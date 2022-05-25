from inspect import Traceback
from unittest import mock

import pytest
import rq

from app.tasks.error_handlers import handle_adjust_balance_error, handle_retry_task_request_error


@mock.patch("app.tasks.error_handlers.logger")
@mock.patch("app.tasks.error_handlers.handle_request_exception")
def test_handle_adjust_balance_error(
    mock_handle_request_exception: mock.MagicMock, mock_logger: mock.MagicMock
) -> None:
    error = ValueError("test error logged")
    mock_handle_request_exception.side_effect = error

    with pytest.raises(ValueError):
        handle_adjust_balance_error(
            job=mock.MagicMock(spec=rq.job.Job, kwargs={"retry_task_id": 1}),
            exc_type=mock.MagicMock(),
            exc_value=mock.MagicMock(),
            traceback=mock.MagicMock(spec=Traceback),
        )

    mock_logger.exception.assert_called_once_with(
        "Unexpected error occurred while running '%s'", "handle_adjust_balance_error", exc_info=error
    )


@mock.patch("app.tasks.error_handlers.logger")
@mock.patch("app.tasks.error_handlers.handle_request_exception")
def test_handle_retry_task_request_error(
    mock_handle_request_exception: mock.MagicMock, mock_logger: mock.MagicMock
) -> None:
    error = ValueError("test error logged")
    mock_handle_request_exception.side_effect = error

    with pytest.raises(ValueError):
        handle_retry_task_request_error(
            job=mock.MagicMock(spec=rq.job.Job, kwargs={"retry_task_id": 1}),
            exc_type=mock.MagicMock(),
            exc_value=mock.MagicMock(),
            traceback=mock.MagicMock(spec=Traceback),
        )

    mock_logger.exception.assert_called_once_with(
        "Unexpected error occurred while running '%s'", "handle_retry_task_request_error", exc_info=error
    )
