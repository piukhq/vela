import logging

from typing import TYPE_CHECKING, Any, Dict, List, Union

from fastapi import APIRouter, Depends
from pydantic import UUID4, ValidationError
from sqlalchemy.future import select
from sqlalchemy.orm import Session

from app.api.deps import get_session, user_is_authorised
from app.enums import CampaignStatuses, HttpErrors
from app.models.retailer import Campaign, RetailerRewards
from app.schemas import CampaignSchema

logger = logging.getLogger("retailer")

router = APIRouter()


def _get_retailer(db_session, retailer_slug: str) -> RetailerRewards:
    retailer = db_session.query(RetailerRewards).filter_by(slug=retailer_slug).first()
    if not retailer:
        raise HttpErrors.INVALID_RETAILER.value

    return retailer


def _get_campaigns(db_session, **query_param: Union[str, int, CampaignStatuses]) -> List[Campaign]:
    campaigns = db_session.query(Campaign).filter_by(**query_param).all()
    if not campaigns:
        raise HttpErrors.NO_ACCOUNT_FOUND.value  # TODO: need no campaigns found I think

    return campaigns


@router.get(
    path="/{retailer_slug}/active-campaign-slugs",
    response_model=CampaignSchema,
    response_model_include={"slug"},
    dependencies=[Depends(user_is_authorised)],
)
async def get_active_campaigns(
    # TODO: where status == active? Loop through and provide only names in output - response_model_* ?
    retailer_slug: str,
    db_session: Session = Depends(get_session),
) -> Any:
    retailer = _get_retailer(db_session, retailer_slug)

    campaigns = _get_campaigns(
        db_session=db_session,
        retailer_id=retailer.id,
        status=CampaignStatuses.ACTIVE,
    )

    return campaigns
