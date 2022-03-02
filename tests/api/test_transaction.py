from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Callable
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from fastapi import status
from fastapi.testclient import TestClient
from httpx import Request, Response
from pytest_mock import MockerFixture

from app.core.config import settings
from app.enums import CampaignStatuses, LoyaltyTypes
from app.models import EarnRule, ProcessedTransaction, RetailerRewards, Transaction
from asgi import app
from tests.conftest import SetupType

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
        "id": "BPL123456789",
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
    response = MagicMock(spec=Response, json=lambda: {"status": "active"}, status_code=status.HTTP_200_OK)
    mocker.patch("app.internal_requests.send_async_request_with_retry", return_value=response)
    mocker.patch("retry_tasks_lib.utils.asynchronous.enqueue_many_retry_tasks")
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
    assert processed_transaction.datetime == datetime.fromtimestamp(timestamp_now, tz=timezone.utc).replace(tzinfo=None)
    assert processed_transaction.account_holder_uuid == account_holder_uuid


def test_post_transaction_not_awarded(
    setup: SetupType, payload: dict, earn_rule: EarnRule, mocker: MockerFixture
) -> None:
    db_session, retailer, _ = setup
    response = MagicMock(spec=Response, json=lambda: {"status": "active"}, status_code=status.HTTP_200_OK)
    mocker.patch("app.internal_requests.send_async_request_with_retry", return_value=response)

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
    assert processed_transaction.datetime == datetime.fromtimestamp(timestamp_now, tz=timezone.utc).replace(tzinfo=None)
    assert processed_transaction.account_holder_uuid == account_holder_uuid


def test_post_transaction_no_active_campaigns(
    setup: SetupType, payload: dict, earn_rule: EarnRule, mocker: MockerFixture
) -> None:
    db_session, retailer, campaign = setup

    campaign.status = CampaignStatuses.DRAFT
    db_session.commit()

    response = MagicMock(spec=Response, json=lambda: {"status": "active"}, status_code=status.HTTP_200_OK)
    mocker.patch("app.internal_requests.send_async_request_with_retry", return_value=response)

    resp = client.post(f"{settings.API_PREFIX}/{retailer.slug}/transaction", json=payload, headers=auth_headers)

    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert resp.json() == {"display_message": "No active campaigns found for retailer.", "code": "NO_ACTIVE_CAMPAIGNS"}

    transaction = db_session.query(Transaction).filter_by(transaction_id=payload["id"], retailer_id=retailer.id).first()

    assert transaction is not None
    assert transaction.mid == payload["MID"]
    assert transaction.amount == payload["transaction_total"]
    assert transaction.datetime == datetime.fromtimestamp(timestamp_now, tz=timezone.utc).replace(tzinfo=None)
    assert transaction.account_holder_uuid == account_holder_uuid


def test_post_transaction_no_active_campaigns_pre_start_date(
    setup: SetupType, payload: dict, earn_rule: EarnRule, mocker: MockerFixture
) -> None:
    db_session, retailer, campaign = setup
    transaction_timestamp = int((campaign.start_date.replace(tzinfo=timezone.utc) - timedelta(minutes=5)).timestamp())
    payload["datetime"] = transaction_timestamp

    response = MagicMock(spec=Response, json=lambda: {"status": "active"}, status_code=status.HTTP_200_OK)
    mocker.patch("app.internal_requests.send_async_request_with_retry", return_value=response)

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

    response = MagicMock(spec=Response, json=lambda: {"status": "active"}, status_code=status.HTTP_200_OK)
    mocker.patch("app.internal_requests.send_async_request_with_retry", return_value=response)

    resp = client.post(f"{settings.API_PREFIX}/{retailer.slug}/transaction", json=payload, headers=auth_headers)

    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert resp.json() == {"display_message": "No active campaigns found for retailer.", "code": "NO_ACTIVE_CAMPAIGNS"}

    transaction = db_session.query(Transaction).filter_by(transaction_id=payload["id"], retailer_id=retailer.id).first()

    assert transaction is not None
    assert transaction.mid == payload["MID"]
    assert transaction.amount == payload["transaction_total"]
    assert transaction.datetime == datetime.fromtimestamp(timestamp_now, tz=timezone.utc).replace(tzinfo=None)
    assert transaction.account_holder_uuid == account_holder_uuid


