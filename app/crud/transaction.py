from typing import TYPE_CHECKING
from uuid import uuid4

import sentry_sdk

from retry_tasks_lib.db.models import RetryTask
from retry_tasks_lib.enums import RetryTaskStatuses
from retry_tasks_lib.utils.asynchronous import async_create_task
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.db.base_class import async_run_query
from app.enums import HttpErrors
from app.models import ProcessedTransaction, RetailerRewards, Transaction

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession


async def create_transaction(
    db_session: "AsyncSession", retailer: RetailerRewards, transaction_data: dict
) -> Transaction:
    async def _query() -> Transaction:
        transaction = Transaction(retailer_id=retailer.id, **transaction_data)
        try:
            db_session.add(transaction)
            await db_session.commit()
        except IntegrityError:
            await db_session.rollback()
            raise HttpErrors.DUPLICATE_TRANSACTION.value  # pylint: disable=raise-missing-from

        return transaction

    return await async_run_query(_query, db_session)


async def delete_transaction(db_session: "AsyncSession", transaction: Transaction) -> None:
    async def _query() -> None:
        await db_session.delete(transaction)
        await db_session.commit()

    await async_run_query(_query, db_session)


async def create_processed_transaction(
    db_session: "AsyncSession", retailer: RetailerRewards, campaign_slugs: list[str], transaction_data: dict
) -> ProcessedTransaction:
    async def _query() -> ProcessedTransaction:
        processed_transaction = ProcessedTransaction(
            retailer_id=retailer.id, campaign_slugs=campaign_slugs, **transaction_data
        )
        try:
            db_session.add(processed_transaction)
            await db_session.commit()
        except IntegrityError as ex:
            sentry_sdk.capture_exception(ex)
            raise HttpErrors.DUPLICATE_TRANSACTION.value  # pylint: disable=raise-missing-from

        return processed_transaction

    return await async_run_query(_query, db_session)


async def create_reward_adjustment_tasks(
    db_session: "AsyncSession", processed_transaction: ProcessedTransaction, adj_amounts: dict
) -> list[int]:
    async def _query() -> list[RetryTask]:
        adjustments = []
        for campaign_slug, amount in adj_amounts.items():
            adjustment_task = await async_create_task(  # pragma: no cover
                db_session,
                task_type_name=settings.REWARD_ADJUSTMENT_TASK_NAME,
                params={
                    "account_holder_uuid": processed_transaction.account_holder_uuid,
                    "retailer_slug": processed_transaction.retailer.slug,
                    "processed_transaction_id": processed_transaction.id,
                    "campaign_slug": campaign_slug,
                    "adjustment_amount": int(amount),
                    "pre_allocation_token": uuid4(),
                },
            )

            adjustments.append(adjustment_task)

        await db_session.commit()
        return adjustments

    return [task.retry_task_id for task in await async_run_query(_query, db_session)]


async def update_reward_adjustment_task_status(
    db_session: "AsyncSession", reward_adjustment_task: RetryTask, status: RetryTaskStatuses
) -> None:
    async def _query() -> None:
        reward_adjustment_task.status = status
        await db_session.commit()

    await async_run_query(_query, db_session)
