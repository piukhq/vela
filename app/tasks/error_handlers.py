from typing import TYPE_CHECKING, Any, Callable

import rq
import sentry_sdk

from retry_tasks_lib.db.models import RetryTask
from retry_tasks_lib.enums import RetryTaskStatuses
from retry_tasks_lib.utils.error_handler import handle_request_exception
from sqlalchemy import update

from app.core.config import redis, settings
from app.db.base_class import sync_run_query
from app.db.session import SyncSessionMaker

from . import BalanceAdjustmentEnqueueException, logger

if TYPE_CHECKING:  # pragma: no cover
    from inspect import Traceback


def log_internal_exception(func: Callable) -> Any:
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except Exception as ex:
            logger.exception(ex)
            sentry_sdk.capture_exception(ex)
            raise

    return wrapper


@log_internal_exception
def handle_adjust_balance_error(job: rq.job.Job, exc_type: type, exc_value: Exception, traceback: "Traceback") -> None:

    with SyncSessionMaker() as db_session:

        if isinstance(exc_value, BalanceAdjustmentEnqueueException) and hasattr(exc_value, "retry_task_id"):
            # If the exception raised is a BalanceAdjustmentEnqueueException it means that we failed to add the
            # post issued voucher balance decrease adjustment to the queue.
            # In this case we set the status of the balance adjustment that issued the voucher to SUCCESS as it has
            # completed all its steps, and the status of the adjustment that failed to be enqueued to FAILED.
            # We can manually re add to the queue the failed adjustment from Event Horizon.

            def _update_exc_tasks() -> None:
                for retry_task_id, new_status in (
                    (job.kwargs["retry_task_id"], RetryTaskStatuses.SUCCESS),
                    (exc_value.retry_task_id, RetryTaskStatuses.FAILED),  # type: ignore [attr-defined]
                ):
                    db_session.execute(
                        update(RetryTask).where(RetryTask.retry_task_id == retry_task_id).values(status=new_status)
                    )

                db_session.commit()

            sync_run_query(_update_exc_tasks, db_session)

        else:  # pragma: no cover

            handle_request_exception(
                db_session=db_session,
                connection=redis,
                backoff_base=settings.TASK_RETRY_BACKOFF_BASE,
                max_retries=settings.TASK_MAX_RETRIES,
                job=job,
                exc_value=exc_value,
                extra_status_codes_to_retry=[409],
            )


# NOTE: Inter-dependency: If this function's name or module changes, ensure that
# it is relevantly reflected in the TaskType table
@log_internal_exception
def handle_retry_task_request_error(
    job: rq.job.Job, exc_type: type, exc_value: Exception, traceback: "Traceback"
) -> None:
    with SyncSessionMaker() as db_session:
        handle_request_exception(
            db_session=db_session,
            connection=redis,
            backoff_base=settings.TASK_RETRY_BACKOFF_BASE,
            max_retries=settings.TASK_MAX_RETRIES,
            job=job,
            exc_value=exc_value,
        )
