from datetime import datetime
from typing import TYPE_CHECKING, List

from app.db.base_class import retry_query
from app.enums import CampaignStatuses, HttpErrors
from app.models import Campaign, EarnRule, RetailerRewards, Transaction

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def get_active_campaign_slugs(
    db_session: "Session", retailer: RetailerRewards, transaction_time: datetime = None
) -> List[str]:

    with retry_query(session=db_session):
        campaign_rows = (
            db_session.query(Campaign.slug, Campaign.start_date, Campaign.end_date)
            .filter_by(retailer_id=retailer.id, status=CampaignStatuses.ACTIVE)
            .all()
        )

    if transaction_time is not None:
        valid_campaigns = [
            slug
            for slug, start, end in campaign_rows
            if start <= transaction_time and (end is None or end > transaction_time)
        ]

    else:
        valid_campaigns = [row[0] for row in campaign_rows]

    if not valid_campaigns:
        raise HttpErrors.NO_ACTIVE_CAMPAIGNS.value

    return valid_campaigns


def check_earn_rule_for_campaigns(db_session: "Session", transaction: Transaction, campaign_slugs: List[str]) -> bool:
    with retry_query(session=db_session):
        campaign_earns = db_session.query(EarnRule).join(Campaign).filter(Campaign.slug.in_(campaign_slugs))

    return any(transaction.amount >= earn.threshold for earn in campaign_earns)
