# pylint: disable=too-many-arguments, too-many-locals

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Callable
from unittest.mock import MagicMock, call
from uuid import uuid4

import pytest

from fastapi import status
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture
from requests import Response
from sqlalchemy import func, select

from asgi import app
from tests.conftest import SetupType
from vela.activity_utils.enums import ActivityType
from vela.core.config import settings
from vela.enums import CampaignStatuses, LoyaltyTypes, TransactionProcessingStatuses
from vela.models import EarnRule, ProcessedTransaction, RetailerRewards, Transaction
from vela.models.retailer import RewardRule

if TYPE_CHECKING:
    from retry_tasks_lib.db.models import TaskType
    from sqlalchemy.orm import Session

client = TestClient(app, raise_server_exceptions=False)
auth_headers = {"Authorization": f"Token {settings.VELA_API_AUTH_TOKEN}"}

account_holder_uuid = uuid4()
datetime_now = datetime.now(tz=timezone.utc)
timestamp_now = int(datetime_now.timestamp())


@pytest.fixture(scope="function")
def payload() -> dict:
    return {
        "id": "69364ce3-21a4-4442-8608-e878eeb8b6e6",
        "transaction_id": "BPL123456789",
        "transaction_total": 1125,
        "datetime": str(timestamp_now),
        "MID": "12345678",
        "loyalty_id": str(account_holder_uuid),
    }


def test_post_transaction_happy_path(
    setup: SetupType,
    payload: dict,
    earn_rule: EarnRule,
    mocker: MockerFixture,
    reward_adjustment_task_type: "TaskType",
    create_mock_reward_rule: Callable,
    reward_status_adjustment_task_type: "TaskType",
) -> None:
    db_session, retailer, campaign = setup

    mocker.patch(
        "vela.internal_requests.send_async_request_with_retry", return_value=(status.HTTP_200_OK, {"status": "active"})
    )
    mocker.patch("retry_tasks_lib.utils.asynchronous.enqueue_many_retry_tasks")
    mock_get_tx_import_activity_data = mocker.patch(
        "vela.activity_utils.enums.ActivityType.get_tx_import_activity_data",
        return_value={"mock": "payload"},
    )
    mock_get_processed_tx_activity_data = mocker.patch(
        "vela.activity_utils.enums.ActivityType.get_processed_tx_activity_data",
        return_value={"mock": "payload"},
    )
    mock_async_send_activity = mocker.patch("vela.api.endpoints.transaction.async_send_activity")
    create_mock_reward_rule(reward_slug="negative-test-reward", campaign_id=campaign.id, reward_goal=10)

    resp = client.post(f"{settings.API_PREFIX}/{retailer.slug}/transaction", json=payload, headers=auth_headers)
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json() == "Awarded"
    processed_transaction = (
        db_session.query(ProcessedTransaction).filter_by(transaction_id=payload["id"], retailer_id=retailer.id).first()
    )
    assert processed_transaction is not None
    assert processed_transaction.mid == payload["MID"]
    assert processed_transaction.amount == payload["transaction_total"]
    assert processed_transaction.transaction_id == payload["id"]
    assert processed_transaction.payment_transaction_id == payload["transaction_id"]
    assert processed_transaction.datetime == datetime.fromtimestamp(timestamp_now, tz=timezone.utc).replace(tzinfo=None)
    assert processed_transaction.account_holder_uuid == account_holder_uuid
    processed_datetime = datetime.fromtimestamp(float(payload["datetime"]), tz=timezone.utc)
    transaction_data = {
        "transaction_id": payload["id"],
        "payment_transaction_id": "BPL123456789",
        "amount": 1125,
        "datetime": processed_datetime,
        "mid": "12345678",
        "account_holder_uuid": account_holder_uuid,
    }
    tx_import_activity_data = {
        "retailer_slug": retailer.slug,
        "active_campaign_slugs": [f"{campaign.slug}"],
        "refunds_valid": True,
        "error": "N/A",
    }
    mock_get_tx_import_activity_data.assert_called_once_with(
        transaction=transaction_data,
        data=tx_import_activity_data,
    )
    mock_get_processed_tx_activity_data.assert_called_once()
    expected_calls = [  # The expected call stack for send_activity, in order
        call().send({"mock": "payload"}, routing_key=ActivityType.TX_HISTORY.value),
        call().send({"mock": "payload"}, routing_key=ActivityType.TX_IMPORT.value),
    ]
    mock_async_send_activity.assert_has_calls(expected_calls)


