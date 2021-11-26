import asyncio

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from retry_tasks_lib.utils.asynchronous import enqueue_many_retry_tasks
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud
from app.api.deps import get_session, retailer_is_valid, user_is_authorised
from app.core.config import redis
from app.db.base_class import async_run_query
from app.enums import CampaignStatuses, HttpErrors, HttpsErrorTemplates
from app.models.retailer import Campaign, RetailerRewards
from app.schemas import CampaignsStatusChangeSchema

router = APIRouter()


class CampaignStatusError(Exception):
    pass


async def _check_remaining_active_campaigns(
    db_session: "AsyncSession", campaign_slugs: list[str], retailer: RetailerRewards
) -> None:
    try:
        active_campaign_slugs: list[str] = await crud.get_active_campaign_slugs(db_session, retailer)
    except HTTPException as e:  # pragma: coverage bug 1012
        # This would actually be an invalid status request
        if e.detail["error"] == "NO_ACTIVE_CAMPAIGNS":  # type: ignore
            raise HttpErrors.INVALID_STATUS_REQUESTED.value

    # If you've requested to end or cancel all of your active campaigns..
    if set(active_campaign_slugs).issubset(set(campaign_slugs)):  # pragma: coverage bug 1012
        raise HttpErrors.INVALID_STATUS_REQUESTED.value


async def _campaign_status_change(
    db_session: "AsyncSession", campaign_slugs: list[str], requested_status: CampaignStatuses, retailer: RetailerRewards
) -> tuple[list[dict], int]:
    status_code = status.HTTP_200_OK
    is_activation = requested_status == CampaignStatuses.ACTIVE

    errors: dict[HttpsErrorTemplates, list[str]] = {
        HttpsErrorTemplates.NO_CAMPAIGN_FOUND: [],
        HttpsErrorTemplates.INVALID_STATUS_REQUESTED: [],
        HttpsErrorTemplates.MISSING_CAMPAIGN_COMPONENTS: [],
    }

    campaigns: list[Campaign] = await crud.get_campaigns_by_slug(
        db_session=db_session, campaign_slugs=campaign_slugs, retailer=retailer, load_rules=is_activation
    )
    # Add in any campaigns that were not found
    missing_campaigns = list(set(campaign_slugs) - {campaign.slug for campaign in campaigns})
    if missing_campaigns:  # pragma: coverage bug 1012
        errors[HttpsErrorTemplates.NO_CAMPAIGN_FOUND] = missing_campaigns
        status_code = status.HTTP_404_NOT_FOUND

    valid_campaigns: list[Campaign] = []  # pragma: coverage bug 1012
    for campaign in campaigns:  # pragma: coverage bug 1012
        if requested_status.is_valid_status_transition(current_status=campaign.status):
            if not is_activation or campaign.is_activable():
                valid_campaigns.append(campaign)
            else:
                status_code = status.HTTP_409_CONFLICT
                errors[HttpsErrorTemplates.MISSING_CAMPAIGN_COMPONENTS].append(campaign.slug)
        else:
            status_code = status.HTTP_409_CONFLICT
            errors[HttpsErrorTemplates.INVALID_STATUS_REQUESTED].append(campaign.slug)

    async def _query(campaigns: list[Campaign]) -> None:  # pragma: coverage bug 1012
        for campaign in campaigns:
            campaign.status = requested_status

        await db_session.commit()

    await async_run_query(_query, db_session, campaigns=valid_campaigns)

    formatted_errors = [
        error_type.value_with_slugs(campaign_slugs) for error_type, campaign_slugs in errors.items() if campaign_slugs
    ]
    return formatted_errors, status_code  # pragma: coverage bug 1012


@router.post(
    path="/{retailer_slug}/campaigns/status_change",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(user_is_authorised)],
)
async def campaigns_status_change(
    payload: CampaignsStatusChangeSchema,
    retailer: RetailerRewards = Depends(retailer_is_valid),
    db_session: AsyncSession = Depends(get_session),
) -> Any:

    # Check that this retailer will not be left with no Active campaigns
    if payload.requested_status in [CampaignStatuses.ENDED, CampaignStatuses.CANCELLED]:
        await _check_remaining_active_campaigns(
            db_session=db_session, campaign_slugs=payload.campaign_slugs, retailer=retailer
        )

    errors, status_code = await _campaign_status_change(
        db_session=db_session,
        campaign_slugs=payload.campaign_slugs,
        requested_status=payload.requested_status,
        retailer=retailer,
    )

    if errors:  # pragma: no cover
        raise HTTPException(detail=errors, status_code=status_code)

    adjustment_tasks_ids = await crud.create_voucher_status_adjustment_tasks(
        db_session=db_session,
        campaign_slugs=payload.campaign_slugs,
        retailer=retailer,
        status=payload.requested_status,
    )
    asyncio.create_task(
        enqueue_many_retry_tasks(db_session=db_session, retry_tasks_ids=adjustment_tasks_ids, connection=redis)
    )
