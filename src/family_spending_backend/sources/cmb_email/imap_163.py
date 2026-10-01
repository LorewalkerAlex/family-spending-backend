"""Read-only 163 IMAP adapter for raw CMB statement messages."""

import base64
import imaplib
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import date, datetime
from email import policy
from email.parser import BytesHeaderParser
from email.utils import parsedate_to_datetime
from typing import Any

HEADER_QUERY = "(BODY.PEEK[HEADER.FIELDS (SUBJECT DATE MESSAGE-ID)])"
RAW_QUERY = "(BODY.PEEK[])"


def parse_since_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%d-%b-%Y").date()
    except ValueError as exc:
        raise ValueError(f"Invalid IMAP since value {value!r}; expected DD-Mon-YYYY") from exc


def encode_mailbox_name(mailbox: str) -> str:
    """Encode a mailbox using IMAP Modified UTF-7 without a runtime dependency."""

    output: list[str] = []
    non_ascii: list[str] = []

    def flush() -> None:
        if not non_ascii:
            return
        encoded = base64.b64encode("".join(non_ascii).encode("utf-16be")).decode()
        output.append("&" + encoded.rstrip("=").replace("/", ",") + "-")
        non_ascii.clear()

    for character in mailbox:
        if " " <= character <= "~":
            flush()
            output.append("&-" if character == "&" else character)
        else:
            non_ascii.append(character)
    flush()
    return "".join(output)


def _fetch_bytes(mail: Any, mail_id: bytes, query: str) -> bytes:
    status, data = mail.fetch(mail_id, query)
    if status == "OK" and data:
        for item in data:
            if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
                return item[1]
    number = mail_id.decode("ascii", errors="replace")
    raise RuntimeError(f"Failed to fetch message {number}: status={status!r}")


def _send_imap_id(mail: Any) -> None:
    imaplib.Commands["ID"] = ("AUTH",)
    status, data = mail._simple_command(
        "ID", '("name" "family-spending-backend" "version" "0.1.0")'
    )
    if status != "OK":
        raise RuntimeError(f"IMAP ID command failed: {data!r}")


@dataclass(frozen=True, slots=True)
class Imap163Connector:
    address: str
    auth_code: str
    host: str = "imap.163.com"
    port: int = 993
    mailbox: str = "INBOX"
    subject_keyword: str = "招商银行信用卡电子账单"
    since: str = "01-Jan-2020"
    timeout_seconds: float = 30.0
    imap_factory: Callable[..., Any] = field(default=imaplib.IMAP4_SSL, repr=False, compare=False)

    def fetch_raw_messages(self) -> tuple[bytes, ...]:
        since_date = parse_since_date(self.since)
        mail = self.imap_factory(self.host, self.port, timeout=self.timeout_seconds)
        logged_in = False
        try:
            status, data = mail.login(self.address, self.auth_code)
            if status != "OK":
                raise RuntimeError(f"IMAP login failed: {data!r}")
            logged_in = True
            _send_imap_id(mail)
            mailbox = encode_mailbox_name(self.mailbox)
            status, data = mail.select(mailbox, readonly=True)
            if status != "OK":
                raise RuntimeError(f"Failed to select mailbox {self.mailbox!r}: {data!r}")
            status, data = mail.search(None, "SENTSINCE", self.since)
            if status != "OK":
                raise RuntimeError(f"IMAP search failed: {data!r}")
            ids = data[0].split() if data and data[0] else []
            matches: list[bytes] = []
            for mail_id in ids:
                header = BytesHeaderParser(policy=policy.default).parsebytes(
                    _fetch_bytes(mail, mail_id, HEADER_QUERY)
                )
                if self.subject_keyword.casefold() not in str(header.get("Subject", "")).casefold():
                    continue
                try:
                    sent = parsedate_to_datetime(str(header.get("Date", ""))).date()
                except (TypeError, ValueError, OverflowError) as exc:
                    raise ValueError(f"Invalid Date header in message {mail_id!r}") from exc
                if sent >= since_date:
                    matches.append(mail_id)
            return tuple(_fetch_bytes(mail, item, RAW_QUERY) for item in matches)
        finally:
            if logged_in:
                with suppress(Exception):
                    mail.logout()
