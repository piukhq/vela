import asyncio

from typing import TYPE_CHECKING

from cosmos_message_lib import get_connection_and_exchange, verify_payload_and_send_activity

from vela.activity_utils.enums import ActivityType
from vela.activity_utils.schemas import ProcessedTXEventSchema
from vela.core.config import settings
from vela.crud import get_retailer_store_name_by_mid
from vela.db.session import AsyncSessionMaker

from . import logger
from .utils import build_tx_history_earns, build_tx_history_reasons, pence_integer_to_currency_string

if TYPE_CHECKING:
    from vela.models import ProcessedTransaction, RetailerRewards


connection, exchange = get_connection_and_exchange(
    rabbitmq_dsn=settings.RABBITMQ_URI,
    message_exchange_name=settings.MESSAGE_EXCHANGE_NAME,
)


async def send_processed_tx_activity(
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
            store_name = await get_retailer_store_name_by_mid(db_session, retailer.id, processed_tx.mid) or "N/A"
            payload = {
                "type": ActivityType.TX_HISTORY.name,
                "datetime": processed_tx.created_at,
                "underlying_datetime": processed_tx.datetime,
                "summary": f"{retailer.slug} Transaction Processed for {store_name} (MID: {processed_tx.mid})",
                "reasons": build_tx_history_reasons(processed_tx.amount, adjustment_amounts, is_refund, currency),
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
                    store_name=store_name,
                    mid=processed_tx.mid,
                    earned=build_tx_history_earns(adjustment_amounts, currency),
                ).dict(),
            }
        except Exception:  # pylint: disable=broad-except
            logger.exception("failed to format payload for processed transaction %d", processed_tx.id)
            raise

    await asyncio.to_thread(
        verify_payload_and_send_activity, connection, exchange, payload, ActivityType.TX_HISTORY.value
    )
