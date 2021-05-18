import logging

from typing import Any, List, Union

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


def _get_campaigns(db_session: Session, **query_param: Union[str, int, CampaignStatuses]) -> List[Campaign]:
    campaigns = db_session.query(Campaign).filter_by(**query_param).all()
    if not campaigns:
        raise HttpErrors.NO_ACTIVE_CAMPAIGNS.value

    return campaigns


def _get_fields_from_rows(rows: List[Union[Campaign, RetailerRewards]], fieldname: str) -> List[Any]:
    """Get a list of field values from a list of row objects"""
    fields = [getattr(row, fieldname) for row in rows]
    return fields


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
    campaigns = _get_campaigns(
        db_session=db_session,
        retailer_id=retailer.id,
        status=CampaignStatuses.ACTIVE,
    )
    campaign_slugs = _get_fields_from_rows(rows=campaigns, fieldname="slug")

    return campaign_slugs
