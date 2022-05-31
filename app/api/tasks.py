import asyncio
import logging

from typing import TYPE_CHECKING

from babel.numbers import format_currency
from cosmos_message_lib import ActivityType, get_connection_and_exchange, verify_payload_and_send_activity
from retry_tasks_lib.utils.asynchronous import enqueue_many_retry_tasks

from app.core.config import redis_raw, settings
from app.crud import get_retailer_store_name_by_mid
from app.db.session import AsyncSessionMaker
from app.enums import LoyaltyTypes
from app.schemas.activities import ProcessedTXEventSchema

if TYPE_CHECKING:
    from app.models import ProcessedTransaction, RetailerRewards


logger = logging.getLogger(__name__)
connection, exchange = get_connection_and_exchange(
    rabbitmq_uri=settings.RABBITMQ_URI,
    message_exchange_name=settings.MESSAGE_EXCHANGE_NAME,
)


async def enqueue_many_tasks(retry_tasks_ids: list[int]) -> None:  # pragma: no cover
    async with AsyncSessionMaker() as db_session:
        await enqueue_many_retry_tasks(
            db_session=db_session,
            retry_tasks_ids=retry_tasks_ids,
            connection=redis_raw,
        )


def _build_reasons(tx_amount: int, adjustments: dict, is_refund: bool, currency: str) -> list[str]:
    reasons = []
    for v in adjustments.values():

        amount = pence_integer_to_currency_string(tx_amount, currency)
        threshold = pence_integer_to_currency_string(v["threshold"], currency)

        if v["accepted"]:
            if is_refund:
                reasons.append(f"refund of {amount} accepted")
            else:
                reasons.append(f"transaction amount {amount} meets the required threshold {threshold}")
        else:
            if is_refund:
                reasons.append(f"refund of {amount} not accepted")
            else:
                reasons.append(f"transaction amount {amount} does no meet the required threshold {threshold}")

    return reasons


def _build_earns(adjustments: dict, currency: str) -> list[dict[str, str]]:
    earns = []
    for v in adjustments.values():
        if v["type"] == LoyaltyTypes.ACCUMULATOR:
            amount = pence_integer_to_currency_string(v["amount"], currency)
        else:
            amount = str(v["amount"])

        earns.append({"value": amount, "type": v["type"]})

    return earns


def pence_integer_to_currency_string(value: int, currency: str, currency_sign: bool = True) -> str:
    extras: dict = {}
    if not currency_sign:
        extras = {"format": "#,##0.##"}

    return format_currency(abs(value) / 100, currency, locale="en_GB", **extras)


async def send_processed_tx_event(
    *,
    processed_tx: "ProcessedTransaction",
    retailer: "RetailerRewards",
    adjustment_amounts: dict,
    is_refund: bool,
    currency: str = "GBP",
) -> None:

    # NOTE: retailer and processed_tx are not bound to this db_session
    # so we can't use the relationships on those objects
    # ie: retailer.stores and processed_tx.retailer
    async with AsyncSessionMaker() as db_session:
        try:
            payload = {
                "type": ActivityType.TRANSACTION_HISTORY,
                "datetime": processed_tx.created_at,
                "underlying_datetime": processed_tx.datetime,
                "summary": f"{retailer.slug} transaction processed",
                "reasons": _build_reasons(processed_tx.amount, adjustment_amounts, is_refund, currency),
                "activity_identifier": processed_tx.transaction_id,
                "user_id": processed_tx.account_holder_uuid,
                "associated_value": pence_integer_to_currency_string(processed_tx.amount, currency),
                "retailer": retailer.slug,
                "campaigns": processed_tx.campaign_slugs,
                "data": ProcessedTXEventSchema(
                    transaction_id=processed_tx.transaction_id,
                    datetime=processed_tx.datetime,
                    amount=pence_integer_to_currency_string(processed_tx.amount, currency, currency_sign=False),
                    amount_currency=currency,
                    store_name=await get_retailer_store_name_by_mid(db_session, retailer.id, processed_tx.mid) or "N/A",
                    mid=processed_tx.mid,
                    earned=_build_earns(adjustment_amounts, currency),
                ).dict(),
            }
        except Exception:  # pylint: disable=broad-except
            logger.exception("failed to format payload for processed transaction %d", processed_tx.id)

    await asyncio.to_thread(
        verify_payload_and_send_activity, connection, exchange, payload, settings.TRANSACTION_ROUTING_KEY
    )
