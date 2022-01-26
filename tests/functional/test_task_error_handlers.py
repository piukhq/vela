from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from requests.exceptions import RequestException
from retry_tasks_lib.db.models import RetryTask
from retry_tasks_lib.enums import RetryTaskStatuses

from app.tasks.error_handlers import handle_adjust_balance_error

if TYPE_CHECKING:
    from pytest_mock import MockerFixture
    from sqlalchemy.orm import Session


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
