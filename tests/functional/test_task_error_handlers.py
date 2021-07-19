import typing

from datetime import datetime, timedelta, timezone
from inspect import Traceback
from unittest import mock

import httpx
import pytest
import rq

from app.core.config import settings
from app.enums import RewardAdjustmentStatuses
from app.models import RewardAdjustment
from app.tasks.error_handlers import handle_adjust_balance_error
from app.tasks.reward_adjustment import adjust_balance

if typing.TYPE_CHECKING:
    from sqlalchemy.orm import Session


@pytest.fixture()
def adjustment(db_session: "Session", reward_adjustment: RewardAdjustment) -> RewardAdjustment:
    #  For correctness, as we are in the error scenario here
    reward_adjustment.status = RewardAdjustmentStatuses.IN_PROGRESS  # type: ignore
    reward_adjustment.attempts = 1
    db_session.commit()
    return reward_adjustment


@pytest.fixture(scope="function")
def fixed_now() -> typing.Generator[datetime, None, None]:
    fixed = datetime.utcnow()
    with mock.patch("app.tasks.error_handlers.datetime") as mock_datetime:
        mock_datetime.utcnow.return_value = fixed
        yield fixed


@mock.patch("rq.Queue")
def test_handle_adjust_balance_error_5xx(
    mock_queue: mock.MagicMock,
    db_session: "Session",
    adjustment: RewardAdjustment,
    adjustment_url: str,
    fixed_now: datetime,
) -> None:
    job = mock.MagicMock(spec=rq.job.Job, kwargs={"reward_adjustment_id": adjustment.id})
    traceback = mock.MagicMock(spec=Traceback)
    mock_request = mock.MagicMock(spec=httpx.Request, url=adjustment_url)
    handle_adjust_balance_error(
        job,
        type(httpx.HTTPStatusError),
        httpx.HTTPStatusError(
            message="Internal server error",
            request=mock_request,
            response=mock.MagicMock(
                spec=httpx.Response, request=mock_request, status_code=500, text="Internal server error"
            ),
        ),
        traceback,
    )
    db_session.refresh(adjustment)
    assert len(adjustment.response_data) == 1
    assert adjustment.response_data[0]["response"]["body"] == "Internal server error"
    assert adjustment.response_data[0]["response"]["status"] == 500

    mock_queue.return_value.enqueue_at.assert_called_with(
        fixed_now.replace(tzinfo=timezone.utc) + timedelta(seconds=180),
        adjust_balance,
        reward_adjustment_id=adjustment.id,
        failure_ttl=604800,
    )
    assert adjustment.status == RewardAdjustmentStatuses.IN_PROGRESS
    assert adjustment.attempts == 1
    assert adjustment.next_attempt_time == fixed_now + timedelta(seconds=180)


@mock.patch("rq.Queue")
def test_handle_adjust_balance_error_no_response(
    mock_queue: mock.MagicMock,
    db_session: "Session",
    adjustment: RewardAdjustment,
    adjustment_url: str,
    fixed_now: datetime,
) -> None:

    job = mock.MagicMock(spec=rq.job.Job, kwargs={"reward_adjustment_id": adjustment.id})
    traceback = mock.MagicMock(spec=Traceback)
    mock_request = mock.MagicMock(spec=httpx.Request, url=adjustment_url)
    handle_adjust_balance_error(
        job,
        type(httpx.TimeoutException),
        httpx.TimeoutException(
            "Request timed out",
            request=mock_request,
        ),
        traceback,
    )
    db_session.refresh(adjustment)
    assert len(adjustment.response_data) == 1
    assert adjustment.response_data[0]["error"] == "Request timed out"

    mock_queue.return_value.enqueue_at.assert_called_with(
        fixed_now.replace(tzinfo=timezone.utc) + timedelta(seconds=180),
        adjust_balance,
        reward_adjustment_id=adjustment.id,
        failure_ttl=604800,
    )
    assert adjustment.status == RewardAdjustmentStatuses.IN_PROGRESS
    assert adjustment.attempts == 1
    assert adjustment.next_attempt_time == fixed_now + timedelta(seconds=180)


