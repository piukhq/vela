from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from vela.activity_utils.schemas import ProcessedTXEventSchema, TxImportEventSchema
from vela.core.config import settings
from vela.enums import HttpErrors

from .utils import build_tx_history_earns, build_tx_history_reasons, pence_integer_to_currency_string

if TYPE_CHECKING:
    from vela.models import ProcessedTransaction, RetailerRewards


class TxImportReasons(Enum):
    REFUNDS_NOT_SUPPORTED = "Refunds not supported"
    USER_NOT_ACTIVE = "No active user"
    NO_ACTIVE_CAMPAIGNS = "No active campaigns"
    NO_ACTIVE_USER = "No active user"
    DUPLICATE_TRANSACTION = "Transaction ID not unique"
    VALID_TRANSACTION = ""


class ActivityType(Enum):
    TX_HISTORY = f"activity.{settings.PROJECT_NAME}.tx.processed"
    TX_IMPORT = f"activity.{settings.PROJECT_NAME}.tx.import"

    @classmethod
    def _get_http_error_reason(cls, error: str) -> Any:
        match error:
            case HttpErrors.USER_NOT_ACTIVE.name:
                reason = TxImportReasons.USER_NOT_ACTIVE.value
            case HttpErrors.NO_ACTIVE_CAMPAIGNS.name:
                reason = TxImportReasons.NO_ACTIVE_CAMPAIGNS.value
            case HttpErrors.USER_NOT_ACTIVE.name | HttpErrors.USER_NOT_FOUND.name:
                reason = TxImportReasons.NO_ACTIVE_USER.value
            case HttpErrors.DUPLICATE_TRANSACTION.name:
                reason = TxImportReasons.DUPLICATE_TRANSACTION.value
        return reason

    @classmethod
    def _assemble_payload(
        cls,
        activity_type: "ActivityType",
        *,
        underlying_datetime: datetime,
        activity_datetime: datetime = datetime.now(tz=timezone.utc),
        summary: str,
        associated_value: str,
        retailer_slug: str,
        data: dict,
        activity_identifier: str | None = "N/A",
        reasons: list[str] | None = None,
        campaigns: list[str] | None = None,
        user_id: UUID | str | None = None,
    ) -> dict:

        activity_identifier = activity_identifier if activity_identifier else "N/A"
        campaigns = campaigns if campaigns else []
        reasons = reasons if reasons else []
        payload = {
            "type": activity_type.name,
            "datetime": activity_datetime,
            "underlying_datetime": underlying_datetime,
            "summary": summary,
            "reasons": reasons,
            "activity_identifier": activity_identifier,
            "user_identifier": user_id,
            "associated_value": associated_value,
            "retailer": retailer_slug,
            "campaigns": campaigns,
            "data": data,
        }
        return payload

    @classmethod
    def get_tx_import_activity_data(
        cls,
        *,
        transaction: dict,
        data: dict,
        currency: str = "GBP",
    ) -> dict:
        if data["error"] != "N/A":
            reason = cls._get_http_error_reason(error=data["error"])
            summary = f"{data['retailer_slug']} Transaction Import Failed"
        elif not data["refunds_valid"]:
            reason = TxImportReasons.REFUNDS_NOT_SUPPORTED.value
            summary = f"{data['retailer_slug']} Transaction Import Failed"
        else:
            reason = TxImportReasons.VALID_TRANSACTION.value
            summary = f"{data['retailer_slug']} Transaction Imported"
        return cls._assemble_payload(
            ActivityType.TX_IMPORT,
            underlying_datetime=transaction["datetime"],
            activity_datetime=datetime.now(tz=timezone.utc),
            summary=summary,
            reasons=list(reason),
            activity_identifier=transaction["transaction_id"],
            user_id=transaction["account_holder_uuid"],
            associated_value=pence_integer_to_currency_string(transaction["amount"], currency),
            retailer_slug=data["retailer_slug"],
            campaigns=data["active_campaign_slugs"],
            data=TxImportEventSchema(
                transaction_id=transaction["transaction_id"],
                datetime=transaction["datetime"],
                amount=pence_integer_to_currency_string(transaction["amount"], currency, currency_sign=False),
                mid=transaction["mid"],
            ).dict(),
        )

    @classmethod
    def get_processed_tx_activity_data(
        cls,
        *,
        processed_tx: "ProcessedTransaction",
        retailer: "RetailerRewards",
        adjustment_amounts: dict,
        is_refund: bool,
        store_name: str,
        currency: str = "GBP",
    ) -> dict:
        # NOTE: retailer and processed_tx are not bound to this db_session
        # so we can't use the relationships on those objects
        # ie: retailer.stores and processed_tx.retailer
        return cls._assemble_payload(
            ActivityType.TX_HISTORY,
            underlying_datetime=processed_tx.datetime,
            activity_datetime=datetime.now(tz=timezone.utc),
            summary=f"{retailer.slug} Transaction Processed for {store_name} (MID: {processed_tx.mid})",
            reasons=build_tx_history_reasons(processed_tx.amount, adjustment_amounts, is_refund, currency),
            activity_identifier=processed_tx.transaction_id,
            user_id=processed_tx.account_holder_uuid,
            associated_value=pence_integer_to_currency_string(processed_tx.amount, currency),
            retailer_slug=retailer.slug,
            campaigns=processed_tx.campaign_slugs,
            data=ProcessedTXEventSchema(
                transaction_id=processed_tx.transaction_id,
                datetime=processed_tx.datetime,
                amount=pence_integer_to_currency_string(processed_tx.amount, currency, currency_sign=False),
                amount_currency=currency,
                store_name=store_name,
                mid=processed_tx.mid,
                earned=build_tx_history_earns(adjustment_amounts, currency),
            ).dict(),
        )