def test_post_transaction_existing_transaction(setup: SetupType, payload: dict, mocker: MockerFixture) -> None:
    retailer_slug = setup.retailer.slug
    response = MagicMock(spec=Response, json=lambda: {"status": "active"}, status_code=status.HTTP_200_OK)
    mocker.patch("app.internal_requests.send_async_request_with_retry", return_value=response)

    resp = client.post(f"{settings.API_PREFIX}/{retailer_slug}/transaction", json=payload, headers=auth_headers)

    assert resp.status_code == status.HTTP_200_OK

    resp = client.post(f"{settings.API_PREFIX}/{retailer_slug}/transaction", json=payload, headers=auth_headers)

    assert resp.status_code == status.HTTP_409_CONFLICT
    assert resp.json() == {"display_message": "Duplicate Transaction.", "code": "DUPLICATE_TRANSACTION"}


def test_post_transaction_wrong_retailer(payload: dict) -> None:
    resp = client.post(f"{settings.API_PREFIX}/NOT_A_RETIALER/transaction", json=payload, headers=auth_headers)
    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert resp.json() == {"display_message": "Requested retailer is invalid.", "code": "INVALID_RETAILER"}


def test_post_transaction_account_holder_validation_errors(
    setup: SetupType, payload: dict, mocker: MockerFixture
) -> None:
    retailer_slug = setup.retailer.slug
    request = Request(
        method="GET",
        url=f"{settings.POLARIS_BASE_URL}/{retailer_slug}/accounts/{payload['loyalty_id']}/status",
    )

    mocked_session = mocker.patch("app.internal_requests.send_async_request_with_retry")
    mocked_session.return_value = MagicMock(
        spec=Response, json=lambda: {"status": "pending"}, status_code=status.HTTP_200_OK
    )

    resp = client.post(f"{settings.API_PREFIX}/{retailer_slug}/transaction", json=payload, headers=auth_headers)

    assert resp.status_code == status.HTTP_409_CONFLICT
    assert resp.json() == {"display_message": "User Account not Active", "code": "USER_NOT_ACTIVE"}

    mocked_session.return_value = Response(status.HTTP_404_NOT_FOUND, request=request)

    resp = client.post(f"{settings.API_PREFIX}/{retailer_slug}/transaction", json=payload, headers=auth_headers)

    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert resp.json() == {"display_message": "Unknown User.", "code": "USER_NOT_FOUND"}

    mocked_session.return_value = Response(status.HTTP_500_INTERNAL_SERVER_ERROR, request=request)

    resp = client.post(f"{settings.API_PREFIX}/{retailer_slug}/transaction", json=payload, headers=auth_headers)

    assert resp.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert resp.json() == {
        "display_message": "An unexpected system error occurred, please try again later.",
        "code": "INTERNAL_ERROR",
    }


def _check_transaction_endpoint_422_response(retailer_slug: str, bad_payload: dict) -> None:
    resp = client.post(f"{settings.API_PREFIX}/{retailer_slug}/transaction", json=bad_payload, headers=auth_headers)
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert resp.json() == {"display_message": "BPL Schema not matched.", "code": "INVALID_CONTENT"}


