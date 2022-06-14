from datetime import datetime, timezone
from uuid import uuid4

import pytest

from cosmos_message_lib import ActivityType
from deepdiff import DeepDiff
from pytest_mock import MockerFixture

from app.api.tasks import send_processed_tx_event
from app.enums import LoyaltyTypes
from app.models import ProcessedTransaction, RetailerStore
from tests.conftest import SetupType


@pytest.mark.asyncio
async def test_send_processed_tx_event(setup: SetupType, retailer_store: RetailerStore, mocker: MockerFixture) -> None:
    db_session, retailer, campaign = setup
    ptx = ProcessedTransaction(
        transaction_id="TSTTXID1234",
        amount=1500,
        mid=retailer_store.mid,
        datetime=datetime.now(tz=timezone.utc),
        account_holder_uuid=uuid4(),
        payment_transaction_id="RNDID1234",
        retailer_id=retailer.id,
        campaign_slugs=[campaign.slug],
    )
    db_session.add(ptx)
    db_session.commit()

    mock_to_thread = mocker.patch("asyncio.to_thread")

    expected_payload = {
        "type": ActivityType.TRANSACTION_HISTORY,
        "datetime": ptx.created_at,
        "underlying_datetime": ptx.datetime,
        "summary": f"{retailer.slug} Transaction Processed for {retailer_store.store_name} (MID: {ptx.mid})",
        "reasons": [
            "transaction amount £15.00 meets the required threshold £0.00",
        ],
        "activity_identifier": ptx.transaction_id,
        "user_id": ptx.account_holder_uuid,
        "associated_value": "£15.00",
        "retailer": retailer.slug,
        "campaigns": ptx.campaign_slugs,
        "data": {
            "transaction_id": ptx.transaction_id,
            "datetime": ptx.datetime,
            "amount": "15.00",
            "amount_currency": "GBP",
            "store_name": retailer_store.store_name,
            "mid": ptx.mid,
            "earned": [
                {
                    "type": "ACCUMULATOR",
                    "value": "£15.00",
                },
            ],
        },
    }
    await send_processed_tx_event(
        processed_tx=ptx,
        retailer=retailer,
        adjustment_amounts={
            campaign.slug: {
                "threshold": 0,
                "type": LoyaltyTypes.ACCUMULATOR,
                "amount": 1500,
                "accepted": True,
            }
        },
        is_refund=False,
    )
    assert not DeepDiff(mock_to_thread.call_args.args[3], expected_payload)
