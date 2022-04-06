# pylint: disable=too-many-arguments,no-value-for-parameter

import json

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from unittest import mock
from uuid import uuid4

import httpretty
import httpx
import pytest
import requests

from pytest_mock import MockerFixture
from retry_tasks_lib.db.models import RetryTask, TaskType
from retry_tasks_lib.enums import RetryTaskStatuses
from retry_tasks_lib.utils.synchronous import IncorrectRetryTaskStatusError, sync_create_task

from app.core.config import redis_raw, settings
from app.enums import CampaignStatuses
from app.models import Campaign, RewardRule
from app.tasks.campaign_balances import update_campaign_balances
from app.tasks.reward_adjustment import (
    _process_balance_adjustment,
    _process_reward_allocation,
    _reward_achieved,
    _set_param_value,
    adjust_balance,
)
from app.tasks.reward_status_adjustment import _process_reward_status_adjustment, reward_status_adjustment

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


fake_now = datetime.now(tz=timezone.utc)


@httpretty.activate
@mock.patch("app.tasks.reward_adjustment.datetime")
def test__process_adjustment_ok(
    mock_datetime: mock.Mock,
    reward_adjustment_task: RetryTask,
    adjustment_url: str,
) -> None:
    task_params = reward_adjustment_task.get_params()

    mock_datetime.now.return_value = fake_now
    httpretty.register_uri(
        "POST",
        adjustment_url,
        body=json.dumps({"new_balance": 100, "campaign_slug": task_params["campaign_slug"]}),
        status=200,
    )

    new_balance, response_audit = _process_balance_adjustment(
        retailer_slug=task_params["retailer_slug"],
        account_holder_uuid=task_params["account_holder_uuid"],
        adjustment_amount=task_params["adjustment_amount"],
        campaign_slug=task_params["campaign_slug"],
        idempotency_token=task_params["pre_allocation_token"],
    )

    last_request = httpretty.last_request()
    assert last_request.method == "POST"
    assert last_request.url == adjustment_url
    assert json.loads(last_request.body) == {
        "balance_change": task_params["adjustment_amount"],
        "campaign_slug": task_params["campaign_slug"],
    }

    assert response_audit == {
        "request": {
            "body": json.dumps({"balance_change": 100, "campaign_slug": "test-campaign"}),
            "url": "{0}/{1}/accounts/{2}/adjustments".format(
                settings.POLARIS_BASE_URL, task_params["retailer_slug"], task_params["account_holder_uuid"]
            ),
        },
        "timestamp": fake_now.isoformat(),
        "response": {
            "status": 200,
            "body": json.dumps(
                {
                    "new_balance": new_balance,
                    "campaign_slug": task_params["campaign_slug"],
                }
            ),
        },
    }


@httpretty.activate
def test__process_adjustment_http_errors(
    reward_adjustment_task: RetryTask,
    adjustment_url: str,
) -> None:

    task_params = reward_adjustment_task.get_params()

    for status, body in [
        (401, "Unauthorized"),
        (500, "Internal Server Error"),
    ]:
        httpretty.register_uri("POST", adjustment_url, body=body, status=status)

        with pytest.raises(requests.RequestException) as excinfo:
            _process_balance_adjustment(
                retailer_slug=task_params["retailer_slug"],
                account_holder_uuid=task_params["account_holder_uuid"],
                adjustment_amount=task_params["adjustment_amount"],
                campaign_slug=task_params["campaign_slug"],
                idempotency_token=task_params["pre_allocation_token"],
            )

        assert isinstance(excinfo.value, requests.RequestException)
        assert excinfo.value.response.status_code == status

        last_request = httpretty.last_request()
        assert last_request.method == "POST"
        assert json.loads(last_request.body) == {
            "balance_change": task_params["adjustment_amount"],
            "campaign_slug": task_params["campaign_slug"],
        }


@mock.patch("app.tasks.reward_adjustment.send_request_with_metrics")
def test__process_adjustment_connection_error(
    mock_send_request_with_metrics: mock.MagicMock,
    reward_adjustment_task: RetryTask,
) -> None:

    mock_send_request_with_metrics.side_effect = httpx.TimeoutException("Request timed out")
    task_params = reward_adjustment_task.get_params()

    with pytest.raises(httpx.RequestError) as excinfo:
        _process_balance_adjustment(
            retailer_slug=task_params["retailer_slug"],
            account_holder_uuid=task_params["account_holder_uuid"],
            adjustment_amount=task_params["adjustment_amount"],
            campaign_slug=task_params["campaign_slug"],
            idempotency_token=task_params["pre_allocation_token"],
        )

    assert isinstance(excinfo.value, httpx.TimeoutException)
    assert not hasattr(excinfo.value, "response")


