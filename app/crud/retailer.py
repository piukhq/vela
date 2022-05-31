from typing import TYPE_CHECKING

from sqlalchemy.future import select
from sqlalchemy.orm import joinedload

from app.db.base_class import async_run_query
from app.enums import CampaignStatuses, HttpErrors, LoyaltyTypes, TransactionProcessingStatuses
from app.models import Campaign, EarnRule, RetailerRewards, Transaction
from app.models.retailer import RetailerStore

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


def _calculate_amount_and_set_threshold(
    adjustment_amounts: dict[str, dict], tx_amount: int, campaign: Campaign, earn_rule: EarnRule
) -> None:

    # NOTE: Business logic mandates that the earn rules of a campaign must have the same threshold.
    # in case of discrepacies we set the threshold to the lowest af all thresholds.
    if adjustment_amounts[campaign.slug]["threshold"]:
        adjustment_amounts[campaign.slug]["threshold"] = min(
            adjustment_amounts[campaign.slug]["threshold"], earn_rule.threshold
        )
    else:
        adjustment_amounts[campaign.slug]["threshold"] = earn_rule.threshold

    if campaign.loyalty_type == LoyaltyTypes.ACCUMULATOR:

        if earn_rule.max_amount and tx_amount > earn_rule.max_amount:
            adjustment_amounts[campaign.slug]["amount"] += earn_rule.max_amount
            adjustment_amounts[campaign.slug]["accepted"] = True

        # pylint: disable=chained-comparison
        elif (tx_amount < 0 and campaign.reward_rule.allocation_window > 0) or tx_amount >= earn_rule.threshold:
            adjustment_amounts[campaign.slug]["amount"] += tx_amount * earn_rule.increment_multiplier
            adjustment_amounts[campaign.slug]["accepted"] = True

    elif campaign.loyalty_type == LoyaltyTypes.STAMPS and tx_amount >= earn_rule.threshold:
        adjustment_amounts[campaign.slug]["amount"] += earn_rule.increment * earn_rule.increment_multiplier
        adjustment_amounts[campaign.slug]["accepted"] = True


def _calculate_transaction_amounts_for_each_earn_rule(campaigns: list[Campaign], transaction: Transaction) -> dict:
    adjustment_amounts: dict[str, dict] = {}

    # pylint: disable=chained-comparison
    for campaign in campaigns:
        adjustment_amounts[campaign.slug] = {
            "type": campaign.loyalty_type,
            "amount": 0,
            "threshold": None,
            "accepted": False,
        }

        for earn_rule in campaign.earn_rules:
            _calculate_amount_and_set_threshold(adjustment_amounts, transaction.amount, campaign, earn_rule)

    return adjustment_amounts


async def get_adjustment_amounts(
    db_session: "AsyncSession", transaction: Transaction, campaign_slugs: list[str]
) -> dict:
    async def _query() -> list[EarnRule]:
        return (
            (
                await db_session.execute(
                    select(Campaign)
                    .options(joinedload(Campaign.earn_rules), joinedload(Campaign.reward_rule))
                    .where(Campaign.slug.in_(campaign_slugs))
                )
            )
            .unique()
            .scalars()
            .all()
        )

    campaigns = await async_run_query(_query, db_session, rollback_on_exc=False)
    return _calculate_transaction_amounts_for_each_earn_rule(campaigns, transaction)


async def get_retailer_store_name_by_mid(db_session: "AsyncSession", retailer_id: int, mid: str) -> str | None:
    async def _query() -> str | None:
        return (
            await db_session.execute(
                select(RetailerStore.store_name).where(
                    RetailerStore.mid == mid,
                    RetailerStore.retailer_id == retailer_id,
                )
            )
        ).scalar_one_or_none()

    return await async_run_query(_query, db_session)
