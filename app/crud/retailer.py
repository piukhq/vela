from typing import TYPE_CHECKING, List

from app.db.base_class import retry_query
from app.enums import CampaignStatuses, HttpErrors
from app.models import Campaign, EarnRule, RetailerRewards, Transaction

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def get_active_campaign_slugs(db_session: "Session", retailer: RetailerRewards) -> List[str]:
    with retry_query(session=db_session):
        campaign_slug_rows = (
            db_session.query(Campaign.slug).filter_by(retailer_id=retailer.id, status=CampaignStatuses.ACTIVE).all()
        )
        if not campaign_slug_rows:
            raise HttpErrors.NO_ACTIVE_CAMPAIGNS.value

    return [row[0] for row in campaign_slug_rows]


def check_earn_rule_for_campaigns(db_session: "Session", transaction: Transaction, campaign_slugs: List[str]) -> bool:
    with retry_query(session=db_session):
        campaign_earns = db_session.query(EarnRule).join(Campaign).filter(Campaign.slug.in_(campaign_slugs))

    return any(transaction.amount >= earn.threshold for earn in campaign_earns)
