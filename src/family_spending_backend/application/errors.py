"""Stable application failure categories for inbound interfaces."""


class ApplicationError(RuntimeError):
    pass


class ApplicationConflictError(ApplicationError):
    pass


class ApplicationNotFoundError(ApplicationError):
    pass


class ApplicationValidationError(ApplicationError):
    pass
