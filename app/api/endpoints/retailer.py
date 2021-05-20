import logging

from typing import Any, List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_session, user_is_authorised
from app.enums import CampaignStatuses, HttpErrors
from app.models.retailer import Campaign, RetailerRewards

logger = logging.getLogger("retailer")

router = APIRouter()


def _get_retailer(db_session: Session, retailer_slug: str) -> RetailerRewards:
    retailer = db_session.query(RetailerRewards).filter_by(slug=retailer_slug).first()
    if not retailer:
        raise HttpErrors.INVALID_RETAILER.value

    return retailer


@router.get(
    path="/{retailer_slug}/active-campaign-slugs",
    response_model=List[str],
    dependencies=[Depends(user_is_authorised)],
)
async def get_active_campaigns(
    retailer_slug: str,
    db_session: Session = Depends(get_session),
) -> Any:
    retailer = _get_retailer(db_session, retailer_slug)
    campaigns = db_session.query(Campaign.slug).filter_by(retailer_id=retailer.id, status=CampaignStatuses.ACTIVE).all()
    if not campaigns:
        raise HttpErrors.NO_ACTIVE_CAMPAIGNS.value
    campaign_slugs = [getattr(campaign, "slug") for campaign in campaigns]

    return campaign_slugs