@mock.patch("rq.Queue")
def test_handle_adjust_balance_error_no_further_retries(
    mock_queue: mock.MagicMock, db_session: "Session", adjustment: RewardAdjustment, adjustment_url: str
) -> None:
    adjustment.attempts = settings.REWARD_ADJUSTMENT_MAX_RETRIES
    db_session.commit()

    job = mock.MagicMock(spec=rq.job.Job, kwargs={"reward_adjustment_id": adjustment.id})
    traceback = mock.MagicMock(spec=Traceback)
    mock_request = mock.MagicMock(spec=httpx.Request, url=adjustment_url)
    handle_adjust_balance_error(
        job,
        type(httpx.HTTPStatusError),
        httpx.HTTPStatusError(
            message="Internal server error",
            request=mock_request,
            response=mock.MagicMock(
                spec=httpx.Response, request=mock_request, status_code=500, text="Internal server error"
            ),
        ),
        traceback,
    )
    db_session.refresh(adjustment)
    mock_queue.assert_not_called()
    assert adjustment.status == RewardAdjustmentStatuses.FAILED
    assert adjustment.attempts == settings.REWARD_ADJUSTMENT_MAX_RETRIES
    assert adjustment.next_attempt_time is None


@mock.patch("rq.Queue")
def test_handle_adjust_balance_error_unhandleable_response(
    mock_queue: mock.MagicMock, db_session: "Session", adjustment: RewardAdjustment, adjustment_url: str
) -> None:

    job = mock.MagicMock(spec=rq.job.Job, kwargs={"reward_adjustment_id": adjustment.id})
    traceback = mock.MagicMock(spec=Traceback)
    mock_request = mock.MagicMock(spec=httpx.Request, url=adjustment_url)
    handle_adjust_balance_error(
        job,
        type(httpx.HTTPStatusError),
        httpx.HTTPStatusError(
            message="Internal server error",
            request=mock_request,
            response=mock.MagicMock(spec=httpx.Response, request=mock_request, status_code=401, text="Unauthorized"),
        ),
        traceback,
    )
    db_session.refresh(adjustment)
    mock_queue.assert_not_called()
    assert adjustment.status == RewardAdjustmentStatuses.FAILED
    assert adjustment.next_attempt_time is None


@mock.patch("sentry_sdk.capture_exception")
def test_handle_adjust_balance_error_unhandled_exception(
    mock_sentry_capture_exception: mock.MagicMock, db_session: "Session", adjustment: RewardAdjustment
) -> None:

    job = mock.MagicMock(spec=rq.job.Job, kwargs={"reward_adjustment_id": adjustment.id})
    traceback = mock.MagicMock(spec=Traceback)
    handle_adjust_balance_error(
        job,
        type(ValueError),
        ValueError("Le Meow"),
        traceback,
    )
    db_session.refresh(adjustment)

    mock_sentry_capture_exception.assert_called_once()
    assert adjustment.status == RewardAdjustmentStatuses.FAILED
    assert adjustment.next_attempt_time is None


@mock.patch("rq.Queue")
def test_handle_adjust_balance_error_account_holder_deleted(
    mock_queue: mock.MagicMock, db_session: "Session", adjustment: RewardAdjustment, adjustment_url: str
) -> None:

    job = mock.MagicMock(spec=rq.job.Job, kwargs={"reward_adjustment_id": adjustment.id})
    traceback = mock.MagicMock(spec=Traceback)
    mock_request = mock.MagicMock(spec=httpx.Request, url=adjustment_url)
    handle_adjust_balance_error(
        job,
        type(httpx.HTTPStatusError),
        httpx.HTTPStatusError(
            message="Not Found",
            request=mock_request,
            response=mock.MagicMock(
                spec=httpx.Response,
                request=mock_request,
                status_code=404,
                text="Not Found",
                json=lambda: {
                    "display_message": "Account not found for provided credentials.",
                    "error": "NO_ACCOUNT_FOUND",
                },
            ),
        ),
        traceback,
    )
    db_session.refresh(adjustment)
    mock_queue.assert_not_called()
    assert adjustment.status == RewardAdjustmentStatuses.ACCOUNT_HOLDER_DELETED
    assert adjustment.next_attempt_time is None
