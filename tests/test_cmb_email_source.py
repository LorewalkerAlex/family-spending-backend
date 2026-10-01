from datetime import date
from decimal import Decimal
from email.message import EmailMessage

import pytest

from family_spending_backend.sources.cmb_email.cache import CmbParserCache
from family_spending_backend.sources.cmb_email.evidence import CmbEmailEvidence
from family_spending_backend.sources.cmb_email.parser import (
    CmbEmailParseError,
    complete_mmdd,
    parse_cmb_email,
)


def table(cells: list[str], *, width: str = "643", height: str = "18") -> str:
    body = "".join(f"<td>{cell}</td>" for cell in cells)
    return f'<table width="{width}" height="{height}"><tr>{body}</tr></table>'


def transaction_row(mmdd: str, post_mmdd: str, description: str, amount: str) -> str:
    return table(["", mmdd, post_mmdd, description, amount, "4529", "CN", amount])


def repayment_row() -> str:
    return table(["", "", "0827", "跨行转账还款", "¥ -100.00", "4529", "", "-100.00"])


def make_cmb_email(
    html_parts: list[str], email_date: str = "Wed, 10 Sep 2025 08:00:00 +0800"
) -> bytes:
    message = EmailMessage()
    message["Date"] = email_date
    message["Subject"] = "招商银行信用卡电子账单"
    message.set_content("fallback")
    for html in html_parts:
        message.add_alternative(html, subtype="html", charset="utf-8")
    return message.as_bytes()


def test_parse_transaction_and_skip_repayment_with_stable_locator() -> None:
    evidence = CmbEmailEvidence(
        make_cmb_email(
            [repayment_row() + transaction_row("0811", "0812", "支付宝-测试", "¥ -7.81")]
        )
    )
    first = parse_cmb_email(evidence)
    second = parse_cmb_email(evidence)
    assert first.statement_date == date(2025, 9, 10)
    assert first.skipped_repayments == 1
    assert first.records[0].amount == Decimal("-7.81")
    assert first.records[0].transaction_date == date(2025, 8, 11)
    assert first.records[0].identity.record_locator.endswith("/table:2")
    assert first.records[0].id == second.records[0].id


def test_duplicate_rows_have_distinct_ids_and_ignored_tables_still_count() -> None:
    row = transaction_row("0811", "0812", "same", "2.00")
    ignored = table(["not", "a", "transaction"])
    parsed = parse_cmb_email(CmbEmailEvidence(make_cmb_email([ignored + row + row])))
    assert len(parsed.records) == 2
    assert parsed.records[0].id != parsed.records[1].id
    assert parsed.records[0].identity.record_locator.endswith("/table:2")
    assert parsed.records[1].identity.record_locator.endswith("/table:3")


def test_parser_rejects_ambiguous_parts_bad_amount_and_bad_dateless_row() -> None:
    valid = transaction_row("0811", "0812", "first", "1.00")
    with pytest.raises(CmbEmailParseError, match="Multiple CMB"):
        parse_cmb_email(CmbEmailEvidence(make_cmb_email([valid, valid])))
    with pytest.raises(CmbEmailParseError, match="Invalid CMB amount"):
        parse_cmb_email(
            CmbEmailEvidence(make_cmb_email([transaction_row("0811", "0812", "bad", "NaN")]))
        )
    unexpected = table(["", "", "0827", "adjustment", "-100", "4529", "", "-100"])
    with pytest.raises(CmbEmailParseError, match="Unexpected date-less row"):
        parse_cmb_email(CmbEmailEvidence(make_cmb_email([unexpected])))


def test_year_completion_and_versioned_parser_cache() -> None:
    assert complete_mmdd("1210", date(2026, 1, 10)) == date(2025, 12, 10)
    evidence = CmbEmailEvidence(
        make_cmb_email([transaction_row("0811", "0812", "merchant", "1.00")])
    )
    calls = 0

    def counting_parser(item: CmbEmailEvidence):
        nonlocal calls
        calls += 1
        return parse_cmb_email(item)

    cache = CmbParserCache("parser-v1", parser=counting_parser)
    assert cache.get_or_parse(evidence) is cache.get_or_parse(evidence)
    assert calls == 1
    assert cache.parser_cache_counts() == (1, 1)
