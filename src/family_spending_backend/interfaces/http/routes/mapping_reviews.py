"""Mapping Review workspace, preview, and guarded apply API."""

from typing import Annotated

from fastapi import APIRouter, Depends

from family_spending_backend.application.context import RequestContext
from family_spending_backend.domain.recommendation import MappingRecommendation
from family_spending_backend.interfaces.http.contracts import (
    ERROR_RESPONSES,
    ApiMeta,
    ApiResponse,
)
from family_spending_backend.interfaces.http.dependencies import (
    ContainerDependency,
    get_request_context,
)
from family_spending_backend.interfaces.http.mapping_contracts import (
    MappingRecommendationAlternativeData,
    MappingRecommendationData,
    MappingRecommendationRequest,
    MappingReviewApplyData,
    MappingReviewApplyRequest,
    MappingReviewItemData,
    MappingReviewPreviewData,
    MappingReviewRequest,
    MappingReviewWorkspaceData,
    MerchantMappingOptionData,
)

router = APIRouter(prefix="/mapping-reviews", tags=["mapping-reviews"], responses=ERROR_RESPONSES)
RequestContextDependency = Annotated[RequestContext, Depends(get_request_context)]


def _recommendation_data(item: MappingRecommendation) -> MappingRecommendationData:
    return MappingRecommendationData(
        description=item.description,
        merchant=item.merchant,
        category=item.category,
        rank_score=item.rank_score,
        score_margin=item.score_margin,
        confidence=item.confidence,
        origin=item.origin,
        is_new_merchant=item.is_new_merchant,
        category_basis=item.category_basis,
        matched_description=item.matched_description,
        evidence=list(item.evidence),
        signals=dict(item.signals),
        alternatives=[
            MappingRecommendationAlternativeData.model_validate(value, from_attributes=True)
            for value in item.alternatives
        ],
        model_version=item.model_version,
    )


@router.get("", response_model=ApiResponse[MappingReviewWorkspaceData])
def get_workspace(
    container: ContainerDependency, context: RequestContextDependency
) -> ApiResponse[MappingReviewWorkspaceData]:
    workspace = container.mapping_review_service.workspace()
    data = MappingReviewWorkspaceData(
        items=[
            MappingReviewItemData(
                description=item.description,
                transaction_count=item.transaction_count,
                total_amount=item.total_amount,
                currency=item.currency,
                latest_date=item.latest_date,
                source_types=list(item.source_types),
                transaction_only_exception_count=item.transaction_only_exception_count,
                recommendation=_recommendation_data(item.recommendation),
            )
            for item in workspace.items
        ],
        merchants=[
            MerchantMappingOptionData.model_validate(item, from_attributes=True)
            for item in workspace.merchants
        ],
        categories=list(workspace.categories),
    )
    return ApiResponse(
        data=data,
        meta=ApiMeta(request_id=context.request_id),
    )


@router.post("/recommend", response_model=ApiResponse[MappingRecommendationData])
def recommend_mapping(
    payload: MappingRecommendationRequest,
    container: ContainerDependency,
    context: RequestContextDependency,
) -> ApiResponse[MappingRecommendationData]:
    recommendation = container.mapping_review_service.recommend(payload.description)
    return ApiResponse(
        data=_recommendation_data(recommendation),
        meta=ApiMeta(request_id=context.request_id),
    )


@router.post("/preview", response_model=ApiResponse[MappingReviewPreviewData])
def preview_mapping(
    payload: MappingReviewRequest,
    container: ContainerDependency,
    context: RequestContextDependency,
) -> ApiResponse[MappingReviewPreviewData]:
    preview = container.mapping_review_service.preview(
        description=payload.description,
        merchant=payload.merchant,
        category=payload.category,
    )
    return ApiResponse(
        data=MappingReviewPreviewData.model_validate(preview, from_attributes=True),
        meta=ApiMeta(request_id=context.request_id),
    )


@router.post("/apply", response_model=ApiResponse[MappingReviewApplyData])
def apply_mapping(
    payload: MappingReviewApplyRequest,
    container: ContainerDependency,
    context: RequestContextDependency,
) -> ApiResponse[MappingReviewApplyData]:
    preview = container.mapping_review_service.apply(
        description=payload.description,
        merchant=payload.merchant,
        category=payload.category,
        preview_token=payload.preview_token,
        confirm_new_merchant=payload.confirm_new_merchant,
    )
    return ApiResponse(
        data=MappingReviewApplyData(
            preview=MappingReviewPreviewData.model_validate(preview, from_attributes=True),
            mutation_impact="enrichments_and_projections",
        ),
        meta=ApiMeta(request_id=context.request_id),
    )
