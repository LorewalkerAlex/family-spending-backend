"""Explicit effect of an application mutation on derived runtime state."""

from enum import StrEnum


class MutationImpact(StrEnum):
    NO_CHANGE = "no_change"
    FEEDBACK_ONLY = "feedback_only"
    AUTOMATION_ONLY = "automation_only"
    PROJECTIONS = "projections"
    ENRICHMENTS_AND_PROJECTIONS = "enrichments_and_projections"
    TRANSACTIONS_AND_DOWNSTREAM = "transactions_and_downstream"
    FULL_REBUILD = "full_rebuild"
