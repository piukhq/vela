from datetime import datetime, timezone
from typing import TYPE_CHECKING

from retry_tasks_lib.db.models import RetryTask
from retry_tasks_lib.enums import RetryTaskStatuses
from retry_tasks_lib.utils.synchronous import retryable_task

from vela.core.config import redis_raw, settings
from vela.db.session import SyncSessionMaker
from vela.tasks.prometheus.metrics import tasks_run_total
from vela.tasks.prometheus.synchronous import task_processing_time_callback_fn

from . import logger, send_request_with_metrics

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
        url_template="{base_url}/{retailer_slug}/accounts/{campaign_slug}/balances",
        url_kwargs={
            "base_url": settings.POLARIS_BASE_URL,
            "retailer_slug": task_params["retailer_slug"],
            "campaign_slug": task_params["campaign_slug"],
        },
        exclude_from_label_url=["retailer_slug", "campaign_slug"],
        headers={"Content-Type": "application/json", "Authorization": f"Token {settings.POLARIS_API_AUTH_TOKEN}"},
    )
    resp.raise_for_status()
    response_audit["response"] = {"status": resp.status_code, "body": resp.text}
    logger.info(f"Balance {action} succeeded for campaign: {task_params['campaign_slug']}")

    return response_audit


# NOTE: Inter-dependency: If this function's name or module changes, ensure that
# it is relevantly reflected in the TaskType table
@retryable_task(
    db_session_factory=SyncSessionMaker,
    redis_connection=redis_raw,
    metrics_callback_fn=task_processing_time_callback_fn,
)
def update_campaign_balances(retry_task: RetryTask, db_session: "Session") -> None:
    if settings.ACTIVATE_TASKS_METRICS:
        tasks_run_total.labels(app=settings.PROJECT_NAME, task_name=retry_task.task_type.name).inc()

    response_audit = _process_campaign_balances_update(retry_task.task_type.name, retry_task.get_params())
    retry_task.update_task(
        db_session, response_audit=response_audit, status=RetryTaskStatuses.SUCCESS, clear_next_attempt_time=True
    )