def test_post_transaction_not_awarded(
    setup: SetupType, payload: dict, earn_rule: EarnRule, reward_rule: RewardRule, mocker: MockerFixture
) -> None:
    db_session, retailer, _ = setup

    mocker.patch(
        "vela.internal_requests.send_async_request_with_retry", return_value=(status.HTTP_200_OK, {"status": "active"})
    )

    payload["transaction_total"] = 250
    resp = client.post(f"{settings.API_PREFIX}/{retailer.slug}/transaction", json=payload, headers=auth_headers)

    assert resp.status_code == status.HTTP_200_OK
    assert resp.json() == "Threshold not met"

    processed_transaction = (
        db_session.query(ProcessedTransaction).filter_by(transaction_id=payload["id"], retailer_id=retailer.id).first()
    )

    assert processed_transaction is not None
    assert processed_transaction.mid == payload["MID"]
    assert processed_transaction.amount == payload["transaction_total"]
    assert processed_transaction.transaction_id == payload["id"]
    assert processed_transaction.payment_transaction_id == payload["transaction_id"]
    assert processed_transaction.datetime == datetime.fromtimestamp(timestamp_now, tz=timezone.utc).replace(tzinfo=None)
    assert processed_transaction.account_holder_uuid == account_holder_uuid


def test_post_transaction_no_active_campaigns(
    setup: SetupType, payload: dict, earn_rule: EarnRule, mocker: MockerFixture
) -> None:
    db_session, retailer, campaign = setup

    campaign.status = CampaignStatuses.DRAFT
    db_session.commit()

    mocker.patch(
        "vela.internal_requests.send_async_request_with_retry", return_value=(status.HTTP_200_OK, {"status": "active"})
    )
    mock_get_tx_import_activity_data = mocker.patch(
        "vela.activity_utils.enums.ActivityType.get_tx_import_activity_data",
        return_value={"mock": "payload"},
    )
    mock_async_send_activity = mocker.patch("vela.api.endpoints.transaction.async_send_activity")

    resp = client.post(f"{settings.API_PREFIX}/{retailer.slug}/transaction", json=payload, headers=auth_headers)

    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert resp.json() == {"display_message": "No active campaigns found for retailer.", "code": "NO_ACTIVE_CAMPAIGNS"}

    transaction = db_session.query(Transaction).filter_by(transaction_id=payload["id"], retailer_id=retailer.id).first()

    assert transaction is not None
    assert transaction.mid == payload["MID"]
    assert transaction.amount == payload["transaction_total"]
    assert transaction.datetime == datetime.fromtimestamp(timestamp_now, tz=timezone.utc).replace(tzinfo=None)
    assert transaction.account_holder_uuid == account_holder_uuid
    processed_datetime = datetime.fromtimestamp(float(payload["datetime"]), tz=timezone.utc)
    transaction_data = {
        "transaction_id": payload["id"],
        "payment_transaction_id": "BPL123456789",
        "amount": 1125,
        "datetime": processed_datetime,
        "mid": "12345678",
        "account_holder_uuid": account_holder_uuid,
    }
    tx_import_activity_data = {
        "retailer_slug": retailer.slug,
        "active_campaign_slugs": None,
        "refunds_valid": None,
        "error": "NO_ACTIVE_CAMPAIGNS",
    }
    mock_get_tx_import_activity_data.assert_called_once_with(
        transaction=transaction_data,
        data=tx_import_activity_data,
    )
    mock_async_send_activity.assert_called_once_with({"mock": "payload"}, routing_key=ActivityType.TX_IMPORT.value)


