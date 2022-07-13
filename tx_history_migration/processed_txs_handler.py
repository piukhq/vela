from typing import TYPE_CHECKING, Any

from sqlalchemy import func
from sqlalchemy.engine import Row
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload

from app.crud.retailer import _calculate_transaction_amounts_for_each_earn_rule
from app.db.session import SyncSessionMaker as VelaSessionMaker
from app.models import ProcessedTransaction, RetailerStore
from app.models.retailer import Campaign, RetailerRewards

from .send_activity import send_processed_tx_activity

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# pylint: disable=too-many-instance-attributes
class VelaTxHistoryHandler:
    def __init__(self, retailer_slug: str, excluded_txs_ids: list[str], debug: bool = False) -> None:
        self.debug = debug
        self.retailer_slug = retailer_slug
        self.excluded_txs_ids = excluded_txs_ids
        self.current_offset = 0
        self.db_session: "Session" = VelaSessionMaker()
        self.retailer_id = self._load_retailer_id()
        self.mapped_campaigns = self._load_retailer_campaigns()

    def get_processed_tx_count(self) -> int:
        return self.db_session.scalar(
            select(func.count("1"))
            .select_from(ProcessedTransaction)
            .where(
                ProcessedTransaction.retailer_id == self.retailer_id,
                ~ProcessedTransaction.transaction_id.in_(self.excluded_txs_ids),
            )
        )

    def fetch_batch(self, batch_size: int) -> list[Row]:

        processed_txs_data = self.db_session.execute(
            select(
                ProcessedTransaction.id,
                ProcessedTransaction.transaction_id,
                ProcessedTransaction.created_at,
                ProcessedTransaction.datetime,
                ProcessedTransaction.mid,
                ProcessedTransaction.account_holder_uuid,
                ProcessedTransaction.amount,
                ProcessedTransaction.campaign_slugs,
                RetailerStore.store_name,
            )
            .select_from(ProcessedTransaction)
            .join(
                RetailerStore,
                (ProcessedTransaction.mid == RetailerStore.mid)
                & (ProcessedTransaction.retailer_id == RetailerStore.retailer_id),
                isouter=True,
            )
            .where(
                ProcessedTransaction.retailer_id == self.retailer_id,
                ~ProcessedTransaction.transaction_id.in_(self.excluded_txs_ids),
            )
            .limit(batch_size)
            .offset(self.current_offset)
        ).all()
        self.current_offset += batch_size
        return processed_txs_data

    def _load_retailer_id(self) -> int:
        return self.db_session.execute(
            select(RetailerRewards.id).where(RetailerRewards.slug == self.retailer_slug)
        ).scalar_one()

    def _load_retailer_campaigns(self) -> dict[str, Campaign]:

        return {
            campaign.slug: campaign
            for campaign in (
                self.db_session.execute(
                    select(Campaign)
                    .options(joinedload(Campaign.earn_rules), joinedload(Campaign.reward_rule))
                    .where(Campaign.retailer_id == self.retailer_id)
                )
                .unique()
                .scalars()
                .all()
            )
        }

    def _get_campaigns_for_tx(self, tx_data: Row) -> list[Campaign]:

        return [
            self.mapped_campaigns[campaign_slug]
            for campaign_slug in tx_data.campaign_slugs
            if campaign_slug in self.mapped_campaigns
        ]

    def produce_activity(self, processed_tx_data: Row) -> None:
        campaigns = self._get_campaigns_for_tx(processed_tx_data)
        adjustment_amounts = _calculate_transaction_amounts_for_each_earn_rule(campaigns, processed_tx_data.amount)
        send_processed_tx_activity(processed_tx_data, self.retailer_slug, adjustment_amounts, self.debug)

    def __enter__(self) -> "VelaTxHistoryHandler":
        return self

    def __exit__(self, *args: Any, **kargs: Any) -> None:
        try:
            self.db_session.close()
        finally:
            pass
