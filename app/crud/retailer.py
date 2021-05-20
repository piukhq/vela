from typing import List

from sqlalchemy.orm import Session

from app.enums import CampaignStatuses, HttpErrors
from app.models.retailer import Campaign, RetailerRewards


def get_active_campaigns(retailer: RetailerRewards, db_session: Session) -> List[str]:
    campaign_slug_rows = (
        db_session.query(Campaign.slug).filter_by(retailer_id=retailer.id, status=CampaignStatuses.ACTIVE).all()
    )
    if not campaign_slug_rows:
        raise HttpErrors.NO_ACTIVE_CAMPAIGNS.value

    return [row[0] for row in campaign_slug_rows]
