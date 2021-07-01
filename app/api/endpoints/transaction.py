import asyncio

from typing import Any, List

import rq
import sentry_sdk

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore

from app import crud
from app.api.deps import get_session, retailer_is_valid, user_is_authorised
from app.core.config import redis, settings
from app.db.session import AsyncSessionMaker
from app.enums import RewardAdjustmentStatuses
from app.internal_requests import validate_account_holder_uuid
from app.models import RetailerRewards
from app.schemas import CreateTransactionSchema

router = APIRouter()


async def enqueue_reward_adjustment_task(*, reward_adjustment_ids: List[int]) -> None:
    from app.tasks.transaction import adjust_balance

    async with AsyncSessionMaker() as db_session:
        try:
            reward_adjustments = await crud.get_reward_adjustments(db_session, reward_adjustment_ids)
            for reward_adjustment in reward_adjustments:
                q = rq.Queue(settings.REWARD_ADJUSTMENT_TASK_QUEUE, connection=redis)
                q.enqueue(
                    adjust_balance,
                    reward_adjustment_id=reward_adjustment.id,
                    failure_ttl=60 * 60 * 24 * 7,  # 1 week
                )

                await crud.update_reward_adjustment_status(
                    db_session, reward_adjustment, RewardAdjustmentStatuses.IN_PROGRESS
                )

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

    processed_transaction = await crud.create_processed_transaction(
        db_session, retailer, active_campaign_slugs, transaction_data
    )
    await crud.delete_transaction(db_session, transaction)

    if adjustment_amounts:
        adjustment_ids = await crud.create_reward_adjustments(db_session, processed_transaction.id, adjustment_amounts)
        asyncio.create_task(enqueue_reward_adjustment_task(reward_adjustment_ids=adjustment_ids))
        response = "Awarded"
    else:
        response = "Threshold not met"

    return response
