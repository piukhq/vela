from datetime import datetime
from typing import TYPE_CHECKING, List

from sqlalchemy.future import select  # type: ignore
from sqlalchemy.orm import joinedload

from app.db.base_class import async_run_query
from app.enums import CampaignStatuses, HttpErrors
from app.models import Campaign, EarnRule, RetailerRewards, Transaction

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore


async def get_retailer_by_slug(db_session: "AsyncSession", retailer_slug: str) -> RetailerRewards:
    async def _query() -> RetailerRewards:
        return (await db_session.execute(select(RetailerRewards).filter_by(slug=retailer_slug))).scalars().first()

    retailer = await async_run_query(_query, db_session, read_only=True)
    if not retailer:
        raise HttpErrors.INVALID_RETAILER.value

    return retailer


async def get_active_campaign_slugs(
    db_session: "AsyncSession", retailer: RetailerRewards, transaction_time: datetime = None
) -> List[str]:
    async def _query() -> list:
        return (
            await db_session.execute(
                select(Campaign.slug, Campaign.start_date, Campaign.end_date).filter_by(
                    retailer_id=retailer.id, status=CampaignStatuses.ACTIVE
                )
            )
        ).all()

    campaign_rows = await async_run_query(_query, db_session, read_only=True)

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
                    .options(joinedload(EarnRule.campaign))
                    .join(Campaign)
                    .filter(Campaign.slug.in_(campaign_slugs))
                )
            )
            .scalars()
            .all()
        )

    earn_rules = await async_run_query(_query, db_session, read_only=True)
    adjustment_amounts: dict = {}
    for earn in earn_rules:
        if transaction.amount >= earn.threshold:
            if earn.campaign.earn_inc_is_tx_value:
                amount = transaction.amount
            else:
                amount = earn.increment * earn.increment_multiplier

            if earn.campaign.slug in adjustment_amounts:
                adjustment_amounts[earn.campaign.slug] += amount
            else:
                adjustment_amounts[earn.campaign.slug] = amount

    return adjustment_amounts