def test_post_transaction_no_active_campaigns_pre_start_date(
    setup: SetupType, payload: dict, earn_rule: EarnRule, mocker: MockerFixture
) -> None:
    db_session, retailer, campaign = setup
    transaction_timestamp = int((campaign.start_date.replace(tzinfo=timezone.utc) - timedelta(minutes=5)).timestamp())
    payload["datetime"] = transaction_timestamp

    mocker.patch(
        "vela.internal_requests.send_async_request_with_retry", return_value=(status.HTTP_200_OK, {"status": "active"})
    )

    resp = client.post(f"{settings.API_PREFIX}/{retailer.slug}/transaction", json=payload, headers=auth_headers)

    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert resp.json() == {"display_message": "No active campaigns found for retailer.", "code": "NO_ACTIVE_CAMPAIGNS"}

    transaction = db_session.query(Transaction).filter_by(transaction_id=payload["id"], retailer_id=retailer.id).first()

    assert transaction is not None
    assert transaction.mid == payload["MID"]
    assert transaction.amount == payload["transaction_total"]
    assert transaction.datetime == datetime.fromtimestamp(transaction_timestamp, tz=timezone.utc).replace(tzinfo=None)
    assert transaction.account_holder_uuid == account_holder_uuid


def test_post_transaction_no_active_campaigns_post_end_date(
    setup: SetupType, payload: dict, earn_rule: EarnRule, mocker: MockerFixture
) -> None:
    db_session, retailer, campaign = setup
    campaign.end_date = datetime_now - timedelta(minutes=1)
    db_session.commit()

    mocker.patch(
        "vela.internal_requests.send_async_request_with_retry", return_value=(status.HTTP_200_OK, {"status": "active"})
    )

    resp = client.post(f"{settings.API_PREFIX}/{retailer.slug}/transaction", json=payload, headers=auth_headers)

    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert resp.json() == {"display_message": "No active campaigns found for retailer.", "code": "NO_ACTIVE_CAMPAIGNS"}

    transaction = db_session.query(Transaction).filter_by(transaction_id=payload["id"], retailer_id=retailer.id).first()

    assert transaction is not None
    assert transaction.mid == payload["MID"]
    assert transaction.amount == payload["transaction_total"]
    assert transaction.datetime == datetime.fromtimestamp(timestamp_now, tz=timezone.utc).replace(tzinfo=None)
    assert transaction.account_holder_uuid == account_holder_uuid
    assert transaction.status == TransactionProcessingStatuses.NO_ACTIVE_CAMPAIGNS


def test_post_transaction_existing_transaction(
    setup: SetupType,
    earn_rule: EarnRule,
    reward_adjustment_task_type: "TaskType",
    create_mock_reward_rule: Callable,
    reward_status_adjustment_task_type: "TaskType",
    payload: dict,
    mocker: MockerFixture,
) -> None:
    retailer_slug = setup.retailer.slug
    campaign = setup.campaign
    db_session = setup.db_session

    mocker.patch(
        "vela.internal_requests.send_async_request_with_retry", return_value=(status.HTTP_200_OK, {"status": "active"})
    )
    mock_get_tx_import_activity_data = mocker.patch(
        "vela.activity_utils.enums.ActivityType.get_tx_import_activity_data",
        return_value={"mock": "payload"},
    )
    mock_get_processed_tx_activity_data = mocker.patch(
        "vela.activity_utils.enums.ActivityType.get_processed_tx_activity_data",
        return_value={"mock": "payload"},
    )
    mock_async_send_activity = mocker.patch("vela.api.endpoints.transaction.async_send_activity")
    create_mock_reward_rule(reward_slug="negative-test-reward", campaign_id=campaign.id, reward_goal=10)

    resp = client.post(f"{settings.API_PREFIX}/{retailer_slug}/transaction", json=payload, headers=auth_headers)

    assert resp.status_code == status.HTTP_200_OK
    assert db_session.execute(select(func.count()).select_from(Transaction)).scalar() == 0
    assert db_session.execute(select(func.count()).select_from(ProcessedTransaction)).scalar() == 1

    resp = client.post(f"{settings.API_PREFIX}/{retailer_slug}/transaction", json=payload, headers=auth_headers)

    assert resp.status_code == status.HTTP_409_CONFLICT
    assert db_session.execute(select(func.count()).select_from(Transaction)).scalar() == 1
    transaction = db_session.execute(select(Transaction)).scalar_one()
    assert transaction.status == TransactionProcessingStatuses.DUPLICATE
    assert db_session.execute(select(func.count()).select_from(ProcessedTransaction)).scalar() == 1
    assert resp.json() == {"display_message": "Duplicate Transaction.", "code": "DUPLICATE_TRANSACTION"}
    processed_datetime = datetime.fromtimestamp(float(payload["datetime"]), tz=timezone.utc)
    transaction_data = {
        "transaction_id": payload["id"],
        "payment_transaction_id": "BPL123456789",
        "amount": 1125,
        "datetime": processed_datetime,
        "mid": "12345678",
        "account_holder_uuid": account_holder_uuid,
    }
    tx_import_activity_data = {
        "retailer_slug": retailer_slug,
        "active_campaign_slugs": None,
        "refunds_valid": None,
        "error": "DUPLICATE_TRANSACTION",
    }
    mock_get_tx_import_activity_data.assert_called_with(
        transaction=transaction_data,
        data=tx_import_activity_data,
    )
    mock_get_processed_tx_activity_data.assert_called_once()
    expected_calls = [  # The expected call stack for send_activity, in order
        call().send({"mock": "payload"}, routing_key=ActivityType.TX_HISTORY.value),
        call().send({"mock": "payload"}, routing_key=ActivityType.TX_IMPORT.value),
        call().send({"mock": "payload"}, routing_key=ActivityType.TX_IMPORT.value),
    ]
    mock_async_send_activity.assert_has_calls(expected_calls)