@mock.patch("app.tasks.reward_adjustment.send_request_with_metrics")
def test__process_reward_allocation_connection_error(
    mock_send_request_with_metrics: mock.MagicMock,
    reward_adjustment_task: RetryTask,
) -> None:

    mock_send_request_with_metrics.side_effect = httpx.TimeoutException("Request timed out")

    with pytest.raises(httpx.RequestError) as excinfo:
        _process_reward_allocation(
            retailer_slug="retailer_slug",
            reward_slug="slug",
            account_holder_uuid="uuid",
            idempotency_token="token",
        )

    assert isinstance(excinfo.value, httpx.TimeoutException)
    assert not hasattr(excinfo.value, "response")


@httpretty.activate
def test_adjust_balance(
    db_session: "Session",
    reward_adjustment_task: RetryTask,
    reward_rule: RewardRule,
    adjustment_url: str,
    allocation_url: str,
    mocker: MockerFixture,
) -> None:
    task_params = reward_adjustment_task.get_params()

    httpretty.register_uri(
        "POST",
        adjustment_url,
        body=json.dumps({"new_balance": 100, "campaign_slug": task_params["campaign_slug"]}),
        status=200,
    )
    httpretty.register_uri(
        "POST",
        allocation_url,
        body=json.dumps({"account_url": "http://account-url/"}),
        status=202,
    )

    adjust_balance(reward_adjustment_task.retry_task_id)

    db_session.refresh(reward_adjustment_task)

    assert reward_adjustment_task.attempts == 1
    assert reward_adjustment_task.next_attempt_time is None
    assert reward_adjustment_task.status == RetryTaskStatuses.SUCCESS
    assert len(reward_adjustment_task.audit_data) == 3


@httpretty.activate
def test_adjust_balance_pending_reward(
    db_session: "Session", reward_adjustment_task: RetryTask, reward_rule: RewardRule, adjustment_url: str
) -> None:
    reward_rule.allocation_window = 15
    db_session.commit()

    task_params = reward_adjustment_task.get_params()
    httpretty.register_uri(
        "POST",
        adjustment_url,
        body=json.dumps({"new_balance": 100, "campaign_slug": task_params["campaign_slug"]}),
        status=200,
    )
    httpretty.register_uri(
        "POST",
        "{base_url}/{retailer_slug}/accounts/{account_holder_uuid}/pendingrewardallocation".format(
            base_url=settings.POLARIS_BASE_URL,
            retailer_slug=task_params["retailer_slug"],
            account_holder_uuid=task_params["account_holder_uuid"],
        ),
        status=202,
    )

    adjust_balance(reward_adjustment_task.retry_task_id)

    db_session.refresh(reward_adjustment_task)

    assert reward_adjustment_task.attempts == 1
    assert reward_adjustment_task.next_attempt_time is None
    assert reward_adjustment_task.status == RetryTaskStatuses.SUCCESS
    assert len(reward_adjustment_task.audit_data) == 3


@httpretty.activate
@mock.patch("app.tasks.reward_adjustment.enqueue_retry_task")
@mock.patch("app.tasks.reward_adjustment.sync_create_task", return_value=mock.MagicMock(retry_task_id=9999))
def test_adjust_balance_multiple_rewards(
    mock_sync_create_task: mock.MagicMock,
    mock_enqueue_retry_task: mock.MagicMock,
    db_session: "Session",
    reward_adjustment_task: RetryTask,
    reward_rule: RewardRule,
    adjustment_url: str,
    allocation_url: str,
    mocker: MockerFixture,
) -> None:
    task_params = reward_adjustment_task.get_params()

    reward_rule.reward_goal = 50
    db_session.commit()
    assert reward_adjustment_task.get_params()["adjustment_amount"] == 100

    httpretty.register_uri(
        "POST",
        adjustment_url,
        responses=[
            httpretty.core.httpretty.Response(
                method=httpretty.POST,
                body=json.dumps({"new_balance": 100, "campaign_slug": task_params["campaign_slug"]}),
            ),
            httpretty.core.httpretty.Response(
                method=httpretty.POST,
                body=json.dumps({"new_balance": 50, "campaign_slug": task_params["campaign_slug"]}),
            ),
        ],
        status=200,
    )
    httpretty.register_uri(
        "POST",
        allocation_url,
        body=json.dumps({"account_url": "http://account-url/"}),
        status=202,
    )
    mock_secondary_task = mock.MagicMock(retry_task_id=42)
    mock_sync_create_task.return_value = mock_secondary_task

    adjust_balance(reward_adjustment_task.retry_task_id)

    db_session.refresh(reward_adjustment_task)

    assert reward_adjustment_task.attempts == 1
    assert reward_adjustment_task.next_attempt_time is None
    assert reward_adjustment_task.status == RetryTaskStatuses.SUCCESS
    assert len(reward_adjustment_task.audit_data) == 3
    mock_sync_create_task.assert_called_once_with(
        mock.ANY,
        task_type_name="reward-adjustment",
        params={
            "processed_transaction_id": task_params["processed_transaction_id"],
            "account_holder_uuid": task_params["account_holder_uuid"],
            "retailer_slug": task_params["retailer_slug"],
            "campaign_slug": task_params["campaign_slug"],
            "reward_only": True,
        },
    )
    mock_enqueue_retry_task.assert_called_once_with(connection=redis_raw, retry_task=mock_secondary_task, at_front=True)


