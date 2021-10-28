import json

from datetime import datetime
from typing import Optional
from unittest import mock

import httpretty
import httpx
import pytest
import requests

from pytest_mock import MockerFixture
from retry_tasks_lib.db.models import RetryTask, TaskTypeKey, TaskTypeKeyValue
from retry_tasks_lib.enums import RetryTaskStatuses
from sqlalchemy.future import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import RewardRule
from app.tasks import BalanceAdjustmentEnqueueException
from app.tasks.reward_adjustment import (
    _process_adjustment,
    _process_voucher_allocation,
    _voucher_is_awardable,
    adjust_balance,
)

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
        "account_url": f"{settings.POLARIS_URL}/bpl/loyalty/{retailer_slug}/accounts/{account_holder_uuid}/vouchers",
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
                f"{settings.POLARIS_URL}/bpl/loyalty/{retailer_slug}/accounts/{account_holder_uuid}/vouchers"
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
