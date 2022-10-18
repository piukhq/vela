# pylint: disable=too-many-arguments,no-value-for-parameter

import asyncio
import json

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from unittest import mock
from uuid import uuid4

import httpretty
import pytest
import requests

from retry_tasks_lib.db.models import RetryTask, TaskType
from retry_tasks_lib.enums import RetryTaskStatuses
from retry_tasks_lib.utils.synchronous import IncorrectRetryTaskStatusError, sync_create_task

from vela.core.config import settings
from vela.enums import CampaignStatuses
from vela.models import Campaign, ProcessedTransaction, RewardRule
from vela.tasks.campaign_balances import update_campaign_balances
from vela.tasks.pending_rewards import convert_or_delete_pending_rewards
from vela.tasks.reward_adjustment import (
    _number_of_rewards_achieved,
    _process_balance_adjustment,
    _process_reward_allocation,
    _set_param_value,
    adjust_balance,
)
from vela.tasks.reward_cancellation import _process_cancel_account_holder_rewards, cancel_account_holder_rewards
from vela.tasks.reward_status_adjustment import _process_reward_status_adjustment, reward_status_adjustment

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


fake_now = datetime.now(tz=timezone.utc)


@httpretty.activate
@mock.patch("vela.tasks.reward_adjustment.datetime")
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
        reason="Transaction 1",
        tx_datetime=task_params["transaction_datetime"],
        is_transaction=False,
    )

    last_request = httpretty.last_request()
    assert last_request.method == "POST"
    assert last_request.url == adjustment_url
    assert json.loads(last_request.body) == {
        "balance_change": task_params["adjustment_amount"],
        "campaign_slug": task_params["campaign_slug"],
        "reason": "Transaction 1",
        "transaction_datetime": task_params["transaction_datetime"].timestamp(),
        "is_transaction": False,
    }

    assert response_audit == {
        "request": {
            "body": json.dumps(
                {
                    "balance_change": 100,
                    "campaign_slug": "test-campaign",
                    "reason": "Transaction 1",
                    "transaction_datetime": task_params["transaction_datetime"].timestamp(),
                    "is_transaction": False,
                }
            ),
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
                reason="Transaction 1",
                tx_datetime=task_params["transaction_datetime"],
            )

        assert isinstance(excinfo.value, requests.RequestException)
        assert excinfo.value.response.status_code == status

        last_request = httpretty.last_request()
        assert last_request.method == "POST"
        assert json.loads(last_request.body) == {
            "balance_change": task_params["adjustment_amount"],
            "campaign_slug": task_params["campaign_slug"],
            "reason": "Transaction 1",
            "transaction_datetime": task_params["transaction_datetime"].timestamp(),
            "is_transaction": True,
        }


@mock.patch("vela.tasks.reward_adjustment.send_request_with_metrics")
def test__process_adjustment_connection_error(
    mock_send_request_with_metrics: mock.MagicMock,
    reward_adjustment_task: RetryTask,
) -> None:

    mock_send_request_with_metrics.side_effect = asyncio.TimeoutError("Request timed out")
    task_params = reward_adjustment_task.get_params()

    with pytest.raises(asyncio.TimeoutError) as excinfo:
        _process_balance_adjustment(
            retailer_slug=task_params["retailer_slug"],
            account_holder_uuid=task_params["account_holder_uuid"],
            adjustment_amount=task_params["adjustment_amount"],
            campaign_slug=task_params["campaign_slug"],
            idempotency_token=task_params["pre_allocation_token"],
            reason="Transaction 1",
            tx_datetime=task_params["transaction_datetime"],
        )

    assert isinstance(excinfo.value, asyncio.TimeoutError)
    assert not hasattr(excinfo.value, "response")


@mock.patch("vela.tasks.reward_adjustment.send_request_with_metrics")
def test__process_reward_allocation_connection_error(
    mock_send_request_with_metrics: mock.MagicMock,
    reward_adjustment_task: RetryTask,
) -> None:

    mock_send_request_with_metrics.side_effect = asyncio.TimeoutError("Request timed out")

    with pytest.raises(asyncio.TimeoutError) as excinfo:
        _process_reward_allocation(
            retailer_slug="retailer_slug",
            reward_slug="slug",
            campaign_slug="campaign-slug",
            account_holder_uuid="uuid",
            idempotency_token="token",
            count=1,
        )

    assert isinstance(excinfo.value, asyncio.TimeoutError)
    assert not hasattr(excinfo.value, "response")


@httpretty.activate
def test_adjust_balance(
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
        body=json.dumps({"new_balance": reward_rule.reward_goal, "campaign_slug": task_params["campaign_slug"]}),
        status=200,
    )
    httpretty.register_uri("POST", allocation_url, status=202)

    adjust_balance(reward_adjustment_task.retry_task_id)

    db_session.refresh(reward_adjustment_task)

    assert reward_adjustment_task.attempts == 1
    assert reward_adjustment_task.next_attempt_time is None
    assert reward_adjustment_task.status == RetryTaskStatuses.SUCCESS
    assert len(reward_adjustment_task.audit_data) == 3
    assert httpretty.latest_requests()[2].parsed_body.get("count") == 1


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
        body=json.dumps({"new_balance": reward_rule.reward_goal * 3, "campaign_slug": task_params["campaign_slug"]}),
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

    pending_allocation_body = httpretty.latest_requests()[2].parsed_body
    assert pending_allocation_body.get("count") == 3
    assert pending_allocation_body.get("total_cost_to_user") == reward_rule.reward_goal * 3


@httpretty.activate
def test_adjust_balance_pending_reward_with_trc_exceed_reward_cap(
    db_session: "Session", reward_adjustment_task: RetryTask, reward_rule: RewardRule, adjustment_url: str
) -> None:
    trc = 2

    reward_rule.allocation_window = 15
    reward_rule.reward_goal = 30
    reward_rule.reward_cap = trc

    db_session.commit()

    task_params = reward_adjustment_task.get_params()
    assert task_params["adjustment_amount"] == 100

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

    pending_allocation_body = httpretty.latest_requests()[2].parsed_body
    assert pending_allocation_body.get("count") == trc
    assert pending_allocation_body.get("total_cost_to_user") == task_params["adjustment_amount"]


@httpretty.activate
def test_adjust_balance_pending_reward_with_trc_reaches_reward_cap_with_slush(
    db_session: "Session", reward_adjustment_task: RetryTask, reward_rule: RewardRule, adjustment_url: str
) -> None:
    trc = 2

    reward_rule.allocation_window = 15
    reward_rule.reward_goal = 40
    reward_rule.reward_cap = trc

    db_session.commit()

    task_params = reward_adjustment_task.get_params()
    assert task_params["adjustment_amount"] == 100

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

    pending_allocation_body = httpretty.latest_requests()[2].parsed_body
    assert pending_allocation_body.get("count") == trc
    assert pending_allocation_body.get("total_cost_to_user") == task_params["adjustment_amount"]


@httpretty.activate
def test_adjust_balance_multiple_rewards(
    db_session: "Session",
    reward_adjustment_task: RetryTask,
    processed_transaction: ProcessedTransaction,
    reward_rule: RewardRule,
    adjustment_url: str,
    allocation_url: str,
) -> None:
    task_params = reward_adjustment_task.get_params()

    reward_rule.reward_goal = 50
    adj_amount = 100
    expected_count = adj_amount // reward_rule.reward_goal
    db_session.commit()
    assert reward_adjustment_task.get_params()["adjustment_amount"] == adj_amount

    httpretty.register_uri(
        "POST",
        adjustment_url,
        responses=[
            httpretty.core.httpretty.Response(
                method=httpretty.POST,
                body=json.dumps({"new_balance": adj_amount, "campaign_slug": task_params["campaign_slug"]}),
            ),
            httpretty.core.httpretty.Response(
                method=httpretty.POST,
                body=json.dumps({"new_balance": 0, "campaign_slug": task_params["campaign_slug"]}),
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

    adjust_balance(reward_adjustment_task.retry_task_id)
    transaction_request = list(httpretty.HTTPretty.latest_requests[1].parsed_body.values())
    reward_allocation_request = list(httpretty.HTTPretty.latest_requests[2].parsed_body.values())
    reward_request = list(httpretty.HTTPretty.latest_requests[-1].parsed_body.values())
    assert transaction_request[2] == f"Transaction {processed_transaction.transaction_id}"
    assert reward_allocation_request[0] == expected_count
    assert reward_request[2] == f"Reward goal: {reward_rule.reward_goal} Count: {expected_count}"

    db_session.refresh(reward_adjustment_task)

    assert reward_adjustment_task.attempts == 1
    assert reward_adjustment_task.next_attempt_time is None
    assert reward_adjustment_task.status == RetryTaskStatuses.SUCCESS
    assert len(reward_adjustment_task.audit_data) == 3


@mock.patch("vela.tasks.requests")
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
@mock.patch("vela.tasks.reward_adjustment._number_of_rewards_achieved")
def test_adjust_balance_fails_with_409_no_balance_for_campaign_slug(
    mock__rewards_achieved: mock.MagicMock,
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
    mock__rewards_achieved.assert_not_called()


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
@mock.patch("vela.tasks.reward_adjustment.datetime")
def test__process_reward_allocation(
    mock_datetime: mock.MagicMock,
    reward_adjustment_task: RetryTask,
    reward_rule: RewardRule,
    reward_slug: str,
    allocation_url: str,
) -> None:
    count = 2
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
        campaign_slug="campaign-slug",
        account_holder_uuid=account_holder_uuid,
        idempotency_token=str(uuid4()),
        count=count,
    )

    last_request = httpretty.last_request()
    assert last_request.method == "POST"
    assert "idempotency-token" in last_request.headers
    assert last_request.url == allocation_url

    account_url = f"{settings.POLARIS_BASE_URL}/{retailer_slug}/accounts/{account_holder_uuid}/rewards"
    assert json.loads(last_request.body) == {
        "account_url": account_url,
        "count": count,
        "campaign_slug": "campaign-slug",
    }
    assert response_audit == {
        "request": {
            "body": json.dumps({"count": count, "account_url": account_url, "campaign_slug": "campaign-slug"}),
            "url": allocation_url,
        },
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
    count = 1
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
                campaign_slug="campaign-slug",
                account_holder_uuid=account_holder_uuid,
                idempotency_token=idempotency_token,
                count=count,
            )

        assert isinstance(excinfo.value, requests.RequestException)
        assert excinfo.value.response.status_code == status

        last_request = httpretty.last_request()
        assert last_request.method == "POST"
        assert json.loads(last_request.body) == {
            "count": count,
            "account_url": (f"{settings.POLARIS_BASE_URL}/{retailer_slug}/accounts/{account_holder_uuid}/rewards"),
            "campaign_slug": "campaign-slug",
        }


def test__number_of_rewards_achieved(reward_rule: RewardRule) -> None:

    assert reward_rule.reward_goal == 5
    assert reward_rule.reward_cap is None

    for new_balance, adjustment, expected_res in [
        # (new balance, adjustment, (num of rewards achieved, cap reached))
        (1, 1, (0, False)),
        (0, 0, (0, False)),
        (5, 5, (1, False)),
        (10, 10, (2, False)),
        (13, 12, (2, False)),
        (15, 15, (3, False)),
    ]:
        assert _number_of_rewards_achieved(reward_rule, new_balance, adjustment) == expected_res


def test__number_of_rewards_achieved_with_trc(db_session: "Session", reward_rule: RewardRule) -> None:

    reward_rule.reward_cap = 2
    db_session.commit()

    assert reward_rule.reward_goal == 5
    assert reward_rule.reward_cap == 2

    for new_balance, adjustment, expected_res in [
        # (new balance, adjustment, (num of rewards achieved, cap reached))
        (1, 1, (0, False)),
        (0, 0, (0, False)),
        (5, 5, (1, False)),
        (10, 10, (2, False)),
        (12, 10, (2, False)),
        (12, 12, (2, True)),
        (15, 15, (2, True)),
    ]:
        assert _number_of_rewards_achieved(reward_rule, new_balance, adjustment) == expected_res


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


@mock.patch("vela.tasks.reward_status_adjustment.send_request_with_metrics")
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
    assert "999" == _set_param_value(db_session, reward_adjustment_task, "secondary_reward_retry_task_id", 999)
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


@httpretty.activate
def test_convert_pending_rewards_task(
    db_session: "Session", convert_or_delete_pending_rewards_task_type: TaskType
) -> None:
    params = {"retailer_slug": "sample-retailer", "campaign_slug": "sample-campaign", "issue_pending_rewards": True}
    url = "{base_url}/{retailer_slug}/accounts/{campaign_slug}/pendingrewards/issue".format(
        base_url=settings.POLARIS_BASE_URL, **params
    )

    httpretty.register_uri("POST", url, body={}, status=202)

    create_convert_pending_rewards_task = sync_create_task(
        db_session, task_type_name=convert_or_delete_pending_rewards_task_type.name, params=params
    )
    db_session.commit()

    convert_or_delete_pending_rewards(create_convert_pending_rewards_task.retry_task_id)
    create_request = httpretty.last_request()

    db_session.refresh(create_convert_pending_rewards_task)

    assert create_request.url == url
    assert create_request.method == "POST"
    assert create_convert_pending_rewards_task.status == RetryTaskStatuses.SUCCESS
    assert create_convert_pending_rewards_task.attempts == 1
    assert create_convert_pending_rewards_task.next_attempt_time is None


@httpretty.activate
def test_delete_pending_rewards_task(
    db_session: "Session", convert_or_delete_pending_rewards_task_type: TaskType
) -> None:
    task_params = {"retailer_slug": "test-retailer", "campaign_slug": "test-campaign", "issue_pending_rewards": False}
    url = "{base_url}/{retailer_slug}/accounts/{campaign_slug}/pendingrewards".format(
        base_url=settings.POLARIS_BASE_URL, **task_params
    )

    httpretty.register_uri("DELETE", url, body={}, status=202)

    create_convert_pending_rewards_task = sync_create_task(
        db_session, task_type_name=convert_or_delete_pending_rewards_task_type.name, params=task_params
    )
    db_session.commit()

    convert_or_delete_pending_rewards(create_convert_pending_rewards_task.retry_task_id)
    create_request = httpretty.last_request()

    db_session.refresh(create_convert_pending_rewards_task)

    assert create_request.url == url
    assert create_request.method == "DELETE"
    assert create_convert_pending_rewards_task.status == RetryTaskStatuses.SUCCESS
    assert create_convert_pending_rewards_task.attempts == 1
    assert create_convert_pending_rewards_task.next_attempt_time is None


@httpretty.activate
def test_reward_cancellation(
    db_session: "Session", reward_cancellation_retry_task: RetryTask, reward_cancellation_url: str
) -> None:

    httpretty.register_uri("POST", reward_cancellation_url, body="OK", status=202)

    cancel_account_holder_rewards(reward_cancellation_retry_task.retry_task_id)

    db_session.refresh(reward_cancellation_retry_task)

    assert reward_cancellation_retry_task.attempts == 1
    assert reward_cancellation_retry_task.next_attempt_time is None
    assert reward_cancellation_retry_task.status == RetryTaskStatuses.SUCCESS


@httpretty.activate
def test__process_cancel_account_holder_rewards_ok(
    reward_cancellation_retry_task: RetryTask,
    reward_cancellation_url: str,
) -> None:
    httpretty.register_uri("POST", reward_cancellation_url, body="OK", status=202)

    response_audit = _process_cancel_account_holder_rewards(reward_cancellation_retry_task.get_params())
    assert httpretty.last_request().method == "POST"
    assert response_audit == {
        "timestamp": mock.ANY,
        "response": {
            "status": 202,
            "body": "OK",
        },
    }


@httpretty.activate
def test__process_cancel_account_holder_rewards_http_errors(
    reward_cancellation_retry_task: RetryTask,
    reward_cancellation_url: str,
) -> None:

    for status, body in [
        (401, "Unauthorized"),
        (500, "Internal Server Error"),
    ]:
        httpretty.register_uri("POST", reward_cancellation_url, body=body, status=status)

        with pytest.raises(requests.RequestException) as excinfo:
            _process_cancel_account_holder_rewards(reward_cancellation_retry_task.get_params())

        assert isinstance(excinfo.value, requests.RequestException)
        assert excinfo.value.response.status_code == status

        assert httpretty.last_request().method == "POST"
