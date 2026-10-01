"""Authentication boundary used by inbound interfaces."""

from dataclasses import dataclass
from typing import Protocol

from family_spending_backend.application.context import Principal


@dataclass(frozen=True, slots=True)
class AuthenticationRequest:
    """Credential material supplied by an inbound interface."""

    authorization: str | None


class Authenticator(Protocol):
    """Resolve credentials into an application principal."""

    def authenticate(self, request: AuthenticationRequest) -> Principal: ...
