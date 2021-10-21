from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore

from app import crud
from app.api.deps import get_session, retailer_is_valid, user_is_authorised
from app.db.base_class import async_run_query
from app.enums import CampaignStatuses, HttpErrors
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
        if e.detail["error"] == "NO_ACTIVE_CAMPAIGNS":  # type: ignore
            raise HttpErrors.INVALID_STATUS_REQUESTED.value

    # If you've requested to end or cancel all of your active campaigns..
    if set(active_campaign_slugs).issubset(set(campaign_slugs)):
        raise HttpErrors.INVALID_STATUS_REQUESTED.value


async def _campaign_status_change(
    db_session: "AsyncSession", campaign_slugs: list[str], requested_status: CampaignStatuses
) -> tuple[list[HttpErrors], list[str]]:
    async def _query(campaign: Campaign) -> None:
        campaign.status = requested_status  # type: ignore
        await db_session.commit()

    errors: list[HttpErrors] = []
    failed_campaign_slugs: list[str] = []
    campaigns: list[Campaign] = await crud.get_campaigns_by_slug(db_session=db_session, campaign_slugs=campaign_slugs)
    for campaign in campaigns:
        if requested_status.is_valid_status_transition(current_status=campaign.status):  # type: ignore
            await async_run_query(_query, db_session, campaign=campaign)
        else:
            errors.append(HttpErrors.INVALID_STATUS_REQUESTED)
            failed_campaign_slugs.append(campaign.slug)

    # Add in any campaigns that were not found
    for campaign_slug_not_found in set(campaign_slugs) - set([campaign.slug for campaign in campaigns]):
        errors.append(HttpErrors.NO_CAMPAIGN_FOUND)
        failed_campaign_slugs.append(campaign_slug_not_found)

    return errors, failed_campaign_slugs


@router.post(
    path="/{retailer_slug}/campaigns/status_change",
    response_model=str,
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

    errors, failed_campaign_slugs = await _campaign_status_change(
        db_session=db_session, campaign_slugs=payload.campaign_slugs, requested_status=payload.requested_status
    )

    if errors:  # pragma: no cover
        # If there are only NO_CAMPAIGN_FOUND errors AND ALL the campaign_slugs provided produced this error
        if HttpErrors.NO_CAMPAIGN_FOUND in errors and len(errors) == len(payload.campaign_slugs):
            raise HttpErrors.NO_CAMPAIGN_FOUND.value
        # If there are only INVALID_STATUS_REQUEST errors AND ALL the campaign_slugs provided produced this error
        elif HttpErrors.INVALID_STATUS_REQUESTED in errors and len(errors) == len(payload.campaign_slugs):
            raise HttpErrors.INVALID_STATUS_REQUESTED.value
        # If there are (possibly mixed) errors, but some requested changes succeeded, inform the end user
        elif errors:
            raise HTTPException(
                detail={
                    "display_message": "Not all campaigns were updated as requested.",
                    "error": "INCOMPLETE_STATUS_UPDATE",
                    "failed_campaigns": failed_campaign_slugs,
                },
                status_code=status.HTTP_409_CONFLICT,
            )