def test_post_transaction_account_holder_empty_val_validation_errors(
    setup: SetupType, payload: dict, mocker: MockerFixture
) -> None:
    retailer_slug = setup.retailer.slug
    mocked_session = mocker.patch("app.internal_requests.send_async_request_with_retry")
    mocked_session.return_value = MagicMock(
        spec=Response, json=lambda: {"status": "pending"}, status_code=status.HTTP_200_OK
    )

    bad_payload = deepcopy(payload)

    bad_payload["id"] = ""
    _check_transaction_endpoint_422_response(retailer_slug, bad_payload)
    bad_payload = deepcopy(payload)

    bad_payload["id"] = "  "
    _check_transaction_endpoint_422_response(retailer_slug, bad_payload)
    bad_payload = deepcopy(payload)

    bad_payload["datetime"] = ""
    _check_transaction_endpoint_422_response(retailer_slug, bad_payload)
    bad_payload = deepcopy(payload)

    bad_payload["MID"] = ""
    _check_transaction_endpoint_422_response(retailer_slug, bad_payload)
    bad_payload = deepcopy(payload)

    bad_payload["MID"] = "   "
    _check_transaction_endpoint_422_response(retailer_slug, bad_payload)
    bad_payload = deepcopy(payload)

    bad_payload["loyalty_id"] = ""
    _check_transaction_endpoint_422_response(retailer_slug, bad_payload)


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
    response = MagicMock(spec=Response, json=lambda: {"status": "active"}, status_code=status.HTTP_200_OK)
    mocker.patch("app.internal_requests.send_async_request_with_retry", return_value=response)
    mocker.patch("retry_tasks_lib.utils.asynchronous.enqueue_many_retry_tasks")
    mock_campaign = create_mock_campaign(
        **{
            "status": CampaignStatuses.ACTIVE,
            "name": "negativetestcampaign",
            "slug": "negative-test-campaign",
            "loyalty_type": LoyaltyTypes.ACCUMULATOR,
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
    assert resp.json() == "Awarded"

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
    response = MagicMock(spec=Response, json=lambda: {"status": "active"}, status_code=status.HTTP_200_OK)
    mocker.patch("app.internal_requests.send_async_request_with_retry", return_value=response)
    mocker.patch("retry_tasks_lib.utils.asynchronous.enqueue_many_retry_tasks")
    mock_campaign = create_mock_campaign(
        **{
            "status": CampaignStatuses.ACTIVE,
            "name": "zerotestcampaign",
            "slug": "zero-test-campaign",
            "loyalty_type": LoyaltyTypes.ACCUMULATOR,
        }
    )
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
    response = MagicMock(spec=Response, json=lambda: {"status": "active"}, status_code=status.HTTP_200_OK)
    mocker.patch("app.internal_requests.send_async_request_with_retry", return_value=response)
    mocker.patch("retry_tasks_lib.utils.asynchronous.enqueue_many_retry_tasks")
    mock_campaign = create_mock_campaign(
        **{
            "status": CampaignStatuses.ACTIVE,
            "name": "negativetestcampaign",
            "slug": "negative-test-campaign",
            "loyalty_type": LoyaltyTypes.ACCUMULATOR,
        }
    )
    create_mock_reward_rule(
        reward_slug="negative-test-reward", campaign_id=mock_campaign.id, reward_goal=10, allocation_window=0
    )
    create_mock_earn_rule(campaign_id=mock_campaign.id, **{"threshold": 300, "increment_multiplier": 1, "increment": 1})
    payload["transaction_total"] = -payload["transaction_total"]  # i.e. a negative transaction

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
    response = MagicMock(spec=Response, json=lambda: {"status": "active"}, status_code=status.HTTP_200_OK)
    mocker.patch("app.internal_requests.send_async_request_with_retry", return_value=response)
    mocker.patch("retry_tasks_lib.utils.asynchronous.enqueue_many_retry_tasks")
    mock_campaign = create_mock_campaign(
        **{
            "status": CampaignStatuses.ACTIVE,
            "name": "negativetestcampaign",
            "slug": "negative-test-campaign",
            "loyalty_type": LoyaltyTypes.STAMPS,
        }
    )
    create_mock_reward_rule(
        reward_slug="negative-test-reward", campaign_id=mock_campaign.id, reward_goal=10, allocation_window=5
    )
    create_mock_earn_rule(campaign_id=mock_campaign.id, **{"threshold": 300, "increment_multiplier": 1, "increment": 1})
    payload["transaction_total"] = -payload["transaction_total"]  # i.e. a negative transaction

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
