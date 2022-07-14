import logging

from cosmos_message_lib import ActivitySchema, get_connection_and_exchange, verify_payload_and_send_activity
from sqlalchemy.engine import Row
from typer import echo

from app.activity_utils.enums import ActivityType
from app.activity_utils.schemas import ProcessedTXEventSchema
from app.activity_utils.utils import build_tx_history_earns, build_tx_history_reasons, pence_integer_to_currency_string
from app.core.config import settings

logger = logging.getLogger("tx-history-migrator")
logger.setLevel(logging.ERROR)

connection, exchange = get_connection_and_exchange(
    rabbitmq_dsn=settings.RABBITMQ_URI,
    message_exchange_name=settings.MESSAGE_EXCHANGE_NAME,
)


def send_processed_tx_activity(
    processed_tx_data: Row, retailer_slug: str, adjustment_amounts: dict, debug: bool = False
) -> None:
    currency = "GBP"
    is_refund: bool = processed_tx_data.amount < 0
    store_name = processed_tx_data.store_name or "N/A"

    try:
        payload = {
            "type": ActivityType.TX_HISTORY.name,
            "datetime": processed_tx_data.created_at,
            "underlying_datetime": processed_tx_data.datetime,
            "summary": (f"{retailer_slug} Transaction Processed for {store_name}" f" (MID: {processed_tx_data.mid})"),
            "reasons": build_tx_history_reasons(processed_tx_data.amount, adjustment_amounts, is_refund, currency),
            "activity_identifier": processed_tx_data.transaction_id,
            "user_id": processed_tx_data.account_holder_uuid,
            "associated_value": pence_integer_to_currency_string(processed_tx_data.amount, currency),
            "retailer": retailer_slug,
            "campaigns": processed_tx_data.campaign_slugs,
            "data": ProcessedTXEventSchema(
                transaction_id=processed_tx_data.transaction_id,
                datetime=processed_tx_data.datetime,
                amount=pence_integer_to_currency_string(processed_tx_data.amount, currency, currency_sign=False),
                amount_currency=currency,
                store_name=store_name,
                mid=processed_tx_data.mid,
                earned=build_tx_history_earns(adjustment_amounts, currency),
            ).dict(),
        }

        if debug:
            echo(ActivitySchema(**payload).json(indent=4, ensure_ascii=False))

    except Exception:  # pylint: disable=broad-except
        logger.exception("failed to format payload for processed transaction %d", processed_tx_data.id)
        raise

    if not debug:
        verify_payload_and_send_activity(connection, exchange, payload, ActivityType.TX_HISTORY.value)
