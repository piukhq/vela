import json

from datetime import datetime
from unittest import mock

import httpretty
import httpx
import pytest

from sqlalchemy.orm import Session

from app.api.endpoints.transaction import enqueue_reward_adjustment_tasks
from app.core.config import settings
from app.enums import RewardAdjustmentStatuses
from app.models import RewardAdjustment, RewardRule
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
    reward_adjustment: RewardAdjustment,
    adjustment_url: str,
) -> None:

    mock_datetime.utcnow.return_value = fake_now
    httpretty.register_uri(
        "POST",
        adjustment_url,
        body=json.dumps({"new_balance": 100, "campaign_slug": reward_adjustment.campaign_slug}),
        status=200,
    )

    new_balance, campaign_slug, response_audit = _process_adjustment(reward_adjustment)

    last_request = httpretty.last_request()
    assert last_request.method == "POST"
    assert last_request.url == adjustment_url
    assert json.loads(last_request.body) == {
        "balance_change": reward_adjustment.adjustment_amount,
        "campaign_slug": reward_adjustment.campaign_slug,
    }
    retailer_slug = reward_adjustment.processed_transaction.retailer.slug
    account_holder_uuid = reward_adjustment.processed_transaction.account_holder_uuid
    assert response_audit == {
        "request": {
            "url": f"{settings.POLARIS_URL}/bpl/loyalty/{retailer_slug}/accounts/{account_holder_uuid}/adjustments",
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
    reward_adjustment: RewardAdjustment,
    adjustment_url: str,
) -> None:

    for status, body in [
        (401, "Unauthorized"),
        (500, "Internal Server Error"),
    ]:
        httpretty.register_uri("POST", adjustment_url, body=body, status=status)

        with pytest.raises(httpx.HTTPStatusError) as excinfo:
            _process_adjustment(reward_adjustment)

        assert isinstance(excinfo.value, httpx.HTTPStatusError)
        assert excinfo.value.response.status_code == status

        last_request = httpretty.last_request()
        assert last_request.method == "POST"
        assert json.loads(last_request.body) == {
            "balance_change": reward_adjustment.adjustment_amount,
            "campaign_slug": reward_adjustment.campaign_slug,
        }


@mock.patch("app.tasks.reward_adjustment.send_request_with_metrics")
def test__process_adjustment_connection_error(
    mock_send_request_with_metrics: mock.MagicMock,
    reward_adjustment: RewardAdjustment,
) -> None:

    mock_send_request_with_metrics.side_effect = httpx.TimeoutException("Request timed out")

    with pytest.raises(httpx.RequestError) as excinfo:
        _process_adjustment(reward_adjustment)

    assert isinstance(excinfo.value, httpx.TimeoutException)
    assert not hasattr(excinfo.value, "response")


@mock.patch("app.tasks.reward_adjustment.send_request_with_metrics")
def test__process_voucher_allocation_connection_error(
    mock_send_request_with_metrics: mock.MagicMock,
    reward_adjustment: RewardAdjustment,
) -> None:

    mock_send_request_with_metrics.side_effect = httpx.TimeoutException("Request timed out")

    with pytest.raises(httpx.RequestError) as excinfo:
        _process_voucher_allocation(reward_adjustment, "slug")

    assert isinstance(excinfo.value, httpx.TimeoutException)
    assert not hasattr(excinfo.value, "response")


@httpretty.activate
def test_adjust_balance(
    db_session: "Session",
    reward_adjustment: RewardAdjustment,
    reward_rule: RewardRule,
    adjustment_url: str,
    allocation_url: str,
) -> None:
    reward_adjustment.status = RewardAdjustmentStatuses.IN_PROGRESS  # type: ignore
    db_session.commit()

    httpretty.register_uri(
        "POST",
        adjustment_url,
        body=json.dumps({"new_balance": 100, "campaign_slug": reward_adjustment.campaign_slug}),
        status=200,
    )
    httpretty.register_uri(
        "POST",
        allocation_url,
        body=json.dumps({"account_url": "http://account-url/"}),
        status=202,
    )

    adjust_balance(reward_adjustment.id)

    db_session.refresh(reward_adjustment)

    assert reward_adjustment.attempts == 1
    assert reward_adjustment.next_attempt_time is None
    assert reward_adjustment.status == RewardAdjustmentStatuses.SUCCESS
    assert len(reward_adjustment.response_data) == 2


@httpretty.activate
def test_adjust_balance_voucher_allocation_call_fails(
    db_session: "Session",
    reward_adjustment: RewardAdjustment,
    reward_rule: RewardRule,
    adjustment_url: str,
    allocation_url: str,
) -> None:
    reward_adjustment.status = RewardAdjustmentStatuses.IN_PROGRESS  # type: ignore
    db_session.commit()

    httpretty.register_uri(
        "POST",
        adjustment_url,
        body=json.dumps({"new_balance": 100, "campaign_slug": reward_adjustment.campaign_slug}),
        status=200,
    )
    httpretty.register_uri(
        "POST",
        allocation_url,
        body=json.dumps({"account_url": "http://account-url/"}),
        status=500,
    )

    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        adjust_balance(reward_adjustment.id)
    assert isinstance(excinfo.value, httpx.HTTPStatusError)
    assert hasattr(excinfo.value, "response")

    db_session.refresh(reward_adjustment)

    assert reward_adjustment.attempts == 1
    assert reward_adjustment.status == RewardAdjustmentStatuses.IN_PROGRESS
    assert len(reward_adjustment.response_data) == 1


def test_adjust_balance_wrong_status(
    db_session: "Session",
    reward_adjustment: RewardAdjustment,
) -> None:
    reward_adjustment.status = RewardAdjustmentStatuses.FAILED  # type: ignore
    db_session.commit()

    with pytest.raises(ValueError):
        adjust_balance(reward_adjustment.id)

    db_session.refresh(reward_adjustment)

    assert reward_adjustment.attempts == 0
    assert reward_adjustment.next_attempt_time is None
    assert reward_adjustment.status == RewardAdjustmentStatuses.FAILED


@pytest.mark.asyncio
@mock.patch("rq.Queue")
async def test_enqueue_reward_adjustment_task(
    MockQueue: mock.MagicMock, reward_adjustment: RewardAdjustment, db_session: "Session"
) -> None:

    mock_queue = MockQueue.return_value

    await enqueue_reward_adjustment_tasks([reward_adjustment.id])

    MockQueue.call_args[0] == "bpl_reward_adjustments"
    mock_queue.enqueue_many.assert_called_once()
    db_session.refresh(reward_adjustment)
    assert reward_adjustment.status == RewardAdjustmentStatuses.IN_PROGRESS


@httpretty.activate
@mock.patch("app.tasks.reward_adjustment.datetime")
def test__process_voucher_allocation(
    mock_datetime: mock.MagicMock,
    db_session: "Session",
    reward_adjustment: RewardAdjustment,
    reward_rule: RewardRule,
    voucher_type_slug: str,
    allocation_url: str,
) -> None:
    mock_datetime.utcnow.return_value = fake_now
    httpretty.register_uri(
        "POST",
        allocation_url,
        body=json.dumps({}),
        status=202,
    )
    retailer_slug = reward_adjustment.processed_transaction.retailer.slug
    account_holder_uuid = reward_adjustment.processed_transaction.account_holder_uuid

    response_audit = _process_voucher_allocation(reward_adjustment, voucher_type_slug)

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
    reward_adjustment: RewardAdjustment,
    allocation_url: str,
    voucher_type_slug: str,
) -> None:

    retailer_slug = reward_adjustment.processed_transaction.retailer.slug
    account_holder_uuid = reward_adjustment.processed_transaction.account_holder_uuid
    for status, body in [
        (401, "Unauthorized"),
        (500, "Internal Server Error"),
    ]:
        httpretty.register_uri("POST", allocation_url, body=body, status=status)

        with pytest.raises(httpx.HTTPStatusError) as excinfo:
            _process_voucher_allocation(reward_adjustment, voucher_type_slug)

        assert isinstance(excinfo.value, httpx.HTTPStatusError)
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
    reward_adjustment: RewardAdjustment,
    reward_rule: RewardRule,
    voucher_type_slug: str,
) -> None:
    assert reward_rule.reward_goal == 5
    assert _voucher_is_awardable(db_session, reward_adjustment, 1) == (False, voucher_type_slug)
    assert _voucher_is_awardable(db_session, reward_adjustment, -5) == (False, voucher_type_slug)
    assert _voucher_is_awardable(db_session, reward_adjustment, 5) == (True, voucher_type_slug)
    assert _voucher_is_awardable(db_session, reward_adjustment, 10) == (True, voucher_type_slug)