def test_post_transaction_wrong_retailer(payload: dict) -> None:
    resp = client.post(f"{settings.API_PREFIX}/NOT_A_RETIALER/transaction", json=payload, headers=auth_headers)
    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert resp.json() == {"display_message": "Requested retailer is invalid.", "code": "INVALID_RETAILER"}


def test_post_transaction_account_holder_validation_errors(
    setup: SetupType,
    earn_rule: EarnRule,
    reward_adjustment_task_type: "TaskType",
    create_mock_reward_rule: Callable,
    reward_status_adjustment_task_type: "TaskType",
    payload: dict,
    mocker: MockerFixture,
) -> None:
    retailer_slug = setup.retailer.slug
    campaign = setup.campaign
    processed_datetime = datetime.fromtimestamp(float(payload["datetime"]), tz=timezone.utc)
    transaction_data = {
        "transaction_id": payload["id"],
        "payment_transaction_id": "BPL123456789",
        "amount": 1125,
        "datetime": processed_datetime,
        "mid": "12345678",
        "account_holder_uuid": account_holder_uuid,
    }

    mock_get_tx_import_activity_data = mocker.patch(
        "vela.activity_utils.enums.ActivityType.get_tx_import_activity_data",
        return_value={"mock": "payload"},
    )
    mock_get_processed_tx_activity_data = mocker.patch(
        "vela.activity_utils.enums.ActivityType.get_processed_tx_activity_data",
        return_value={"mock": "payload"},
    )
    mock_async_send_activity = mocker.patch("vela.api.endpoints.transaction.async_send_activity")
    create_mock_reward_rule(reward_slug="negative-test-reward", campaign_id=campaign.id, reward_goal=10)

    mocked_session = mocker.patch("vela.internal_requests.send_async_request_with_retry")
    mocked_session.return_value = (status.HTTP_200_OK, {"status": "pending"})

    resp = client.post(f"{settings.API_PREFIX}/{retailer_slug}/transaction", json=payload, headers=auth_headers)

    assert resp.status_code == status.HTTP_409_CONFLICT
    assert resp.json() == {"display_message": "User Account not Active", "code": "USER_NOT_ACTIVE"}
    tx_import_activity_data_not_active = {
        "retailer_slug": retailer_slug,
        "active_campaign_slugs": None,
        "refunds_valid": None,
        "error": "USER_NOT_ACTIVE",
    }
    mock_get_tx_import_activity_data.assert_called_with(
        transaction=transaction_data, data=tx_import_activity_data_not_active
    )

    mocked_session.return_value = (status.HTTP_404_NOT_FOUND, {})

    resp = client.post(f"{settings.API_PREFIX}/{retailer_slug}/transaction", json=payload, headers=auth_headers)

    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert resp.json() == {"display_message": "Unknown User.", "code": "USER_NOT_FOUND"}
    tx_import_activity_data_not_found = {
        "retailer_slug": retailer_slug,
        "active_campaign_slugs": None,
        "refunds_valid": None,
        "error": "USER_NOT_FOUND",
    }
    mock_get_tx_import_activity_data.assert_called_with(
        transaction=transaction_data, data=tx_import_activity_data_not_found
    )

    mocked_session.return_value = (status.HTTP_500_INTERNAL_SERVER_ERROR, {})

    resp = client.post(f"{settings.API_PREFIX}/{retailer_slug}/transaction", json=payload, headers=auth_headers)

    assert resp.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert resp.json() == {
        "display_message": "An unexpected system error occurred, please try again later.",
        "code": "INTERNAL_ERROR",
    }
    tx_import_activity_data_client_error = {
        "retailer_slug": retailer_slug,
        "active_campaign_slugs": None,
        "refunds_valid": None,
        "error": "INTERNAL_ERROR",
    }
    mock_get_tx_import_activity_data.assert_called_with(
        transaction=transaction_data,
        data=tx_import_activity_data_client_error,
    )

    mock_get_processed_tx_activity_data.assert_not_called()

    expected_calls = [  # The expected call stack for send_activity, in order
        call().send({"mock": "payload"}, routing_key=ActivityType.TX_IMPORT.value),
        call().send({"mock": "payload"}, routing_key=ActivityType.TX_IMPORT.value),
        call().send({"mock": "payload"}, routing_key=ActivityType.TX_IMPORT.value),
    ]
    mock_async_send_activity.assert_has_calls(expected_calls)


