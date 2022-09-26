from typing import TYPE_CHECKING, Any, Callable

import rq

from retry_tasks_lib.utils.error_handler import handle_request_exception

from vela.core.config import redis_raw, settings
from vela.db.session import SyncSessionMaker

from . import logger

if TYPE_CHECKING:  # pragma: no cover
    from inspect import Traceback


def log_internal_exception(func: Callable) -> Any:
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except Exception as ex:
            logger.exception("Unexpected error occurred while running '%s'", func.__qualname__, exc_info=ex)
            raise

    return wrapper


# NOTE: Inter-dependency: If this function's name or module changes, ensure that
# it is relevantly reflected in the TaskType table
# pylint: disable=unused-argument
@log_internal_exception
def handle_adjust_balance_error(job: rq.job.Job, exc_type: type, exc_value: Exception, traceback: "Traceback") -> None:
    with SyncSessionMaker() as db_session:
        handle_request_exception(
            db_session=db_session,
            connection=redis_raw,
            backoff_base=settings.TASK_RETRY_BACKOFF_BASE,
            max_retries=settings.TASK_MAX_RETRIES,
            job=job,
            exc_value=exc_value,
            extra_status_codes_to_retry=[409],
        )


# NOTE: Inter-dependency: If this function's name or module changes, ensure that
# it is relevantly reflected in the TaskType table
# pylint: disable=unused-argument
@log_internal_exception
def handle_retry_task_request_error(
    job: rq.job.Job, exc_type: type, exc_value: Exception, traceback: "Traceback"
) -> None:
    with SyncSessionMaker() as db_session:
        handle_request_exception(
            db_session=db_session,
            connection=redis_raw,
            backoff_base=settings.TASK_RETRY_BACKOFF_BASE,
            max_retries=settings.TASK_MAX_RETRIES,
            job=job,
            exc_value=exc_value,
        )
