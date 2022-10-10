from datetime import datetime, timezone
from uuid import uuid4

import pytest

from pytest_mock import MockerFixture

from tests.conftest import SetupType
from vela.activity_utils.enums import ActivityType
from vela.enums import LoyaltyTypes
from vela.models import ProcessedTransaction, RetailerStore


@pytest.mark.asyncio
async def test_tx_history_activity_payload(
    setup: SetupType, retailer_store: RetailerStore, mocker: MockerFixture
) -> None:
    db_session, retailer, campaign = setup
    mock_datetime = mocker.patch("vela.activity_utils.enums.datetime")
    fake_now = datetime.now(tz=timezone.utc)
    mock_datetime.now.return_value = fake_now
    processed_transaction = ProcessedTransaction(
        transaction_id="TSTTXID1234",
        amount=1500,
        mid=retailer_store.mid,
        datetime=datetime.now(tz=timezone.utc),
        account_holder_uuid=uuid4(),
        payment_transaction_id="RNDID1234",
        retailer_id=retailer.id,
        campaign_slugs=[campaign.slug],
    )
    db_session.add(processed_transaction)
    db_session.commit()

    expected_payload = {
        "type": ActivityType.TX_HISTORY.name,
        "datetime": fake_now,
        "underlying_datetime": processed_transaction.datetime,
        "summary": f"{retailer.slug} Transaction Processed for {retailer_store.store_name} "
        f"(MID: {processed_transaction.mid})",
        "reasons": [
            "transaction amount £15.00 meets the required threshold £0.00",
        ],
        "activity_identifier": processed_transaction.transaction_id,
        "user_id": processed_transaction.account_holder_uuid,
        "associated_value": "£15.00",
        "retailer": retailer.slug,
        "campaigns": processed_transaction.campaign_slugs,
        "data": {
            "transaction_id": processed_transaction.transaction_id,
            "datetime": processed_transaction.datetime,
            "amount": "15.00",
            "amount_currency": "GBP",
            "store_name": retailer_store.store_name,
            "mid": processed_transaction.mid,
            "earned": [
                {
                    "type": "ACCUMULATOR",
                    "value": "£15.00",
                },
            ],
        },
    }
    actual_payload = ActivityType.get_processed_tx_activity_data(
        processed_tx=processed_transaction,
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
        store_name=retailer_store.store_name,
    )
    assert actual_payload == expected_payload


@pytest.mark.asyncio
async def test_tx_import_activity_payload(
    setup: SetupType, retailer_store: RetailerStore, mocker: MockerFixture
) -> None:
    db_session, retailer, campaign = setup
    mock_datetime = mocker.patch("vela.activity_utils.enums.datetime")
    fake_now = datetime.now(tz=timezone.utc)
    mock_datetime.now.return_value = fake_now
    processed_transaction = ProcessedTransaction(
        transaction_id="TSTTXID1234",
        amount=1500,
        mid=retailer_store.mid,
        datetime=datetime.now(tz=timezone.utc),
        account_holder_uuid=uuid4(),
        payment_transaction_id="RNDID1234",
        retailer_id=retailer.id,
        campaign_slugs=[campaign.slug],
    )
    db_session.add(processed_transaction)
    db_session.commit()

    expected_payload = {
        "type": ActivityType.TX_IMPORT.name,
        "datetime": fake_now,
        "underlying_datetime": processed_transaction.datetime,
        "summary": f"{retailer.slug} Transaction Imported",
        "reasons": [],
        "activity_identifier": processed_transaction.transaction_id,
        "user_id": processed_transaction.account_holder_uuid,
        "associated_value": "£15.00",
        "retailer": retailer.slug,
        "campaigns": processed_transaction.campaign_slugs,
        "data": {
            "transaction_id": processed_transaction.transaction_id,
            "datetime": processed_transaction.datetime,
            "amount": "15.00",
            "mid": processed_transaction.mid,
        },
    }
    tx_import_activity_data = {
        "retailer_slug": retailer.slug,
        "active_campaign_slugs": processed_transaction.campaign_slugs,
        "refunds_valid": True,
        "error": "N/A",
    }
    transaction_data = {
        "transaction_id": processed_transaction.transaction_id,
        "payment_transaction_id": processed_transaction.payment_transaction_id,
        "amount": processed_transaction.amount,
        "datetime": processed_transaction.datetime,
        "mid": processed_transaction.mid,
        "account_holder_uuid": processed_transaction.account_holder_uuid,
    }
    actual_payload = ActivityType.get_tx_import_activity_data(
        transaction=transaction_data,
        data=tx_import_activity_data,
    )
    assert actual_payload == expected_payload