def test_post_transaction_account_holder_empty_val_validation_errors(
    setup: SetupType, payload: dict, mocker: MockerFixture
) -> None:
    def _check_transaction_endpoint_422_response(field_name: str, retailer_slug: str, bad_payload: dict) -> None:
        resp = client.post(f"{settings.API_PREFIX}/{retailer_slug}/transaction", json=bad_payload, headers=auth_headers)
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert resp.json() == {
            "display_message": "Submitted fields are missing or invalid.",
            "code": "FIELD_VALIDATION_ERROR",
            "fields": [field_name],
        }

    retailer_slug = setup.retailer.slug
    mocked_session = mocker.patch("vela.internal_requests.send_async_request_with_retry")
    mocked_session.return_value = MagicMock(
        spec=Response, json=lambda: {"status": "pending"}, status_code=status.HTTP_200_OK
    )

    for field_name in ["id", "transaction_id", "datetime", "MID", "loyalty_id"]:
        bad_payload = deepcopy(payload)
        bad_payload[field_name] = ""
        _check_transaction_endpoint_422_response(field_name, retailer_slug, bad_payload)

        bad_payload[field_name] = "  "
        _check_transaction_endpoint_422_response(field_name, retailer_slug, bad_payload)


def test_post_transaction_negative_amount(
    db_session: "Session",
    retailer: RetailerRewards,
    payload: dict,
    mocker: MockerFixture,
    reward_adjustment_task_type: "TaskType",
    create_mock_campaign: Callable,
    create_mock_earn_rule: Callable,
    create_mock_reward_rule: Callable,
    reward_status_adjustment_task_type: "TaskType",
) -> None:

    mocker.patch(
        "vela.internal_requests.send_async_request_with_retry", return_value=(status.HTTP_200_OK, {"status": "active"})
    )
    mocker.patch("retry_tasks_lib.utils.asynchronous.enqueue_many_retry_tasks")
    mock_campaign = create_mock_campaign(
        **{
            "status": CampaignStatuses.ACTIVE,
            "name": "negativetestcampaign",
            "slug": "negative-test-campaign",
            "loyalty_type": LoyaltyTypes.ACCUMULATOR,
            "start_date": datetime.now(tz=timezone.utc) - timedelta(days=1),
        }
    )
    create_mock_reward_rule(
        reward_slug="negative-test-reward", campaign_id=mock_campaign.id, reward_goal=10, allocation_window=5
    )
    create_mock_earn_rule(
        campaign_id=mock_campaign.id, **{"threshold": 300, "increment_multiplier": 10, "increment": 1}
    )
    payload["transaction_total"] = -payload["transaction_total"]  # i.e. a negative transaction

    resp = client.post(f"{settings.API_PREFIX}/{retailer.slug}/transaction", json=payload, headers=auth_headers)

    assert resp.status_code == status.HTTP_200_OK
    assert resp.json() == "Refund accepted"

    processed_transaction = (
        db_session.query(ProcessedTransaction).filter_by(transaction_id=payload["id"], retailer_id=retailer.id).first()
    )

    assert processed_transaction is not None
    assert processed_transaction.mid == payload["MID"]
    assert processed_transaction.amount == payload["transaction_total"]  # no increment multiplier s/be applied
    assert processed_transaction.datetime == datetime.fromtimestamp(timestamp_now, tz=timezone.utc).replace(tzinfo=None)
    assert processed_transaction.account_holder_uuid == account_holder_uuid


