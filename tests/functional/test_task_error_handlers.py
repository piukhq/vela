from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from retry_tasks_lib.db.models import RetryTask
from retry_tasks_lib.enums import RetryTaskStatuses
from rq.job import Job

from app.tasks import BalanceAdjustmentEnqueueException
from app.tasks.error_handlers import handle_adjust_balance_error

if TYPE_CHECKING:
    from pytest_mock import MockerFixture
    from sqlalchemy.orm import Session


def test_handle_adjust_balance_error(
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
