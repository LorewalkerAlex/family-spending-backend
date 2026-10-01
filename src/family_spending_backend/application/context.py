"""Request-scoped application identity."""

from contextvars import ContextVar, Token
from dataclasses import dataclass

_request_id: ContextVar[str] = ContextVar("family_spending_request_id", default="background")


def current_request_id() -> str:
    return _request_id.get()


def bind_request_id(request_id: str) -> Token[str]:
    return _request_id.set(request_id)


def reset_request_id(token: Token[str]) -> None:
    _request_id.reset(token)


@dataclass(frozen=True, slots=True)
class Principal:
    """Authenticated application identity, independent of HTTP credentials."""

    user_id: str
    roles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Context passed from an interface to application use cases."""

    request_id: str
    principal: Principal