def test_post_transaction_zero_amount(
    db_session: "Session",
    retailer: RetailerRewards,
    payload: dict,
    mocker: MockerFixture,
    reward_adjustment_task_type: "TaskType",
    create_mock_campaign: Callable,
    create_mock_earn_rule: Callable,
    create_mock_reward_rule: Callable,
    reward_status_adjustment_task_type: "TaskType",
) -> None:

    mocker.patch(
        "vela.internal_requests.send_async_request_with_retry", return_value=(status.HTTP_200_OK, {"status": "active"})
    )
    mocker.patch("retry_tasks_lib.utils.asynchronous.enqueue_many_retry_tasks")
    mock_campaign = create_mock_campaign(
        **{
            "status": CampaignStatuses.ACTIVE,
            "name": "zerotestcampaign",
            "slug": "zero-test-campaign",
            "loyalty_type": LoyaltyTypes.ACCUMULATOR,
            "start_date": datetime.now(tz=timezone.utc) - timedelta(days=1),
        }
    )
    mock_get_tx_import_activity_data = mocker.patch(
        "vela.activity_utils.enums.ActivityType.get_tx_import_activity_data",
        return_value={"mock": "payload"},
    )
    mock_get_processed_tx_activity_data = mocker.patch(
        "vela.activity_utils.enums.ActivityType.get_processed_tx_activity_data",
        return_value={"mock": "payload"},
    )
    mock_async_send_activity = mocker.patch("vela.api.endpoints.transaction.async_send_activity")
    create_mock_reward_rule(
        reward_slug="zero-test-reward", campaign_id=mock_campaign.id, reward_goal=10, allocation_window=5
    )
    create_mock_earn_rule(campaign_id=mock_campaign.id, **{"threshold": 300, "increment_multiplier": 1, "increment": 1})
    payload["transaction_total"] = 0

    resp = client.post(f"{settings.API_PREFIX}/{retailer.slug}/transaction", json=payload, headers=auth_headers)

    assert resp.status_code == status.HTTP_200_OK
    assert resp.json() == "Threshold not met"

    processed_transaction = (
        db_session.query(ProcessedTransaction).filter_by(transaction_id=payload["id"], retailer_id=retailer.id).first()
    )

    assert processed_transaction is not None
    assert processed_transaction.mid == payload["MID"]
    assert processed_transaction.amount == payload["transaction_total"]
    assert processed_transaction.datetime == datetime.fromtimestamp(timestamp_now, tz=timezone.utc).replace(tzinfo=None)
    assert processed_transaction.account_holder_uuid == account_holder_uuid
    processed_datetime = datetime.fromtimestamp(float(payload["datetime"]), tz=timezone.utc)
    transaction_data = {
        "transaction_id": payload["id"],
        "payment_transaction_id": "BPL123456789",
        "amount": 0,
        "datetime": processed_datetime,
        "mid": "12345678",
        "account_holder_uuid": account_holder_uuid,
    }

    tx_import_activity_data = {
        "retailer_slug": retailer.slug,
        "active_campaign_slugs": ["zero-test-campaign"],
        "refunds_valid": True,
        "error": "N/A",
    }
    mock_get_tx_import_activity_data.assert_called_with(
        transaction=transaction_data,
        data=tx_import_activity_data,
    )

    mock_get_processed_tx_activity_data.assert_called_once()

    expected_calls = [  # The expected call stack for send_activity, in order
        call().send({"mock": "payload"}, routing_key=ActivityType.TX_HISTORY.value),
        call().send({"mock": "payload"}, routing_key=ActivityType.TX_IMPORT.value),
    ]
    mock_async_send_activity.assert_has_calls(expected_calls)