@mock.patch("app.tasks.requests")
def test_adjust_balance_task_cancelled_when_campaign_cancelled_or_ended(
    mock_requests: mock.MagicMock,
    db_session: "Session",
    reward_adjustment_task: RetryTask,
    campaign: Campaign,
) -> None:
    attempts = reward_adjustment_task.attempts
    for status in (CampaignStatuses.ENDED, CampaignStatuses.CANCELLED):
        attempts = reward_adjustment_task.attempts
        reward_adjustment_task.status = RetryTaskStatuses.PENDING
        campaign.status = status
        db_session.commit()

        adjust_balance(reward_adjustment_task.retry_task_id)

        db_session.refresh(reward_adjustment_task)

        mock_requests.assert_not_called()
        assert reward_adjustment_task.attempts == attempts + 1
        assert reward_adjustment_task.next_attempt_time is None
        assert reward_adjustment_task.status == RetryTaskStatuses.CANCELLED


@httpretty.activate
@mock.patch("app.tasks.reward_adjustment._reward_achieved")
def test_adjust_balance_fails_with_409_no_balance_for_campaign_slug(
    mock__reward_achieved: mock.MagicMock,
    db_session: "Session",
    reward_adjustment_task: RetryTask,
    reward_rule: RewardRule,
    adjustment_url: str,
) -> None:
    task_params = reward_adjustment_task.get_params()

    httpretty.register_uri(
        "POST",
        adjustment_url,
        body=json.dumps({"new_balance": 100, "campaign_slug": task_params["campaign_slug"]}),
        status=409,
    )

    with pytest.raises(requests.RequestException):
        adjust_balance(reward_adjustment_task.retry_task_id)
    mock__reward_achieved.assert_not_called()


@httpretty.activate
def test_adjust_balance_reward_allocation_call_fails(
    db_session: "Session",
    reward_adjustment_task: RetryTask,
    reward_rule: RewardRule,
    adjustment_url: str,
    allocation_url: str,
) -> None:
    task_params = reward_adjustment_task.get_params()

    httpretty.register_uri(
        "POST",
        adjustment_url,
        body=json.dumps({"new_balance": 100, "campaign_slug": task_params["campaign_slug"]}),
        status=200,
    )
    httpretty.register_uri(
        "POST",
        allocation_url,
        body=json.dumps({"account_url": "http://account-url/"}),
        status=500,
    )

    with pytest.raises(requests.RequestException) as excinfo:
        adjust_balance(reward_adjustment_task.retry_task_id)
    assert isinstance(excinfo.value, requests.RequestException)
    assert hasattr(excinfo.value, "response")

    db_session.refresh(reward_adjustment_task)

    assert reward_adjustment_task.attempts == 1
    assert reward_adjustment_task.status == RetryTaskStatuses.IN_PROGRESS
    assert len(reward_adjustment_task.audit_data) == 1


def test_adjust_balance_wrong_status(
    db_session: "Session",
    reward_adjustment_task: RetryTask,
) -> None:
    reward_adjustment_task.status = RetryTaskStatuses.FAILED
    db_session.commit()

    with pytest.raises(IncorrectRetryTaskStatusError):
        adjust_balance(reward_adjustment_task.retry_task_id)

    db_session.refresh(reward_adjustment_task)

    assert reward_adjustment_task.attempts == 0
    assert reward_adjustment_task.next_attempt_time is None
    assert reward_adjustment_task.status == RetryTaskStatuses.FAILED


