"""Typed HTTP-to-application dependency boundary."""

from typing import Annotated

from fastapi import Depends, Request

from family_spending_backend.application.context import RequestContext
from family_spending_backend.application.ports.authentication import AuthenticationRequest
from family_spending_backend.bootstrap import ApplicationContainer


def get_container(request: Request) -> ApplicationContainer:
    container: ApplicationContainer = request.app.state.container
    return container


ContainerDependency = Annotated[ApplicationContainer, Depends(get_container)]


def get_request_context(request: Request) -> RequestContext:
    credentials = AuthenticationRequest(
        authorization=request.headers.get("authorization"),
    )
    principal = get_container(request).authenticator.authenticate(credentials)
    return RequestContext(
        request_id=request.state.request_id,
        principal=principal,
    )