def test_post_transaction_negative_amount_but_no_allocation_window(
    db_session: "Session",
    retailer: RetailerRewards,
    payload: dict,
    mocker: MockerFixture,
    reward_adjustment_task_type: "TaskType",
    create_mock_campaign: Callable,
    create_mock_earn_rule: Callable,
    create_mock_reward_rule: Callable,
    reward_status_adjustment_task_type: "TaskType",
) -> None:

    mocker.patch(
        "vela.internal_requests.send_async_request_with_retry", return_value=(status.HTTP_200_OK, {"status": "active"})
    )
    mock_get_tx_import_activity_data = mocker.patch(
        "vela.activity_utils.enums.ActivityType.get_tx_import_activity_data",
        return_value={"mock": "payload"},
    )
    mock_get_processed_tx_activity_data = mocker.patch(
        "vela.activity_utils.enums.ActivityType.get_processed_tx_activity_data",
        return_value={"mock": "payload"},
    )
    mock_async_send_activity = mocker.patch("vela.api.endpoints.transaction.async_send_activity")
    mocker.patch("retry_tasks_lib.utils.asynchronous.enqueue_many_retry_tasks")
    mock_campaign = create_mock_campaign(
        **{
            "status": CampaignStatuses.ACTIVE,
            "name": "negativetestcampaign",
            "slug": "negative-test-campaign",
            "loyalty_type": LoyaltyTypes.ACCUMULATOR,
            "start_date": datetime.now(tz=timezone.utc) - timedelta(days=1),
        }
    )
    create_mock_reward_rule(
        reward_slug="negative-test-reward", campaign_id=mock_campaign.id, reward_goal=10, allocation_window=0
    )
    create_mock_earn_rule(campaign_id=mock_campaign.id, **{"threshold": 300, "increment_multiplier": 1, "increment": 1})
    payload["transaction_total"] = -payload["transaction_total"]  # i.e. a negative transaction

    resp = client.post(f"{settings.API_PREFIX}/{retailer.slug}/transaction", json=payload, headers=auth_headers)

    assert resp.status_code == status.HTTP_200_OK
    assert resp.json() == "Refunds not accepted"

    processed_transaction = (
        db_session.query(ProcessedTransaction).filter_by(transaction_id=payload["id"], retailer_id=retailer.id).first()
    )

    assert processed_transaction is not None
    assert processed_transaction.mid == payload["MID"]
    assert processed_transaction.amount == payload["transaction_total"]
    assert processed_transaction.datetime == datetime.fromtimestamp(timestamp_now, tz=timezone.utc).replace(tzinfo=None)
    assert processed_transaction.account_holder_uuid == account_holder_uuid
    processed_datetime = datetime.fromtimestamp(float(payload["datetime"]), tz=timezone.utc)
    transaction_data = {
        "transaction_id": payload["id"],
        "payment_transaction_id": "BPL123456789",
        "amount": processed_transaction.amount,
        "datetime": processed_datetime,
        "mid": "12345678",
        "account_holder_uuid": account_holder_uuid,
    }

    tx_import_activity_data = {
        "retailer_slug": retailer.slug,
        "active_campaign_slugs": [mock_campaign.slug],
        "refunds_valid": False,
        "error": "N/A",
    }
    mock_get_tx_import_activity_data.assert_called_with(
        transaction=transaction_data,
        data=tx_import_activity_data,
    )

    mock_get_processed_tx_activity_data.assert_called_once()

    expected_calls = [  # The expected call stack for send_activity, in order
        call().send({"mock": "payload"}, routing_key=ActivityType.TX_HISTORY.value),
        call().send({"mock": "payload"}, routing_key=ActivityType.TX_IMPORT.value),
    ]
    mock_async_send_activity.assert_has_calls(expected_calls)


