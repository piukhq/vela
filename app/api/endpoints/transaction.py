import asyncio

from typing import Any, List

import rq
import sentry_sdk

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore
from sqlalchemy.future import select  # type: ignore

from app import crud
from app.api.deps import get_session, retailer_is_valid, user_is_authorised
from app.core.config import redis, settings
from app.db.base_class import async_run_query
from app.db.session import AsyncSessionMaker
from app.enums import RewardAdjustmentStatuses
from app.internal_requests import validate_account_holder_uuid
from app.models import RetailerRewards, RewardAdjustment
from app.schemas import CreateTransactionSchema

router = APIRouter()


async def enqueue_reward_adjustment_task(*, reward_adjustment_ids: List[int]) -> None:
    from app.tasks.transaction import adjust_balance

    async with AsyncSessionMaker() as db_session:
        try:

            async def _get_adjustments() -> List[RewardAdjustment]:
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

            for reward_adjustment in await async_run_query(_get_adjustments, db_session, read_only=True):
                q = rq.Queue(settings.REWARD_ADJUSTMENT_TASK_QUEUE, connection=redis)
                q.enqueue(
                    adjust_balance,
                    reward_adjustment_id=reward_adjustment.id,
                    failure_ttl=60 * 60 * 24 * 7,  # 1 week
                )

                async def _update_status() -> None:
                    reward_adjustment.status = RewardAdjustmentStatuses.IN_PROGRESS
                    await db_session.commit()

                await async_run_query(_update_status, db_session)

        except Exception as ex:
            sentry_sdk.capture_exception(ex)
            await db_session.rollback()


@router.post(
    path="/{retailer_slug}/transaction",
    response_model=str,
    dependencies=[Depends(user_is_authorised)],
)
async def record_transaction(
    payload: CreateTransactionSchema,
    retailer: RetailerRewards = Depends(retailer_is_valid),
    db_session: AsyncSession = Depends(get_session),
) -> Any:
    validate_account_holder_uuid(payload.account_holder_uuid, retailer.slug)
    transaction_data = payload.dict(exclude_unset=True)
    transaction = await crud.create_transaction(db_session, retailer, transaction_data)
    active_campaign_slugs = await crud.get_active_campaign_slugs(db_session, retailer, transaction.datetime)
    adjustment_amounts = await crud.get_adjustment_amounts(db_session, transaction, active_campaign_slugs)

    if adjustment_amounts:
        response = "Awarded"
    else:
        response = "Threshold not met"

    processed_transaction = await crud.create_processed_transaction(
        db_session, retailer, active_campaign_slugs, transaction_data
    )
    await crud.delete_transaction(db_session, transaction)

    adjustment_ids = await crud.create_reward_adjustments(db_session, processed_transaction.id, adjustment_amounts)
    asyncio.create_task(enqueue_reward_adjustment_task(reward_adjustment_ids=adjustment_ids))

    return response