@httpretty.activate
@mock.patch("app.tasks.reward_adjustment.datetime")
def test__process_reward_allocation(
    mock_datetime: mock.MagicMock,
    reward_adjustment_task: RetryTask,
    reward_rule: RewardRule,
    reward_slug: str,
    allocation_url: str,
) -> None:
    task_params = reward_adjustment_task.get_params()
    mock_datetime.now.return_value = fake_now
    httpretty.register_uri(
        "POST",
        allocation_url,
        body=json.dumps({}),
        status=202,
    )
    retailer_slug = task_params["retailer_slug"]
    account_holder_uuid = task_params["account_holder_uuid"]

    response_audit = _process_reward_allocation(
        retailer_slug=retailer_slug,
        reward_slug=reward_slug,
        account_holder_uuid=account_holder_uuid,
        idempotency_token=str(uuid4()),
    )

    last_request = httpretty.last_request()
    assert last_request.method == "POST"
    assert "idempotency-token" in last_request.headers
    assert last_request.url == allocation_url

    account_url = f"{settings.POLARIS_BASE_URL}/{retailer_slug}/accounts/{account_holder_uuid}/rewards"
    assert json.loads(last_request.body) == {
        "account_url": account_url,
    }
    assert response_audit == {
        "request": {"body": json.dumps({"account_url": account_url}), "url": allocation_url},
        "timestamp": fake_now.isoformat(),
        "response": {
            "status": 202,
            "body": json.dumps({}),
        },
    }


@httpretty.activate
def test__process_reward_allocation_http_errors(
    reward_adjustment_task: RetryTask,
    allocation_url: str,
    reward_slug: str,
) -> None:
    task_params = reward_adjustment_task.get_params()
    retailer_slug = task_params["retailer_slug"]
    account_holder_uuid = task_params["account_holder_uuid"]
    idempotency_token = task_params["pre_allocation_token"]
    for status, body in [
        (401, "Unauthorized"),
        (500, "Internal Server Error"),
    ]:
        httpretty.register_uri("POST", allocation_url, body=body, status=status)

        with pytest.raises(requests.RequestException) as excinfo:
            _process_reward_allocation(
                retailer_slug=retailer_slug,
                reward_slug=reward_slug,
                account_holder_uuid=account_holder_uuid,
                idempotency_token=idempotency_token,
            )

        assert isinstance(excinfo.value, requests.RequestException)
        assert excinfo.value.response.status_code == status

        last_request = httpretty.last_request()
        assert last_request.method == "POST"
        assert json.loads(last_request.body) == {
            "account_url": (f"{settings.POLARIS_BASE_URL}/{retailer_slug}/accounts/{account_holder_uuid}/rewards"),
        }


def test__reward_achieved(
    db_session: "Session",
    reward_adjustment_task: RetryTask,
    reward_rule: RewardRule,
) -> None:
    def _compare_result(result: bool, expected_result: bool) -> None:
        assert result == expected_result

    assert reward_rule.reward_goal == 5
    _compare_result(_reward_achieved(reward_rule, 1), False)
    _compare_result(_reward_achieved(reward_rule, -5), False)
    _compare_result(_reward_achieved(reward_rule, 5), True)
    _compare_result(_reward_achieved(reward_rule, 10), True)


@httpretty.activate
def test__process_reward_status_adjustment_ok(
    reward_status_adjustment_retry_task: RetryTask,
    reward_status_adjustment_expected_payload: dict,
    reward_status_adjustment_url: str,
) -> None:

    httpretty.register_uri("PATCH", reward_status_adjustment_url, body="OK", status=202)

    response_audit = _process_reward_status_adjustment(reward_status_adjustment_retry_task.get_params())

    last_request = httpretty.last_request()
    assert last_request.method == "PATCH"
    assert json.loads(last_request.body) == reward_status_adjustment_expected_payload
    assert response_audit == {
        "timestamp": mock.ANY,
        "response": {
            "status": 202,
            "body": "OK",
        },
    }