def test_post_transaction_negative_amount_but_not_accumulator(
    db_session: "Session",
    retailer: RetailerRewards,
    payload: dict,
    mocker: MockerFixture,
    reward_adjustment_task_type: "TaskType",
    create_mock_campaign: Callable,
    create_mock_earn_rule: Callable,
    create_mock_reward_rule: Callable,
    reward_status_adjustment_task_type: "TaskType",
) -> None:

    mocker.patch(
        "vela.internal_requests.send_async_request_with_retry", return_value=(status.HTTP_200_OK, {"status": "active"})
    )
    mocker.patch("retry_tasks_lib.utils.asynchronous.enqueue_many_retry_tasks")
    mock_get_tx_import_activity_data = mocker.patch(
        "vela.activity_utils.enums.ActivityType.get_tx_import_activity_data",
        return_value={"mock": "payload"},
    )
    mock_get_processed_tx_activity_data = mocker.patch(
        "vela.activity_utils.enums.ActivityType.get_processed_tx_activity_data",
        return_value={"mock": "payload"},
    )
    mock_async_send_activity = mocker.patch("vela.api.endpoints.transaction.async_send_activity")
    mock_campaign = create_mock_campaign(
        **{
            "status": CampaignStatuses.ACTIVE,
            "name": "negativetestcampaign",
            "slug": "negative-test-campaign",
            "loyalty_type": LoyaltyTypes.STAMPS,
            "start_date": datetime.now(tz=timezone.utc) - timedelta(days=1),
        }
    )
    create_mock_reward_rule(
        reward_slug="negative-test-reward", campaign_id=mock_campaign.id, reward_goal=10, allocation_window=5
    )
    create_mock_earn_rule(campaign_id=mock_campaign.id, **{"threshold": 300, "increment_multiplier": 1, "increment": 1})
    payload["transaction_total"] = -payload["transaction_total"]  # i.e. a negative transaction

    resp = client.post(f"{settings.API_PREFIX}/{retailer.slug}/transaction", json=payload, headers=auth_headers)

    assert resp.status_code == status.HTTP_200_OK
    assert resp.json() == "Refunds not accepted"

    processed_transaction = (
        db_session.query(ProcessedTransaction).filter_by(transaction_id=payload["id"], retailer_id=retailer.id).first()
    )

    assert processed_transaction is not None
    assert processed_transaction.mid == payload["MID"]
    assert processed_transaction.amount == payload["transaction_total"]
    assert processed_transaction.datetime == datetime.fromtimestamp(timestamp_now, tz=timezone.utc).replace(tzinfo=None)
    assert processed_transaction.account_holder_uuid == account_holder_uuid
    processed_datetime = datetime.fromtimestamp(float(payload["datetime"]), tz=timezone.utc)
    transaction_data = {
        "transaction_id": payload["id"],
        "payment_transaction_id": "BPL123456789",
        "amount": processed_transaction.amount,
        "datetime": processed_datetime,
        "mid": "12345678",
        "account_holder_uuid": account_holder_uuid,
    }

    tx_import_activity_data = {
        "retailer_slug": retailer.slug,
        "active_campaign_slugs": [mock_campaign.slug],
        "refunds_valid": False,
        "error": "N/A",
    }
    mock_get_tx_import_activity_data.assert_called_with(
        transaction=transaction_data,
        data=tx_import_activity_data,
    )

    mock_get_processed_tx_activity_data.assert_called_once()

    expected_calls = [  # The expected call stack for send_activity, in order
        call().send({"mock": "payload"}, routing_key=ActivityType.TX_HISTORY.value),
        call().send({"mock": "payload"}, routing_key=ActivityType.TX_IMPORT.value),
    ]
    mock_async_send_activity.assert_has_calls(expected_calls)
