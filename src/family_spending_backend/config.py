"""Process configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated settings for one backend process."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="FAMILY_SPENDING_",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    environment: Literal["development", "test", "production"] = "development"
    data_root: Path = Path("data")
    auth_mode: Literal["disabled"] = Field(
        default="disabled",
        validation_alias=AliasChoices("AUTH_MODE", "FAMILY_SPENDING_AUTH_MODE"),
    )
    schema_version: str = "1"
    parser_version: str = "cmb-v1"
    scheduler_enabled: bool = True
    scheduler_interval_seconds: float = 300.0
    cmb_email_poll_enabled: bool = False
    email_poll_interval_seconds: float = 300.0
    imap_address: str | None = None
    imap_auth_code: SecretStr | None = None
    imap_host: str = "imap.163.com"
    imap_port: int = 993
    imap_mailbox: str = "INBOX"
    imap_subject_keyword: str = "招商银行信用卡电子账单"
    imap_since: str = "01-Jan-2020"
    imap_timeout_seconds: float = 30.0
    bind_host: str = "127.0.0.1"
    bind_port: int = 8000

    @field_validator("scheduler_interval_seconds", "email_poll_interval_seconds")
    @classmethod
    def interval_must_be_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("interval must be positive")
        return value

    @field_validator("imap_port")
    @classmethod
    def port_must_be_valid(cls, value: int) -> int:
        if value < 1 or value > 65535:
            raise ValueError("IMAP port must be between 1 and 65535")
        return value

    @field_validator("bind_port")
    @classmethod
    def bind_port_must_be_valid(cls, value: int) -> int:
        if value < 1 or value > 65535:
            raise ValueError("bind port must be between 1 and 65535")
        return value

    @field_validator("imap_timeout_seconds")
    @classmethod
    def timeout_must_be_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("IMAP timeout must be positive")
        return value

    @model_validator(mode="after")
    def enabled_imap_requires_credentials(self) -> Settings:
        auth_code = (
            self.imap_auth_code.get_secret_value().strip()
            if self.imap_auth_code is not None
            else ""
        )
        if self.cmb_email_poll_enabled and (not self.imap_address or not auth_code):
            raise ValueError("Enabled CMB email polling requires IMAP address and auth code")
        return self

    @field_validator("schema_version", "parser_version")
    @classmethod
    def version_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("version must not be blank")
        return normalized


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide validated settings instance."""

    return Settings()
