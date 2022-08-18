import asyncio

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud
from app.activity_utils.tasks import send_processed_tx_activity
from app.api.deps import get_session, retailer_is_valid, user_is_authorised
from app.api.tasks import enqueue_many_tasks
from app.core.utils import calculate_adjustment_amounts
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
    active_campaigns = await crud.get_active_campaigns(db_session, retailer, transaction, join_rules=True)
    adjustment_amounts = calculate_adjustment_amounts(campaigns=active_campaigns, tx_amount=transaction.amount)

    active_campaign_slugs = [campaign.slug for campaign in active_campaigns]
    processed_transaction = await crud.create_processed_transaction(
        db_session, retailer, active_campaign_slugs, transaction
    )
    await crud.delete_transaction(db_session, transaction)

    is_refund: bool = processed_transaction.amount < 0

    asyncio.create_task(
        send_processed_tx_activity(
            processed_tx=processed_transaction,
            retailer=retailer,
            adjustment_amounts=adjustment_amounts,
            is_refund=is_refund,
        )
    )

    accepted_adjustments = {k: v["amount"] for k, v in adjustment_amounts.items() if v["accepted"]}
    if accepted_adjustments:
        adjustment_tasks_ids = await crud.create_reward_adjustment_tasks(
            db_session, processed_transaction, accepted_adjustments
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
