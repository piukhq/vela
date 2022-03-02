from collections import defaultdict
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy.future import select
from sqlalchemy.orm import joinedload

from app.db.base_class import async_run_query
from app.enums import CampaignStatuses, HttpErrors, LoyaltyTypes
from app.models import Campaign, EarnRule, RetailerRewards, Transaction

if TYPE_CHECKING:  # pragma: no cover
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession


async def get_retailer_by_slug(db_session: "AsyncSession", retailer_slug: str) -> RetailerRewards:
    async def _query() -> Optional[RetailerRewards]:
        return (
            await db_session.execute(select(RetailerRewards).where(RetailerRewards.slug == retailer_slug))
        ).scalar_one_or_none()

    retailer = await async_run_query(_query, db_session, rollback_on_exc=False)
    if not retailer:
        raise HttpErrors.INVALID_RETAILER.value

    return retailer


async def get_active_campaign_slugs(
    db_session: "AsyncSession", retailer: RetailerRewards, transaction_time: "datetime" = None
) -> List[str]:
    async def _query() -> list:
        return (
            await db_session.execute(
                select(Campaign.slug, Campaign.start_date, Campaign.end_date).filter_by(
                    retailer_id=retailer.id, status=CampaignStatuses.ACTIVE
                )
            )
        ).all()

    campaign_rows = await async_run_query(_query, db_session, rollback_on_exc=False)

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


async def get_adjustment_amounts(
    db_session: "AsyncSession", transaction: Transaction, campaign_slugs: List[str]
) -> dict:
    async def _query() -> List[EarnRule]:
        return (
            (
                await db_session.execute(
                    select(EarnRule)
                    .join(Campaign)
                    .options(
                        joinedload(EarnRule.campaign, innerjoin=True).joinedload(Campaign.reward_rule, innerjoin=True)
                    )
                    .where(Campaign.slug.in_(campaign_slugs))
                )
            )
            .scalars()
            .all()
        )

    earn_rules = await async_run_query(_query, db_session, rollback_on_exc=False)
    adjustment_amounts: defaultdict = defaultdict(int)

    for earn_rule in earn_rules:
        if (
            transaction.amount < 0
            and earn_rule.campaign.loyalty_type == LoyaltyTypes.ACCUMULATOR
            and earn_rule.campaign.reward_rule.allocation_window
        ):  # i.e. a refund
            adjustment_amounts[earn_rule.campaign.slug] += int(transaction.amount)
        elif transaction.amount >= earn_rule.threshold:
            if earn_rule.campaign.loyalty_type == LoyaltyTypes.ACCUMULATOR:
                amount = int(transaction.amount * earn_rule.increment_multiplier)
            else:
                amount = int(earn_rule.increment * earn_rule.increment_multiplier)

            adjustment_amounts[earn_rule.campaign.slug] += amount

    return dict(adjustment_amounts)
