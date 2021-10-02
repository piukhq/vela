from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore

from app import crud
from app.api.deps import get_session, retailer_is_valid, user_is_authorised
from app.db.base_class import async_run_query
from app.enums import CampaignStatuses
from app.models.retailer import Campaign, RetailerRewards
from app.schemas import CampaignsStatusChangeSchema

router = APIRouter()


class CampaignStatusError(Exception):
    pass


async def _campaign_status_change(
    db_session: "AsyncSession", campaign_slugs: list[str], action_type: CampaignStatuses
) -> list[CampaignStatusError]:
    async def _query(campaign: Campaign) -> None:
        campaign.status = action_type  # type: ignore
        await db_session.commit()

    errors: list[CampaignStatusError] = []
    for campaign_slug in campaign_slugs:
        campaign = await crud.get_campaign_by_slug(db_session=db_session, campaign_slug=campaign_slug)
        if campaign:
            if action_type.is_legal_transition(current_status=campaign.status):
                await async_run_query(_query, db_session, campaign=campaign)
            else:
                # TODO this is where a 409 needs to get returned somehow, or a list of them
                errors.append(CampaignStatusError(f"{action_type} not found in allowable transitions for campaign"))
        else:
            errors.append(CampaignStatusError(f"No campaign found for slug {campaign_slug}"))

    return errors


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

    # {
    #   "action_type": "Ended",
    #   "campaign_slugs": [
    #     "test-campaign-1",
    #     "test-campaign-2"
    #   ]
    # }
    # transaction_data = payload.dict(exclude_unset=True)

    errors: list[CampaignStatusError] = await _campaign_status_change(
        db_session=db_session, campaign_slugs=payload.campaign_slugs, action_type=payload.action_type
    )

    # TODO response is 422 if errors or 200 if no errors I think
    response = "Threshold not met"

    return response