@httpretty.activate
def test__process_reward_status_adjustment_http_errors(
    reward_status_adjustment_retry_task: RetryTask,
    reward_status_adjustment_expected_payload: dict,
    reward_status_adjustment_url: str,
) -> None:

    for status, body in [
        (401, "Unauthorized"),
        (500, "Internal Server Error"),
    ]:
        httpretty.register_uri("PATCH", reward_status_adjustment_url, body=body, status=status)

        with pytest.raises(requests.RequestException) as excinfo:
            _process_reward_status_adjustment(reward_status_adjustment_retry_task.get_params())

        assert isinstance(excinfo.value, requests.RequestException)
        assert excinfo.value.response.status_code == status

        last_request = httpretty.last_request()
        assert last_request.method == "PATCH"
        assert json.loads(last_request.body) == reward_status_adjustment_expected_payload


@mock.patch("app.tasks.reward_status_adjustment.send_request_with_metrics")
def test__process_reward_status_adjustment_connection_error(
    mock_send_request_with_metrics: mock.MagicMock, reward_status_adjustment_retry_task: RetryTask
) -> None:

    mock_send_request_with_metrics.side_effect = requests.Timeout("Request timed out")

    with pytest.raises(requests.RequestException) as excinfo:
        _process_reward_status_adjustment(reward_status_adjustment_retry_task.get_params())

    assert isinstance(excinfo.value, requests.Timeout)
    assert excinfo.value.response is None


def test__set_param_value(db_session: "Session", reward_adjustment_task: RetryTask) -> None:
    value = str(uuid4())
    assert 999 == _set_param_value(db_session, reward_adjustment_task, "secondary_reward_retry_task_id", 999)
    assert value == _set_param_value(db_session, reward_adjustment_task, "post_allocation_token", value)


@httpretty.activate
def test_reward_status_adjustment(
    db_session: "Session", reward_status_adjustment_retry_task: RetryTask, reward_status_adjustment_url: str
) -> None:

    httpretty.register_uri("PATCH", reward_status_adjustment_url, body="OK", status=202)

    reward_status_adjustment(reward_status_adjustment_retry_task.retry_task_id)

    db_session.refresh(reward_status_adjustment_retry_task)

    assert reward_status_adjustment_retry_task.attempts == 1
    assert reward_status_adjustment_retry_task.next_attempt_time is None
    assert reward_status_adjustment_retry_task.status == RetryTaskStatuses.SUCCESS


def test_reward_status_adjustment_wrong_status(
    db_session: "Session", reward_status_adjustment_retry_task: RetryTask
) -> None:
    reward_status_adjustment_retry_task.status = RetryTaskStatuses.FAILED
    db_session.commit()

    with pytest.raises(IncorrectRetryTaskStatusError):
        reward_status_adjustment(reward_status_adjustment_retry_task.retry_task_id)

    db_session.refresh(reward_status_adjustment_retry_task)

    assert reward_status_adjustment_retry_task.attempts == 0
    assert reward_status_adjustment_retry_task.next_attempt_time is None
    assert reward_status_adjustment_retry_task.status == RetryTaskStatuses.FAILED


@httpretty.activate
def test_update_campaign_balances(
    db_session: "Session", create_campaign_balances_task_type: TaskType, delete_campaign_balances_task_type: TaskType
) -> None:
    params = {"retailer_slug": "sample-retailer", "campaign_slug": "sample-campaign"}
    url = "{base_url}/{retailer_slug}/accounts/{campaign_slug}/balances".format(
        base_url=settings.POLARIS_BASE_URL, **params
    )

    httpretty.register_uri("POST", url, body={}, status=202)
    httpretty.register_uri("DELETE", url, body={}, status=202)

    create_campaign_balances_task = sync_create_task(
        db_session, task_type_name=create_campaign_balances_task_type.name, params=params
    )
    delete_campaign_balances_task = sync_create_task(
        db_session, task_type_name=delete_campaign_balances_task_type.name, params=params
    )
    db_session.commit()

    update_campaign_balances(create_campaign_balances_task.retry_task_id)
    create_request = httpretty.last_request()

    update_campaign_balances(delete_campaign_balances_task.retry_task_id)
    delete_request = httpretty.last_request()

    db_session.refresh(create_campaign_balances_task)
    db_session.refresh(delete_campaign_balances_task)

    assert create_request.url == url
    assert create_request.method == "POST"
    assert create_campaign_balances_task.status == RetryTaskStatuses.SUCCESS
    assert create_campaign_balances_task.attempts == 1
    assert create_campaign_balances_task.next_attempt_time is None

    assert delete_request.url == url
    assert delete_request.method == "DELETE"
    assert delete_campaign_balances_task.status == RetryTaskStatuses.SUCCESS
    assert delete_campaign_balances_task.attempts == 1
    assert delete_campaign_balances_task.next_attempt_time is None
