"""Current authentication adapter."""

from family_spending_backend.application.context import Principal
from family_spending_backend.application.ports.authentication import AuthenticationRequest


class DisabledAuthenticator:
    """Resolve every request to the single household owner."""

    def authenticate(self, request: AuthenticationRequest) -> Principal:
        del request
        return Principal(user_id="owner", roles=("owner",))
