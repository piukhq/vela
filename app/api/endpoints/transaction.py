import asyncio

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore

from app import crud
from app.api.deps import get_session, retailer_is_valid, user_is_authorised
from app.internal_requests import validate_account_holder_uuid
from app.models import RetailerRewards
from app.schemas import CreateTransactionSchema
from app.tasks.transaction import enqueue_reward_adjustment_tasks

router = APIRouter()


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
    await validate_account_holder_uuid(payload.account_holder_uuid, retailer.slug)
    transaction_data = payload.dict(exclude_unset=True)
    transaction = await crud.create_transaction(db_session, retailer, transaction_data)
    active_campaign_slugs = await crud.get_active_campaign_slugs(db_session, retailer, transaction.datetime)
    adjustment_amounts = await crud.get_adjustment_amounts(db_session, transaction, active_campaign_slugs)

    processed_transaction = await crud.create_processed_transaction(
        db_session, retailer, active_campaign_slugs, transaction_data
    )
    await crud.delete_transaction(db_session, transaction)

    if adjustment_amounts:
        adjustment_tasks_ids = await crud.create_reward_adjustment_tasks(
            db_session, processed_transaction, adjustment_amounts
        )
        asyncio.create_task(enqueue_reward_adjustment_tasks(retry_tasks_ids=adjustment_tasks_ids))
        response = "Awarded"
    else:
        response = "Threshold not met"

    return response
