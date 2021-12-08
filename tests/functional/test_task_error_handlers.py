from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from requests.exceptions import RequestException
from retry_tasks_lib.db.models import RetryTask
from retry_tasks_lib.enums import RetryTaskStatuses
from rq.job import Job

from app.tasks import BalanceAdjustmentEnqueueException
from app.tasks.error_handlers import handle_adjust_balance_error

if TYPE_CHECKING:
    from pytest_mock import MockerFixture
    from sqlalchemy.orm import Session


def test_handle_adjust_balance_enqueue_error(
    db_session: "Session", reward_adjustment_task: RetryTask, mocker: "MockerFixture"
) -> None:
    second_task = RetryTask(task_type_id=reward_adjustment_task.task_type_id)
    db_session.add(second_task)
    db_session.commit()

    mock_handle_error = mocker.patch("app.tasks.error_handlers.handle_request_exception")

    fake_job = MagicMock(spec=Job, kwargs={"retry_task_id": reward_adjustment_task.retry_task_id})
    exc_value = BalanceAdjustmentEnqueueException(retry_task_id=second_task.retry_task_id)

    handle_adjust_balance_error(
        job=fake_job, exc_type=BalanceAdjustmentEnqueueException, exc_value=exc_value, traceback=MagicMock()
    )

    db_session.refresh(reward_adjustment_task)
    db_session.refresh(second_task)

    assert reward_adjustment_task.status == RetryTaskStatuses.SUCCESS
    assert second_task.status == RetryTaskStatuses.FAILED
    mock_handle_error.assert_not_called()


def test_handle_adjust_balance_requests_exception(
    db_session: "Session", reward_adjustment_task: RetryTask, mocker: "MockerFixture"
) -> None:
    reward_adjustment_task.status = RetryTaskStatuses.IN_PROGRESS  # for the sake of correctness
    db_session.commit()

    mock_handle_error = mocker.patch("app.tasks.error_handlers.handle_request_exception")

    handle_adjust_balance_error(
        job=MagicMock(), exc_type=RequestException, exc_value=RequestException(), traceback=MagicMock()
    )

    db_session.refresh(reward_adjustment_task)

    assert reward_adjustment_task.status == RetryTaskStatuses.IN_PROGRESS
    mock_handle_error.assert_called_once()
    assert mock_handle_error.call_args.kwargs.get("extra_status_codes_to_retry") == [409]
