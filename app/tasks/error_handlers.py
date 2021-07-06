from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple, Union

import httpx
import rq
import sentry_sdk

from sqlalchemy.orm.attributes import flag_modified

from app.core.config import redis, settings
from app.db.base_class import sync_run_query
from app.db.session import SyncSessionMaker
from app.enums import RewardAdjustmentStatuses
from app.models import RewardAdjustment

from . import logger
from .reward_adjustment import adjust_balance

if TYPE_CHECKING:  # pragma: no cover
    from inspect import Traceback


def requeue_adjustment(adjustment: RewardAdjustment) -> datetime:
    backoff_seconds = pow(settings.REWARD_ADJUSTMENT_BACKOFF_BASE, float(adjustment.attempts)) * 60
    q = rq.Queue(settings.REWARD_ADJUSTMENT_TASK_QUEUE, connection=redis)
    next_attempt_time = datetime.utcnow().replace(tzinfo=timezone.utc) + timedelta(seconds=backoff_seconds)
    job = q.enqueue_at(  # requires rq worker --with-scheduler
        next_attempt_time,
        adjust_balance,
        reward_adjustment_id=adjustment.id,
        failure_ttl=60 * 60 * 24 * 7,  # 1 week
    )

    logger.info(f"Requeued task for execution at {next_attempt_time.isoformat()}: {job}")
    return next_attempt_time


def handle_request_exception(
    adjustment: RewardAdjustment, request_exception: Union[httpx.RequestError, httpx.HTTPStatusError]
) -> Tuple[dict, Optional[RewardAdjustmentStatuses], Optional[datetime]]:
    status = None
    next_attempt_time = None
    response_status = None

    terminal = False
    response_audit: Dict[str, Any] = {"error": str(request_exception), "timestamp": datetime.utcnow().isoformat()}

    if isinstance(request_exception, httpx.HTTPStatusError):
        response_status = request_exception.response.status_code
        response_audit["response"] = {
            "status": response_status,
            "body": request_exception.response.text,
        }

    logger.warning(
        f"Balance adjustment attempt {adjustment.attempts} failed for tx: {adjustment.processed_transaction_id}"
    )

    if adjustment.attempts < settings.REWARD_ADJUSTMENT_MAX_RETRIES:
        if response_status is None or (500 <= response_status < 600):
            next_attempt_time = requeue_adjustment(adjustment)
            logger.info(f"Next attempt time at {next_attempt_time}")
        else:
            terminal = True
            logger.warning(f"Received unhandlable response code ({response_status}). Stopping")
    else:
        terminal = True
        logger.warning(f"No further retries. Setting status to {RewardAdjustmentStatuses.FAILED}.")
        sentry_sdk.capture_message(
            f"Balance adjustment failed (max attempts reached) for {adjustment}. Stopping... {request_exception}"
        )

    if terminal:
        status = RewardAdjustmentStatuses.FAILED  # type: ignore

    return response_audit, status, next_attempt_time


def handle_adjust_balance_error(job: rq.job.Job, exc_type: type, exc_value: Exception, traceback: "Traceback") -> None:
    response_audit = None
    next_attempt_time = None

    with SyncSessionMaker() as db_session:

        adjustment = sync_run_query(
            lambda: db_session.query(RewardAdjustment).filter_by(id=job.kwargs["reward_adjustment_id"]).first(),
            db_session,
            read_only=True,
        )

        if isinstance(exc_value, (httpx.RequestError, httpx.HTTPStatusError)):  # handle http failures specifically
            response_audit, status, next_attempt_time = handle_request_exception(adjustment, exc_value)
        else:  # otherwise report to sentry and fail the task
            status = RewardAdjustmentStatuses.FAILED  # type: ignore [assignment]
            sentry_sdk.capture_exception(exc_value)

        def _update_adjustment() -> None:
            adjustment.next_attempt_time = next_attempt_time
            flag_modified(adjustment, "next_attempt_time")

            if response_audit is not None:
                adjustment.response_data.append(response_audit)
                flag_modified(adjustment, "response_data")

            if status is not None:
                adjustment.status = status

            db_session.commit()

        sync_run_query(_update_adjustment, db_session)
