from collections import defaultdict
from typing import TYPE_CHECKING

from sqlalchemy.future import select
from sqlalchemy.orm import joinedload

from app.db.base_class import async_run_query
from app.enums import CampaignStatuses, HttpErrors, LoyaltyTypes, TransactionProcessingStatuses
from app.models import Campaign, EarnRule, RetailerRewards, Transaction

if TYPE_CHECKING:  # pragma: no cover

    from sqlalchemy.ext.asyncio import AsyncSession


async def get_retailer_by_slug(db_session: "AsyncSession", retailer_slug: str) -> RetailerRewards:
    async def _query() -> RetailerRewards | None:
        return (
            await db_session.execute(select(RetailerRewards).where(RetailerRewards.slug == retailer_slug))
        ).scalar_one_or_none()

    retailer = await async_run_query(_query, db_session, rollback_on_exc=False)
    if not retailer:
        raise HttpErrors.INVALID_RETAILER.value

    return retailer


async def get_active_campaign_slugs(
    db_session: "AsyncSession", retailer: RetailerRewards, transaction: Transaction = None
) -> list[str]:
    async def _query() -> list:
        return (
            await db_session.execute(
                select(Campaign.slug, Campaign.start_date, Campaign.end_date).filter_by(
                    retailer_id=retailer.id, status=CampaignStatuses.ACTIVE
                )
            )
        ).all()

    campaign_rows = await async_run_query(_query, db_session, rollback_on_exc=False)

    if transaction is not None:
        valid_campaigns = [
            slug
            for slug, start, end in campaign_rows
            if start <= transaction.datetime and (end is None or end > transaction.datetime)
        ]

    else:
        valid_campaigns = [row[0] for row in campaign_rows]

    async def _update_tx_status(*, tx: Transaction) -> None:
        tx.status = TransactionProcessingStatuses.NO_ACTIVE_CAMPAIGNS
        await db_session.commit()

    if not valid_campaigns:
        if transaction is not None:
            await async_run_query(_update_tx_status, db_session, tx=transaction)

        raise HttpErrors.NO_ACTIVE_CAMPAIGNS.value

    return valid_campaigns


def _calculate_transaction_amounts_from_earn_rules(earn_rules: list[EarnRule], transaction: Transaction) -> dict:
    adjustment_amounts: defaultdict = defaultdict(int)

    # pylint: disable=chained-comparison
    for earn_rule in earn_rules:
        if earn_rule.campaign.loyalty_type == LoyaltyTypes.ACCUMULATOR:
            if earn_rule.max_amount and transaction.amount > earn_rule.max_amount:
                adjustment_amounts[earn_rule.campaign.slug] += earn_rule.max_amount
            elif (
                transaction.amount < 0 and earn_rule.campaign.reward_rule.allocation_window > 0
            ) or transaction.amount >= earn_rule.threshold:
                adjustment_amounts[earn_rule.campaign.slug] += transaction.amount * earn_rule.increment_multiplier

        elif earn_rule.campaign.loyalty_type == LoyaltyTypes.STAMPS and transaction.amount >= earn_rule.threshold:
            adjustment_amounts[earn_rule.campaign.slug] += earn_rule.increment * earn_rule.increment_multiplier

    return dict(adjustment_amounts)


async def get_adjustment_amounts(
    db_session: "AsyncSession", transaction: Transaction, campaign_slugs: list[str]
) -> dict:
    async def _query() -> list[EarnRule]:
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

    return _calculate_transaction_amounts_from_earn_rules(earn_rules, transaction)
