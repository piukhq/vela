from datetime import datetime, timezone
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


def _process_pending_rewards(task_params: dict) -> dict:
    logger.info(f"Processing pending rewards for conversion or deletion: {task_params['campaign_slug']}")
    response_audit: dict = {"timestamp": datetime.now(tz=timezone.utc).isoformat()}
    if task_params["issue_pending_rewards"]:
        method = "POST"
        url_suffix = "pendingrewards/issue"
        action = "Conversion"
    else:
        method = "DELETE"
        url_suffix = "pendingrewards"
        action = "Deletion"
    resp = send_request_with_metrics(
        method,
        url_template="{base_url}/{retailer_slug}/accounts/{campaign_slug}/{url_suffix}",
        url_kwargs={
            "base_url": settings.POLARIS_BASE_URL,
            "retailer_slug": task_params["retailer_slug"],
            "campaign_slug": task_params["campaign_slug"],
            "url_suffix": url_suffix,
        },
        exclude_from_label_url=["retailer_slug", "campaign_slug"],
        headers={"Authorization": f"Token {settings.POLARIS_API_AUTH_TOKEN}"},
    )
    resp.raise_for_status()
    response_audit["response"] = {"status": resp.status_code, "body": resp.text}
    logger.info(f"{action} of pending rewards succeeded: {task_params['campaign_slug']}")

    return response_audit


# NOTE: Inter-dependency: If this function's name or module changes, ensure that
# it is relevantly reflected in the TaskType table
@retryable_task(db_session_factory=SyncSessionMaker)
def convert_or_delete_pending_rewards(retry_task: RetryTask, db_session: "Session") -> None:
    if settings.ACTIVATE_TASKS_METRICS:
        tasks_run_total.labels(app=settings.PROJECT_NAME, task_name=settings.PENDING_REWARDS_TASK_NAME).inc()

    response_audit = _process_pending_rewards(retry_task.get_params())
    retry_task.update_task(
        db_session, response_audit=response_audit, status=RetryTaskStatuses.SUCCESS, clear_next_attempt_time=True
    )
