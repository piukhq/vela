from typing import TYPE_CHECKING, List

from sqlalchemy.exc import IntegrityError
from sqlalchemy.future import select  # type: ignore

from app.db.base_class import async_run_query
from app.enums import HttpErrors, RewardAdjustmentStatuses
from app.models import ProcessedTransaction, RetailerRewards, RewardAdjustment, Transaction

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.exc.asyncio import AsyncSession  # type: ignore


async def create_transaction(
    db_session: "AsyncSession", retailer: RetailerRewards, transaction_data: dict
) -> Transaction:
    async def _query() -> Transaction:
        transaction = Transaction(retailer_id=retailer.id, **transaction_data)
        try:
            db_session.add(transaction)
            await db_session.commit()
        except IntegrityError:
            raise HttpErrors.DUPLICATE_TRANSACTION.value

        return transaction

    return await async_run_query(_query, db_session)


async def delete_transaction(db_session: "AsyncSession", transaction: Transaction) -> None:
    async def _query() -> None:
        db_session.delete(transaction)
        await db_session.commit()

    await async_run_query(_query, db_session)


async def create_processed_transaction(
    db_session: "AsyncSession", retailer: RetailerRewards, campaign_slugs: List[str], transaction_data: dict
) -> ProcessedTransaction:
    async def _query() -> ProcessedTransaction:
        processed_transaction = ProcessedTransaction(
            retailer_id=retailer.id, campaign_slugs=campaign_slugs, **transaction_data
        )
        try:
            db_session.add(processed_transaction)
            await db_session.commit()
        except IntegrityError:
            raise HttpErrors.DUPLICATE_TRANSACTION.value

        return processed_transaction

    return await async_run_query(_query, db_session)


async def get_reward_adjustments(db_session: "AsyncSession", reward_adjustment_ids: list) -> List[RewardAdjustment]:
    async def _query() -> List[RewardAdjustment]:
        return (
            (
                await db_session.execute(
                    select(RewardAdjustment)
                    .with_for_update()
                    .filter(
                        RewardAdjustment.id.in_(reward_adjustment_ids),
                        RewardAdjustment.status == RewardAdjustmentStatuses.PENDING,
                    )
                )
            )
            .scalars()
            .all()
        )

    return await async_run_query(_query, db_session, rollback_on_exc=False)


async def create_reward_adjustments(
    db_session: "AsyncSession", processed_transaction_id: int, adj_amounts: dict
) -> List[int]:
    async def _query() -> List[RewardAdjustment]:
        adjustments = []
        for campaign_slug, amount in adj_amounts.items():
            adjustment = RewardAdjustment(
                processed_transaction_id=processed_transaction_id,
                campaign_slug=campaign_slug,
                adjustment_amount=amount,
            )
            db_session.add(adjustment)
            adjustments.append(adjustment)

        await db_session.commit()
        return adjustments

    return [adj.id for adj in await async_run_query(_query, db_session)]


async def update_reward_adjustment_status(
    db_session: "AsyncSession", adjustment: RewardAdjustment, status: RewardAdjustmentStatuses
) -> None:
    async def _query() -> None:
        adjustment.status = status  # type: ignore
        await db_session.commit()

    await async_run_query(_query, db_session)
