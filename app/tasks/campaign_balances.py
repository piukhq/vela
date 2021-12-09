from datetime import datetime

from retry_tasks_lib.enums import RetryTaskStatuses
from retry_tasks_lib.utils.synchronous import get_retry_task

from app.core.config import settings
from app.db.session import SyncSessionMaker

from . import logger, send_request_with_metrics


def _process_campaign_balances_update(task_type_name: str, task_params: dict) -> dict:
    if task_type_name == settings.CREATE_CAMPAIGN_BALANCES_TASK_NAME:
        action = "creation"
        method = "POST"
    elif task_type_name == settings.DELETE_CAMPAIGN_BALANCES_TASK_NAME:
        action = "deletion"
        method = "DELETE"
    else:
        raise ValueError("Invalid task type.")  # pragma: coverage bug 1012

    logger.info(f"Processing balance {action} for campaign: {task_params['campaign_slug']}")
    timestamp = datetime.utcnow()
    response_audit: dict = {"timestamp": timestamp.isoformat()}

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
def update_campaign_balances(retry_task_id: int) -> None:
    with SyncSessionMaker() as db_session:

        retry_task = get_retry_task(db_session, retry_task_id)
        retry_task.update_task(db_session, increase_attempts=True)

        response_audit = _process_campaign_balances_update(retry_task.task_type.name, retry_task.get_params())

        retry_task.update_task(
            db_session, response_audit=response_audit, status=RetryTaskStatuses.SUCCESS, clear_next_attempt_time=True
        )
