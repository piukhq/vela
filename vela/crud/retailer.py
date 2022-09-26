from typing import TYPE_CHECKING

from sqlalchemy.future import select
from sqlalchemy.orm import joinedload

from vela.db.base_class import async_run_query
from vela.enums import CampaignStatuses, HttpErrors, TransactionProcessingStatuses
from vela.models import Campaign, EarnRule, RetailerRewards, Transaction
from vela.models.retailer import RetailerStore

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


async def get_active_campaigns(
    db_session: "AsyncSession", retailer: RetailerRewards, transaction: Transaction = None, join_rules: bool = False
) -> list[Campaign]:

    opt = [joinedload(Campaign.earn_rules), joinedload(Campaign.reward_rule)] if join_rules else []

    async def _query() -> list:
        return (
            (
                await db_session.execute(
                    select(Campaign)
                    .options(*opt)
                    .where(Campaign.retailer_id == retailer.id, Campaign.status == CampaignStatuses.ACTIVE)
                )
            )
            .unique()
            .scalars()
            .all()
        )

    campaigns = await async_run_query(_query, db_session, rollback_on_exc=False)

    campaigns = (
        [
            campaign
            for campaign in campaigns
            if campaign.start_date <= transaction.datetime
            and (campaign.end_date is None or campaign.end_date > transaction.datetime)
        ]
        if transaction is not None
        else campaigns
    )

    if not campaigns:
        if transaction:

            async def _update_tx_status(*, tx: Transaction) -> None:
                tx.status = TransactionProcessingStatuses.NO_ACTIVE_CAMPAIGNS
                await db_session.commit()

            await async_run_query(_update_tx_status, db_session, tx=transaction)

        raise HttpErrors.NO_ACTIVE_CAMPAIGNS.value

    return campaigns


async def get_campaign_with_rules(db_session: "AsyncSession", campaign_slugs: list[str]) -> list[Campaign]:
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

    return await async_run_query(_query, db_session, rollback_on_exc=False)


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
