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


def _process_campaign_balances_update(task_type_name: str, task_params: dict) -> dict:
    if task_type_name == settings.CREATE_CAMPAIGN_BALANCES_TASK_NAME:
        action = "creation"
        method = "POST"
    elif task_type_name == settings.DELETE_CAMPAIGN_BALANCES_TASK_NAME:
        action = "deletion"
        method = "DELETE"
    else:
        raise ValueError("Invalid task type.")

    logger.info(f"Processing balance {action} for campaign: {task_params['campaign_slug']}")
    response_audit: dict = {"timestamp": datetime.now(tz=timezone.utc).isoformat()}

    resp = send_request_with_metrics(
        method,
        "{base_url}/bpl/loyalty/{retailer_slug}/accounts/{campaign_slug}/balances".format(
            base_url=settings.POLARIS_URL,
            retailer_slug=task_params["retailer_slug"],
            campaign_slug=task_params["campaign_slug"],
        ),
        headers={"Content-Type": "application/json", "Authorization": f"Token {settings.POLARIS_AUTH_TOKEN}"},
        timeout=(3.03, 10),
    )
    resp.raise_for_status()
    response_audit["response"] = {"status": resp.status_code, "body": resp.text}
    logger.info(f"Balance {action} succeeded for campaign: {task_params['campaign_slug']}")

    return response_audit


# NOTE: Inter-dependency: If this function's name or module changes, ensure that
# it is relevantly reflected in the TaskType table
@retryable_task(db_session_factory=SyncSessionMaker)
def update_campaign_balances(retry_task: RetryTask, db_session: "Session") -> None:
    tasks_run_total.labels(app=settings.PROJECT_NAME, task_name=retry_task.task_type.name).inc()
    response_audit = _process_campaign_balances_update(retry_task.task_type.name, retry_task.get_params())
    retry_task.update_task(
        db_session, response_audit=response_audit, status=RetryTaskStatuses.SUCCESS, clear_next_attempt_time=True
    )
