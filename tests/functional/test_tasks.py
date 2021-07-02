import json

from datetime import datetime
from unittest import mock

import httpretty
import httpx
import pytest

from sqlalchemy.orm import Session

from app.enums import RewardAdjustmentStatuses
from app.models import RewardAdjustment
from app.tasks.transaction import _process_adjustment, adjust_balance

fake_now = datetime.utcnow()


@httpretty.activate
@mock.patch("app.tasks.transaction.datetime")
def test__process_callback_ok(
    mock_datetime: mock.Mock,
    reward_adjustment: RewardAdjustment,
    adjustment_url: str,
) -> None:

    mock_datetime.utcnow.return_value = fake_now
    httpretty.register_uri("POST", adjustment_url, body="OK", status=200)

    response_audit = _process_adjustment(reward_adjustment)

    last_request = httpretty.last_request()
    assert last_request.method == "POST"
    assert last_request.url == adjustment_url
    assert json.loads(last_request.body) == {
        "balance_change": reward_adjustment.adjustment_amount,
        "campaign_slug": reward_adjustment.campaign_slug,
    }
    assert response_audit == {
        "timestamp": fake_now.isoformat(),
        "response": {
            "status": 200,
            "body": "OK",
        },
    }


@httpretty.activate
def test__process_callback_http_errors(
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


@mock.patch("app.tasks.transaction.send_request_with_metrics")
def test__process_callback_connection_error(
    mock_send_request_with_metrics: mock.MagicMock,
    reward_adjustment: RewardAdjustment,
) -> None:

    mock_send_request_with_metrics.side_effect = httpx.TimeoutException("Request timed out")

    with pytest.raises(httpx.RequestError) as excinfo:
        _process_adjustment(reward_adjustment)

    assert isinstance(excinfo.value, httpx.TimeoutException)
    assert not hasattr(excinfo.value, "response")


@httpretty.activate
def test_activate_account_holder(
    db_session: "Session",
    reward_adjustment: RewardAdjustment,
    adjustment_url: str,
) -> None:
    reward_adjustment.status = RewardAdjustmentStatuses.IN_PROGRESS  # type: ignore
    db_session.commit()

    httpretty.register_uri("POST", adjustment_url, body="OK", status=200)

    adjust_balance(reward_adjustment.id)

    db_session.refresh(reward_adjustment)

    assert reward_adjustment.attempts == 1
    assert reward_adjustment.next_attempt_time is None
    assert reward_adjustment.status == RewardAdjustmentStatuses.SUCCESS


def test_activate_account_holder_wrong_status(
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
