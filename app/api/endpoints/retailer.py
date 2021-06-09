from typing import Any, List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_session, retailer_is_valid, user_is_authorised
from app.db.base_class import retry_query
from app.enums import CampaignStatuses, HttpErrors
from app.models.retailer import Campaign, RetailerRewards

router = APIRouter()


@router.get(
    path="/{retailer_slug}/active-campaign-slugs",
    response_model=List[str],
    dependencies=[Depends(user_is_authorised)],
)
async def get_active_campaign_slugs(
    retailer: RetailerRewards = Depends(retailer_is_valid),
    db_session: Session = Depends(get_session),
) -> Any:
    with retry_query(session=db_session):
        campaign_slug_rows = (
            db_session.query(Campaign.slug).filter_by(retailer_id=retailer.id, status=CampaignStatuses.ACTIVE).all()
        )
        if not campaign_slug_rows:
            raise HttpErrors.NO_ACTIVE_CAMPAIGNS.value

        return [row[0] for row in campaign_slug_rows]
