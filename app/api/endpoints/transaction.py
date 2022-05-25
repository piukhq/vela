import asyncio

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud
from app.api.deps import get_session, retailer_is_valid, user_is_authorised
from app.api.tasks import enqueue_many_tasks
from app.internal_requests import validate_account_holder_uuid
from app.models import RetailerRewards
from app.schemas import CreateTransactionSchema

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

    # asyncpg can't translate tz aware to naive datetimes, remove this once we move to psycopg3.
    transaction_data["datetime"] = transaction_data["datetime"].replace(tzinfo=None)
    # ---------------------------------------------------------------------------------------- #

    transaction = await crud.create_transaction(db_session, retailer, transaction_data)
    active_campaign_slugs = await crud.get_active_campaign_slugs(db_session, retailer, transaction)
    adjustment_amounts: dict = await crud.get_adjustment_amounts(db_session, transaction, active_campaign_slugs)

    processed_transaction = await crud.create_processed_transaction(
        db_session, retailer, active_campaign_slugs, transaction
    )
    await crud.delete_transaction(db_session, transaction)
    is_refund: bool = processed_transaction.amount < 0

    if adjustment_amounts:
        adjustment_tasks_ids = await crud.create_reward_adjustment_tasks(
            db_session, processed_transaction, adjustment_amounts
        )
        asyncio.create_task(enqueue_many_tasks(retry_tasks_ids=adjustment_tasks_ids))

        if is_refund:
            response = "Refund accepted"
        else:
            response = "Awarded"

    else:

        if is_refund:
            response = "Refunds not accepted"
        else:
            response = "Threshold not met"

    return response
