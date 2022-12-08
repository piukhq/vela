from datetime import datetime, timezone
from typing import TYPE_CHECKING

from retry_tasks_lib.db.models import RetryTask
from retry_tasks_lib.enums import RetryTaskStatuses
from retry_tasks_lib.utils.synchronous import retryable_task

from vela.core.config import settings
from vela.db.session import SyncSessionMaker
from vela.tasks.prometheus.metrics import tasks_run_total
from vela.tasks.prometheus.synchronous import task_processing_time_callback_fn

from . import logger, send_request_with_metrics

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _process_cancel_account_holder_rewards(task_params: dict) -> dict:
    logger.info(f"Processing account holder reward cancellation for campaign: {task_params['campaign_slug']}")
    response_audit: dict = {"timestamp": datetime.now(tz=timezone.utc).isoformat()}

    resp = send_request_with_metrics(
        "POST",
        url_template="{base_url}/{retailer_slug}/rewards/{campaign_slug}/cancel",
        url_kwargs={
            "base_url": settings.POLARIS_BASE_URL,
            "retailer_slug": task_params["retailer_slug"],
            "campaign_slug": task_params["campaign_slug"],
        },
        exclude_from_label_url=["retailer_slug", "campaign_slug"],
        json={"activity_metadata": {"cancel_datetime": task_params["cancel_datetime"].timestamp()}},
        headers={"Authorization": f"Token {settings.POLARIS_API_AUTH_TOKEN}"},
    )
    resp.raise_for_status()
    response_audit["response"] = {"status": resp.status_code, "body": resp.text}
    logger.info(f"Account Holder reward cancellation succeeded for campaign: {task_params['campaign_slug']}")

    return response_audit


# NOTE: Inter-dependency: If this function's name or module changes, ensure that
# it is relevantly reflected in the TaskType table
@retryable_task(db_session_factory=SyncSessionMaker, metrics_callback_fn=task_processing_time_callback_fn)
def cancel_account_holder_rewards(retry_task: RetryTask, db_session: "Session") -> None:
    if settings.ACTIVATE_TASKS_METRICS:
        tasks_run_total.labels(app=settings.PROJECT_NAME, task_name=settings.REWARD_CANCELLATION_TASK_NAME).inc()

    response_audit = _process_cancel_account_holder_rewards(retry_task.get_params())
    retry_task.update_task(
        db_session, response_audit=response_audit, status=RetryTaskStatuses.SUCCESS, clear_next_attempt_time=True
    )
