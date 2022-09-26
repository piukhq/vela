from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from vela import crud
from vela.api.deps import get_session, retailer_is_valid, user_is_authorised
from vela.models.retailer import RetailerRewards

router = APIRouter()


@router.get(
    path="/{retailer_slug}/active-campaign-slugs",
    response_model=list[str],
    dependencies=[Depends(user_is_authorised)],
)
async def get_active_campaign_slugs(
    retailer: RetailerRewards = Depends(retailer_is_valid),
    db_session: AsyncSession = Depends(get_session),
) -> Any:
    campaigns = await crud.get_active_campaigns(db_session, retailer)
    return [campaign.slug for campaign in campaigns]
