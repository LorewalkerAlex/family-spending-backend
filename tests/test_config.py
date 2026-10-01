from pathlib import Path

import pytest
from pydantic import ValidationError

from family_spending_backend.config import Settings


def test_settings_load_supported_environment_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "disabled")
    monkeypatch.setenv("FAMILY_SPENDING_ENVIRONMENT", "test")
    monkeypatch.setenv("FAMILY_SPENDING_DATA_ROOT", "var/test-data")
    monkeypatch.setenv("FAMILY_SPENDING_SCHEMA_VERSION", "2")
    monkeypatch.setenv("FAMILY_SPENDING_PARSER_VERSION", "cmb-v1")

    settings = Settings(_env_file=None)

    assert settings.auth_mode == "disabled"
    assert settings.environment == "test"
    assert settings.data_root == Path("var/test-data")
    assert settings.schema_version == "2"
    assert settings.parser_version == "cmb-v1"


def test_only_disabled_auth_mode_is_currently_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_MODE", "token")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_versions_cannot_be_blank() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, parser_version="  ")


@pytest.mark.parametrize(
    ("imap_address", "imap_auth_code"),
    [
        (None, "secret"),
        ("", "secret"),
        ("owner@example.com", None),
        ("owner@example.com", ""),
        ("owner@example.com", "   "),
    ],
)
def test_enabled_email_polling_requires_non_blank_credentials(
    imap_address: str | None,
    imap_auth_code: str | None,
) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            cmb_email_poll_enabled=True,
            imap_address=imap_address,
            imap_auth_code=imap_auth_code,
        )


def test_enabled_email_polling_accepts_complete_credentials() -> None:
    settings = Settings(
        _env_file=None,
        cmb_email_poll_enabled=True,
        imap_address="owner@example.com",
        imap_auth_code="secret",
    )

    assert settings.imap_address == "owner@example.com"
    assert settings.imap_auth_code is not None
    assert settings.imap_auth_code.get_secret_value() == "secret"
