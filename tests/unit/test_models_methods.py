from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from app.enums import CampaignStatuses
from app.models import Campaign, EarnRule, RewardRule

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.models import RetailerRewards


def test_campaign_is_activable_ok(db_session: "Session", retailer: "RetailerRewards") -> None:
    campaign = Campaign(
        name="activable campaign",
        slug="activable-campaign",
        start_date=datetime.utcnow() - timedelta(days=-1),
        retailer_id=retailer.id,
    )
    db_session.add(campaign)
    db_session.flush()

    db_session.add(EarnRule(threshold=200, increment=100, increment_multiplier=1.5, campaign_id=campaign.id))
    db_session.add(RewardRule(reward_goal=150, voucher_type_slug="test-voucher-type", campaign_id=campaign.id))
    db_session.commit()

    assert campaign.is_activable() is True


def test_campaign_is_activable_no_reward_rule(db_session: "Session", retailer: "RetailerRewards") -> None:
    campaign = Campaign(
        name="activable campaign",
        slug="activable-campaign",
        start_date=datetime.utcnow() - timedelta(days=-1),
        retailer_id=retailer.id,
    )
    db_session.add(campaign)
    db_session.flush()

    db_session.add(EarnRule(threshold=200, increment=100, increment_multiplier=1.5, campaign_id=campaign.id))
    db_session.commit()

    assert campaign.is_activable() is False


def test_campaign_is_activable_no_earn_rules(db_session: "Session", retailer: "RetailerRewards") -> None:
    campaign = Campaign(
        name="activable campaign",
        slug="activable-campaign",
        start_date=datetime.utcnow() - timedelta(days=-1),
        retailer_id=retailer.id,
    )
    db_session.add(campaign)
    db_session.flush()

    db_session.add(RewardRule(reward_goal=150, voucher_type_slug="test-voucher-type", campaign_id=campaign.id))
    db_session.commit()

    assert campaign.is_activable() is False


def test_campaign_is_activable_wrong_status(db_session: "Session", retailer: "RetailerRewards") -> None:
    campaign = Campaign(
        name="activable campaign",
        slug="activable-campaign",
        start_date=datetime.utcnow() - timedelta(days=-1),
        retailer_id=retailer.id,
    )
    db_session.add(campaign)
    db_session.flush()

    campaign.status = CampaignStatuses.ENDED
    db_session.add(EarnRule(threshold=200, increment=100, increment_multiplier=1.5, campaign_id=campaign.id))
    db_session.add(RewardRule(reward_goal=150, voucher_type_slug="test-voucher-type", campaign_id=campaign.id))
    db_session.commit()

    assert campaign.is_activable() is False