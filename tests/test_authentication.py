from family_spending_backend.application.context import Principal
from family_spending_backend.application.ports.authentication import AuthenticationRequest
from family_spending_backend.interfaces.http.authentication import DisabledAuthenticator


def test_disabled_authenticator_returns_the_single_owner_principal() -> None:
    authenticator = DisabledAuthenticator()

    principal = authenticator.authenticate(AuthenticationRequest(authorization=None))

    assert principal == Principal(user_id="owner", roles=("owner",))
