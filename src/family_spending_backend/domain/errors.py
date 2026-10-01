"""Domain-level failures."""


class DomainInvariantError(ValueError):
    """A stable financial domain invariant was violated."""
