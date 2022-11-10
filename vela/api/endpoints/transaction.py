import asyncio

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from vela import crud
from vela.activity_utils.enums import ActivityType
from vela.activity_utils.tasks import async_send_activity
from vela.api.deps import get_session, retailer_is_valid, user_is_authorised
from vela.api.tasks import enqueue_many_tasks
from vela.core.utils import calculate_adjustment_amounts
from vela.enums import HttpErrors, TransactionProcessingStatuses
from vela.internal_requests import validate_account_holder_uuid
from vela.models import RetailerRewards
from vela.schemas import CreateTransactionSchema

router = APIRouter()


async def _get_transaction_response(accepted_adjustments: dict, is_refund: bool) -> str:
    if accepted_adjustments:
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


@router.post(
    path="/{retailer_slug}/transaction",
    response_model=str,
    dependencies=[Depends(user_is_authorised)],
)
# pylint: disable=too-many-locals
async def record_transaction(
    payload: CreateTransactionSchema,
    retailer: RetailerRewards = Depends(retailer_is_valid),
    db_session: AsyncSession = Depends(get_session),
) -> Any:
    tx_import_activity_data = {
        "retailer_slug": retailer.slug,
        "active_campaign_slugs": None,
        "refunds_valid": None,
        "error": "N/A",
    }
    adjustment_tasks_ids = []
    try:
        await validate_account_holder_uuid(payload.account_holder_uuid, retailer.slug)
        transaction_data = payload.dict(exclude_unset=True)

        # asyncpg can't translate tz aware to naive datetimes, remove this once we move to psycopg3.
        transaction_data["datetime"] = transaction_data["datetime"].replace(tzinfo=None)
        # ---------------------------------------------------------------------------------------- #
        transaction = await crud.create_transaction(db_session, retailer, transaction_data)  # nested commit
        active_campaigns = await crud.get_active_campaigns(db_session, retailer, transaction, join_rules=True)
        adjustment_amounts = calculate_adjustment_amounts(campaigns=active_campaigns, tx_amount=transaction.amount)
        accepted_adjustments = {k: v["amount"] for k, v in adjustment_amounts.items() if v["accepted"]}
        active_campaign_slugs = [campaign.slug for campaign in active_campaigns]

        processed_transaction = await crud.create_processed_transaction(  # nested commit
            db_session, retailer, active_campaign_slugs, transaction
        )
        is_refund: bool = processed_transaction.amount < 0
        tx_import_activity_data.update(
            {
                "active_campaign_slugs": active_campaign_slugs,
                "refunds_valid": bool(accepted_adjustments or not is_refund),
            }
        )

        await crud.delete_transaction(db_session, transaction)
        store_name = (
            await crud.get_retailer_store_name_by_mid(db_session, retailer.id, processed_transaction.mid) or "N/A"
        )

        tx_history_activity_payload = ActivityType.get_processed_tx_activity_data(
            processed_tx=processed_transaction,
            retailer=retailer,
            adjustment_amounts=adjustment_amounts,
            is_refund=is_refund,
            store_name=store_name,
        )
        asyncio.create_task(async_send_activity(tx_history_activity_payload, routing_key=ActivityType.TX_HISTORY.value))

        if accepted_adjustments:
            task_ids = await crud.create_reward_adjustment_tasks(
                db_session, processed_transaction, accepted_adjustments
            )
            adjustment_tasks_ids.extend(task_ids)

        response_content = await _get_transaction_response(accepted_adjustments, is_refund)

        return response_content

    except HTTPException as ex:
        tx_import_activity_data.update({"error": ex.detail["code"]})  # type: ignore [index]
        if ex == HttpErrors.NO_ACTIVE_CAMPAIGNS.value:
            transaction.status = TransactionProcessingStatuses.NO_ACTIVE_CAMPAIGNS
        raise

    finally:
        await db_session.commit()  # main db commit

        if adjustment_tasks_ids:
            asyncio.create_task(enqueue_many_tasks(retry_tasks_ids=adjustment_tasks_ids))  # main db commit + rollback

        tx_import_activity_payload = ActivityType.get_tx_import_activity_data(
            transaction=payload.dict(exclude_unset=True),
            data=tx_import_activity_data,
        )
        asyncio.create_task(async_send_activity(tx_import_activity_payload, routing_key=ActivityType.TX_IMPORT.value))
