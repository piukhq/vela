import asyncio

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud
from app.api.deps import get_session, retailer_is_valid, user_is_authorised
from app.api.tasks import enqueue_many_tasks
from app.core.config import settings
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
    except HTTPException as e:
        # This would actually be an invalid status request
        if e.detail["code"] == "NO_ACTIVE_CAMPAIGNS":  # type: ignore
            raise HttpErrors.INVALID_STATUS_REQUESTED.value

    # If you've requested to end or cancel all of your active campaigns..
    if set(active_campaign_slugs).issubset(set(campaign_slugs)):
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
    if missing_campaigns:
        errors[HttpsErrorTemplates.NO_CAMPAIGN_FOUND] = missing_campaigns
        status_code = status.HTTP_404_NOT_FOUND

    valid_campaigns: list[Campaign] = []
    for campaign in campaigns:
        if requested_status.is_valid_status_transition(current_status=campaign.status):
            if not is_activation or campaign.is_activable():
                valid_campaigns.append(campaign)
            else:
                status_code = status.HTTP_409_CONFLICT
                errors[HttpsErrorTemplates.MISSING_CAMPAIGN_COMPONENTS].append(campaign.slug)
        else:
            status_code = status.HTTP_409_CONFLICT
            errors[HttpsErrorTemplates.INVALID_STATUS_REQUESTED].append(campaign.slug)

    async def _query(campaigns: list[Campaign]) -> None:
        for campaign in campaigns:
            campaign.status = requested_status
            now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
            if requested_status in (CampaignStatuses.CANCELLED, CampaignStatuses.ENDED):
                campaign.end_date = now
            elif requested_status == CampaignStatuses.ACTIVE:
                campaign.start_date = now

        await db_session.commit()

    await async_run_query(_query, db_session, campaigns=valid_campaigns)

    formatted_errors = [
        error_type.value_with_slugs(campaign_slugs) for error_type, campaign_slugs in errors.items() if campaign_slugs
    ]
    return formatted_errors, status_code


@router.post(
    path="/{retailer_slug}/campaigns/status_change",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(user_is_authorised)],
)
async def campaigns_status_change(
    payload: CampaignsStatusChangeSchema,
    retailer: RetailerRewards = Depends(retailer_is_valid),
    db_session: AsyncSession = Depends(get_session),
) -> Any:
    balance_task_type: str = settings.CREATE_CAMPAIGN_BALANCES_TASK_NAME

    # Check that this retailer will not be left with no active campaigns
    if payload.requested_status in [CampaignStatuses.ENDED, CampaignStatuses.CANCELLED]:
        await _check_remaining_active_campaigns(
            db_session=db_session, campaign_slugs=payload.campaign_slugs, retailer=retailer
        )
        balance_task_type = settings.DELETE_CAMPAIGN_BALANCES_TASK_NAME

    errors, status_code = await _campaign_status_change(
        db_session=db_session,
        campaign_slugs=payload.campaign_slugs,
        requested_status=payload.requested_status,
        retailer=retailer,
    )

    if errors:  # pragma: no cover
        raise HTTPException(detail=errors, status_code=status_code)

    retry_tasks_ids = await crud.create_reward_status_adjustment_and_campaign_balances_tasks(
        db_session=db_session,
        campaign_slugs=payload.campaign_slugs,
        retailer=retailer,
        status=payload.requested_status,
        balance_task_type=balance_task_type,
    )

    asyncio.create_task(enqueue_many_tasks(retry_tasks_ids=retry_tasks_ids))

    return {}
