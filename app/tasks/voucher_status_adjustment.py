from datetime import datetime
from typing import TYPE_CHECKING

from retry_tasks_lib.db.models import RetryTask
from retry_tasks_lib.enums import RetryTaskStatuses
from retry_tasks_lib.utils.synchronous import retryable_task

from app.core.config import settings
from app.db.session import SyncSessionMaker

from . import logger, send_request_with_metrics
from .prometheus import tasks_run_total

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _process_voucher_status_adjustment(task_params: dict) -> dict:
    logger.info(f"Processing status adjustment for voucher_type_slug: {task_params['voucher_type_slug']}")
    timestamp = datetime.utcnow()
    response_audit: dict = {"timestamp": timestamp.isoformat()}

    resp = send_request_with_metrics(
        "PATCH",
        "{base_url}/bpl/rewards/{retailer_slug}/rewards/{voucher_type_slug}/status".format(
            base_url=settings.CARINA_URL,
            retailer_slug=task_params["retailer_slug"],
            voucher_type_slug=task_params["voucher_type_slug"],
        ),
        json={
            "status": task_params["status"],
        },
        headers={"Authorization": f"Token {settings.CARINA_AUTH_TOKEN}"},
        timeout=(3.03, 10),
    )
    resp.raise_for_status()
    response_audit["response"] = {"status": resp.status_code, "body": resp.text}
    logger.info(f"Status adjustment succeeded for voucher_type_slug: {task_params['voucher_type_slug']}")

    return response_audit


# NOTE: Inter-dependency: If this function's name or module changes, ensure that
# it is relevantly reflected in the TaskType table
@retryable_task(db_session_factory=SyncSessionMaker)
def voucher_status_adjustment(retry_task: RetryTask, db_session: "Session") -> None:
    tasks_run_total.labels(app=settings.PROJECT_NAME, task_name=settings.VOUCHER_STATUS_ADJUSTMENT_TASK_NAME).inc()
    response_audit = _process_voucher_status_adjustment(retry_task.get_params())
    retry_task.update_task(
        db_session, response_audit=response_audit, status=RetryTaskStatuses.SUCCESS, clear_next_attempt_time=True
    )
