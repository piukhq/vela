from typing import Any, List

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore

from app import crud
from app.api.deps import get_session, retailer_is_valid, user_is_authorised
from app.models.retailer import RetailerRewards

router = APIRouter()


@router.get(
    path="/{retailer_slug}/active-campaign-slugs",
    response_model=List[str],
    dependencies=[Depends(user_is_authorised)],
)
async def get_active_campaign_slugs(
    retailer: RetailerRewards = Depends(retailer_is_valid),
    db_session: AsyncSession = Depends(get_session),
) -> Any:
    return await crud.get_active_campaign_slugs(db_session, retailer)
