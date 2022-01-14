import json

from datetime import datetime
from typing import Optional
from unittest import mock

import httpretty
import httpx
import pytest
import requests

from pytest_mock import MockerFixture
from retry_tasks_lib.db.models import RetryTask, TaskType, TaskTypeKey, TaskTypeKeyValue
from retry_tasks_lib.enums import RetryTaskStatuses
from retry_tasks_lib.utils.synchronous import sync_create_task
from sqlalchemy.future import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.enums import CampaignStatuses
from app.models import Campaign, RewardRule
from app.tasks import BalanceAdjustmentEnqueueException
from app.tasks.campaign_balances import update_campaign_balances
from app.tasks.reward_adjustment import (
    _process_adjustment,
    _process_voucher_allocation,
    _voucher_is_awardable,
    adjust_balance,
)
from app.tasks.voucher_status_adjustment import _process_voucher_status_adjustment, voucher_status_adjustment

fake_now = datetime.utcnow()


@httpretty.activate
@mock.patch("app.tasks.reward_adjustment.datetime")
def test__process_adjustment_ok(
    mock_datetime: mock.Mock,
    reward_adjustment_task: RetryTask,
    adjustment_url: str,
) -> None:
    task_params = reward_adjustment_task.get_params()

    mock_datetime.utcnow.return_value = fake_now
    httpretty.register_uri(
        "POST",
        adjustment_url,
        body=json.dumps({"new_balance": 100, "campaign_slug": task_params["campaign_slug"]}),
        status=200,
    )

    new_balance, campaign_slug, response_audit = _process_adjustment(task_params)

    last_request = httpretty.last_request()
    assert last_request.method == "POST"
    assert last_request.url == adjustment_url
    assert json.loads(last_request.body) == {
        "balance_change": task_params["adjustment_amount"],
        "campaign_slug": task_params["campaign_slug"],
    }

    assert response_audit == {
        "request": {
            "url": "{0}/bpl/loyalty/{1}/accounts/{2}/adjustments".format(
                settings.POLARIS_URL, task_params["retailer_slug"], task_params["account_holder_uuid"]
            ),
        },
        "timestamp": fake_now.isoformat(),
        "response": {
            "status": 200,
            "body": json.dumps(
                {
                    "new_balance": new_balance,
                    "campaign_slug": campaign_slug,
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
            _process_adjustment(task_params)

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

    with pytest.raises(httpx.RequestError) as excinfo:
        _process_adjustment(reward_adjustment_task.get_params())

    assert isinstance(excinfo.value, httpx.TimeoutException)
    assert not hasattr(excinfo.value, "response")


@mock.patch("app.tasks.reward_adjustment.send_request_with_metrics")
def test__process_voucher_allocation_connection_error(
    mock_send_request_with_metrics: mock.MagicMock,
    reward_adjustment_task: RetryTask,
) -> None:

    mock_send_request_with_metrics.side_effect = httpx.TimeoutException("Request timed out")

    with pytest.raises(httpx.RequestError) as excinfo:
        _process_voucher_allocation(reward_adjustment_task.get_params(), "slug")

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
    mock_enqueue = mocker.patch("app.tasks.reward_adjustment.enqueue_retry_task")
    reward_adjustment_task.status = RetryTaskStatuses.IN_PROGRESS
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
        allocation_url,
        body=json.dumps({"account_url": "http://account-url/"}),
        status=202,
    )

    adjust_balance(reward_adjustment_task.retry_task_id)

    db_session.refresh(reward_adjustment_task)

    assert reward_adjustment_task.attempts == 1
    assert reward_adjustment_task.next_attempt_time is None
    assert reward_adjustment_task.status == RetryTaskStatuses.SUCCESS
    assert len(reward_adjustment_task.audit_data) == 2

    post_voucher_adjustment_task: Optional[RetryTask] = (
        db_session.execute(
            select(RetryTask).where(
                RetryTask.retry_task_id != reward_adjustment_task.retry_task_id,
                TaskTypeKey.task_type_key_id == TaskTypeKeyValue.task_type_key_id,
                TaskTypeKeyValue.value == str(task_params["processed_transaction_id"]),
            )
        )
        .unique()
        .scalar_one_or_none()
    )

    assert post_voucher_adjustment_task is not None
    assert post_voucher_adjustment_task.get_params()["adjustment_amount"] < 0
    mock_enqueue.assert_called_once()


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
        reward_adjustment_task.status = RetryTaskStatuses.IN_PROGRESS
        campaign.status = status
        db_session.commit()

        adjust_balance(reward_adjustment_task.retry_task_id)

        db_session.refresh(reward_adjustment_task)

        mock_requests.assert_not_called()
        assert reward_adjustment_task.attempts == attempts + 1
        assert reward_adjustment_task.next_attempt_time is None
        assert reward_adjustment_task.status == RetryTaskStatuses.CANCELLED


@httpretty.activate
@mock.patch("app.tasks.reward_adjustment._voucher_is_awardable")
def test_adjust_balance_fails_with_409_no_balance_for_campaign_slug(
    mock__voucher_is_awardable: mock.MagicMock,
    db_session: "Session",
    reward_adjustment_task: RetryTask,
    reward_rule: RewardRule,
    adjustment_url: str,
) -> None:
    reward_adjustment_task.status = RetryTaskStatuses.IN_PROGRESS
    db_session.commit()
    task_params = reward_adjustment_task.get_params()

    httpretty.register_uri(
        "POST",
        adjustment_url,
        body=json.dumps({"new_balance": 100, "campaign_slug": task_params["campaign_slug"]}),
        status=409,
    )

    with pytest.raises(requests.RequestException):
        adjust_balance(reward_adjustment_task.retry_task_id)
    mock__voucher_is_awardable.assert_not_called()


@httpretty.activate
def test_adjust_balance_voucher_allocation_call_fails(
    db_session: "Session",
    reward_adjustment_task: RetryTask,
    reward_rule: RewardRule,
    adjustment_url: str,
    allocation_url: str,
) -> None:
    reward_adjustment_task.status = RetryTaskStatuses.IN_PROGRESS
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

    post_voucher_adjustment_task: Optional[RetryTask] = (
        db_session.execute(
            select(RetryTask).where(
                RetryTask.retry_task_id != reward_adjustment_task.retry_task_id,
                TaskTypeKey.task_type_key_id == TaskTypeKeyValue.task_type_key_id,
                TaskTypeKeyValue.value == str(task_params["processed_transaction_id"]),
            )
        )
        .unique()
        .scalar_one_or_none()
    )

    assert post_voucher_adjustment_task is None


def test_adjust_balance_wrong_status(
    db_session: "Session",
    reward_adjustment_task: RetryTask,
) -> None:
    reward_adjustment_task.status = RetryTaskStatuses.FAILED
    db_session.commit()

    with pytest.raises(ValueError):
        adjust_balance(reward_adjustment_task.retry_task_id)

    db_session.refresh(reward_adjustment_task)

    assert reward_adjustment_task.attempts == 0
    assert reward_adjustment_task.next_attempt_time is None
    assert reward_adjustment_task.status == RetryTaskStatuses.FAILED

    post_voucher_adjustment_task: Optional[RetryTask] = (
        db_session.execute(
            select(RetryTask).where(
                RetryTask.retry_task_id != reward_adjustment_task.retry_task_id,
                TaskTypeKey.task_type_key_id == TaskTypeKeyValue.task_type_key_id,
                TaskTypeKeyValue.value == str(reward_adjustment_task.get_params()["processed_transaction_id"]),
            )
        )
        .unique()
        .scalar_one_or_none()
    )

    assert post_voucher_adjustment_task is None


@httpretty.activate
@mock.patch("rq.Queue")
def test_adjust_balance_failed_enqueue(
    MockQueue: mock.MagicMock,
    db_session: "Session",
    reward_adjustment_task: RetryTask,
    reward_rule: RewardRule,
    adjustment_url: str,
    allocation_url: str,
) -> None:
    reward_adjustment_task.status = RetryTaskStatuses.IN_PROGRESS
    db_session.commit()
    task_params = reward_adjustment_task.get_params()

    MockQueue.side_effect = Exception("test exception")

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

    with pytest.raises(BalanceAdjustmentEnqueueException):
        adjust_balance(reward_adjustment_task.retry_task_id)

    post_voucher_adjustment_task: Optional[RetryTask] = (
        db_session.execute(
            select(RetryTask).where(
                RetryTask.retry_task_id != reward_adjustment_task.retry_task_id,
                TaskTypeKey.task_type_key_id == TaskTypeKeyValue.task_type_key_id,
                TaskTypeKeyValue.value == str(reward_adjustment_task.get_params()["processed_transaction_id"]),
            )
        )
        .unique()
        .scalar_one_or_none()
    )
    assert post_voucher_adjustment_task is not None


@httpretty.activate
@mock.patch("app.tasks.reward_adjustment.datetime")
def test__process_voucher_allocation(
    mock_datetime: mock.MagicMock,
    reward_adjustment_task: RetryTask,
    reward_rule: RewardRule,
    voucher_type_slug: str,
    allocation_url: str,
) -> None:
    task_params = reward_adjustment_task.get_params()
    mock_datetime.utcnow.return_value = fake_now
    httpretty.register_uri(
        "POST",
        allocation_url,
        body=json.dumps({}),
        status=202,
    )
    retailer_slug = task_params["retailer_slug"]
    account_holder_uuid = task_params["account_holder_uuid"]

    response_audit = _process_voucher_allocation(task_params, voucher_type_slug)

    last_request = httpretty.last_request()
    assert last_request.method == "POST"
    assert "idempotency-token" in last_request.headers
    assert last_request.url == allocation_url
    assert json.loads(last_request.body) == {
        "account_url": f"{settings.POLARIS_URL}/bpl/loyalty/{retailer_slug}/accounts/{account_holder_uuid}/rewards",
    }
    assert response_audit == {
        "request": {"url": allocation_url},
        "timestamp": fake_now.isoformat(),
        "response": {
            "status": 202,
            "body": json.dumps({}),
        },
    }


@httpretty.activate
def test__process_voucher_allocation_http_errors(
    reward_adjustment_task: RetryTask,
    allocation_url: str,
    voucher_type_slug: str,
) -> None:
    task_params = reward_adjustment_task.get_params()
    retailer_slug = task_params["retailer_slug"]
    account_holder_uuid = task_params["account_holder_uuid"]
    for status, body in [
        (401, "Unauthorized"),
        (500, "Internal Server Error"),
    ]:
        httpretty.register_uri("POST", allocation_url, body=body, status=status)

        with pytest.raises(requests.RequestException) as excinfo:
            _process_voucher_allocation(task_params, voucher_type_slug)

        assert isinstance(excinfo.value, requests.RequestException)
        assert excinfo.value.response.status_code == status

        last_request = httpretty.last_request()
        assert last_request.method == "POST"
        assert json.loads(last_request.body) == {
            "account_url": (
                f"{settings.POLARIS_URL}/bpl/loyalty/{retailer_slug}/accounts/{account_holder_uuid}/rewards"
            ),
        }


def test__voucher_is_awardable(
    db_session: "Session",
    reward_adjustment_task: RetryTask,
    reward_rule: RewardRule,
    voucher_type_slug: str,
) -> None:
    campaign_slug = reward_adjustment_task.get_params()["campaign_slug"]

    def _compare_result(result: tuple, expected_result: tuple) -> None:
        assert result[0] == expected_result[0] and result[1].voucher_type_slug == expected_result[1]

    assert reward_rule.reward_goal == 5
    _compare_result(_voucher_is_awardable(db_session, campaign_slug, 1), (False, voucher_type_slug))
    _compare_result(_voucher_is_awardable(db_session, campaign_slug, -5), (False, voucher_type_slug))
    _compare_result(_voucher_is_awardable(db_session, campaign_slug, 5), (True, voucher_type_slug))
    _compare_result(_voucher_is_awardable(db_session, campaign_slug, 10), (True, voucher_type_slug))


@httpretty.activate
def test__process_voucher_status_adjustment_ok(
    voucher_status_adjustment_retry_task: RetryTask,
    voucher_status_adjustment_expected_payload: dict,
    voucher_status_adjustment_url: str,
) -> None:

    httpretty.register_uri("PATCH", voucher_status_adjustment_url, body="OK", status=202)

    response_audit = _process_voucher_status_adjustment(voucher_status_adjustment_retry_task.get_params())

    last_request = httpretty.last_request()
    assert last_request.method == "PATCH"
    assert json.loads(last_request.body) == voucher_status_adjustment_expected_payload
    assert response_audit == {
        "timestamp": mock.ANY,
        "response": {
            "status": 202,
            "body": "OK",
        },
    }


@httpretty.activate
def test__process_voucher_status_adjustment_http_errors(
    voucher_status_adjustment_retry_task: RetryTask,
    voucher_status_adjustment_expected_payload: dict,
    voucher_status_adjustment_url: str,
) -> None:

    for status, body in [
        (401, "Unauthorized"),
        (500, "Internal Server Error"),
    ]:
        httpretty.register_uri("PATCH", voucher_status_adjustment_url, body=body, status=status)

        with pytest.raises(requests.RequestException) as excinfo:
            _process_voucher_status_adjustment(voucher_status_adjustment_retry_task.get_params())

        assert isinstance(excinfo.value, requests.RequestException)
        assert excinfo.value.response.status_code == status

        last_request = httpretty.last_request()
        assert last_request.method == "PATCH"
        assert json.loads(last_request.body) == voucher_status_adjustment_expected_payload


@mock.patch("app.tasks.voucher_status_adjustment.send_request_with_metrics")
def test__process_voucher_status_adjustment_connection_error(
    mock_send_request_with_metrics: mock.MagicMock, voucher_status_adjustment_retry_task: RetryTask
) -> None:

    mock_send_request_with_metrics.side_effect = requests.Timeout("Request timed out")

    with pytest.raises(requests.RequestException) as excinfo:
        _process_voucher_status_adjustment(voucher_status_adjustment_retry_task.get_params())

    assert isinstance(excinfo.value, requests.Timeout)
    assert excinfo.value.response is None


@httpretty.activate
def test_voucher_status_adjustment(
    db_session: "Session", voucher_status_adjustment_retry_task: RetryTask, voucher_status_adjustment_url: str
) -> None:
    voucher_status_adjustment_retry_task.status = RetryTaskStatuses.IN_PROGRESS
    db_session.commit()

    httpretty.register_uri("PATCH", voucher_status_adjustment_url, body="OK", status=202)

    voucher_status_adjustment(voucher_status_adjustment_retry_task.retry_task_id)

    db_session.refresh(voucher_status_adjustment_retry_task)

    assert voucher_status_adjustment_retry_task.attempts == 1
    assert voucher_status_adjustment_retry_task.next_attempt_time is None
    assert voucher_status_adjustment_retry_task.status == RetryTaskStatuses.SUCCESS


def test_voucher_status_adjustment_wrong_status(
    db_session: "Session", voucher_status_adjustment_retry_task: RetryTask
) -> None:
    voucher_status_adjustment_retry_task.status = RetryTaskStatuses.FAILED
    db_session.commit()

    with pytest.raises(ValueError):
        voucher_status_adjustment(voucher_status_adjustment_retry_task.retry_task_id)

    db_session.refresh(voucher_status_adjustment_retry_task)

    assert voucher_status_adjustment_retry_task.attempts == 0
    assert voucher_status_adjustment_retry_task.next_attempt_time is None
    assert voucher_status_adjustment_retry_task.status == RetryTaskStatuses.FAILED


@httpretty.activate
def test_update_campaign_balances(
    db_session: "Session", create_campaign_balances_task_type: TaskType, delete_campaign_balances_task_type: TaskType
) -> None:
    params = {"retailer_slug": "sample-retailer", "campaign_slug": "sample-campaign"}
    url = "{base_url}/bpl/loyalty/{retailer_slug}/accounts/{campaign_slug}/balances".format(
        base_url=settings.POLARIS_URL, **params
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
