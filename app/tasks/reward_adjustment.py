from datetime import datetime
from typing import TYPE_CHECKING, cast
from uuid import uuid4

from retry_tasks_lib.db.models import RetryTask
from retry_tasks_lib.enums import RetryTaskStatuses
from retry_tasks_lib.utils.synchronous import RetryTaskAdditionalSubqueryData, retryable_task
from sqlalchemy.future import select

from app.core.config import redis, settings
from app.db.base_class import sync_run_query
from app.db.session import SyncSessionMaker
from app.enums import CampaignStatuses
from app.models import Campaign, RetailerRewards, RewardRule

from . import logger, send_request_with_metrics
from .prometheus import tasks_run_total

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session


def _process_reward_allocation(
    *, retailer_slug: str, reward_slug: str, account_holder_uuid: str, idempotency_token: str
) -> dict:
    timestamp = datetime.utcnow()
    request_url = "{base_url}/bpl/vouchers/{retailer_slug}/rewards/{reward_slug}/allocation".format(
        base_url=settings.CARINA_URL,
        retailer_slug=retailer_slug,
        reward_slug=reward_slug,
    )
    response_audit: dict = {
        "timestamp": timestamp.isoformat(),
        "request": {"url": request_url},
    }
    resp = send_request_with_metrics(
        "POST",
        request_url,
        json={
            "account_url": "{base_url}/bpl/loyalty/{retailer_slug}/accounts/{account_holder_uuid}/rewards".format(
                base_url=settings.POLARIS_URL,
                retailer_slug=retailer_slug,
                account_holder_uuid=account_holder_uuid,
            )
        },
        headers={
            "Authorization": f"Token {settings.CARINA_AUTH_TOKEN}",
            "idempotency-token": idempotency_token,
        },
        timeout=(3.03, 10),
    )
    resp.raise_for_status()
    response_audit["response"] = {"status": resp.status_code, "body": resp.text}
    return response_audit


def _reward_achieved(db_session: "Session", campaign_slug: str, new_balance: int) -> tuple[bool, RewardRule]:
    reward_rule: RewardRule = sync_run_query(
        lambda: db_session.execute(
            select(RewardRule).where(RewardRule.campaign_id == Campaign.id, Campaign.slug == campaign_slug)
        ).scalar_one(),
        db_session,
        rollback_on_exc=False,
    )
    if goal_met := new_balance >= cast(int, reward_rule.reward_goal):
        logger.info(f"Reward goal ({reward_rule.reward_goal}) met (current balance: {new_balance}).")
    return goal_met, reward_rule


def _process_adjustment(
    *, retailer_slug: str, account_holder_uuid: str, adjustment_amount: int, campaign_slug: str, idempotency_token: str
) -> tuple[int, str, dict]:
    timestamp = datetime.utcnow()
    request_url = "{base_url}/bpl/loyalty/{retailer_slug}/accounts/{account_holder_uuid}/adjustments".format(
        base_url=settings.POLARIS_URL,
        retailer_slug=retailer_slug,
        account_holder_uuid=account_holder_uuid,
    )
    response_audit: dict = {
        "timestamp": timestamp.isoformat(),
        "request": {"url": request_url},
    }

    resp = send_request_with_metrics(
        "POST",
        request_url,
        json={
            "balance_change": adjustment_amount,
            "campaign_slug": campaign_slug,
        },
        headers={
            "Authorization": f"Token {settings.POLARIS_AUTH_TOKEN}",
            "idempotency-token": idempotency_token,
        },
        timeout=(3.03, 10),
    )
    resp.raise_for_status()
    response_audit["response"] = {"status": resp.status_code, "body": resp.text}
    resp_data = resp.json()

    return resp_data["new_balance"], resp_data["campaign_slug"], response_audit


def _create_idempotency_token(retry_task: RetryTask, param_name: str, db_session: "Session") -> str:
    key_ids_by_name = retry_task.task_type.get_key_ids_by_name()
    task_type_key_val = retry_task.get_task_type_key_values([(key_ids_by_name[param_name], str(uuid4()))])[0]
    db_session.add(task_type_key_val)
    db_session.commit()
    return task_type_key_val.value


# NOTE: Inter-dependency: If this function's name or module changes, ensure that
# it is relevantly reflected in the TaskType table
@retryable_task(
    db_session_factory=SyncSessionMaker,
    exclusive_constraints=[
        RetryTaskAdditionalSubqueryData(
            matching_val_keys=["account_holder_uuid", "campaign_slug"],
            additional_statuses=[RetryTaskStatuses.FAILED],
        )
    ],
    redis_connection=redis,
)
def adjust_balance(retry_task: RetryTask, db_session: "Session") -> None:
    tasks_run_total.labels(app=settings.PROJECT_NAME, task_name=settings.REWARD_ADJUSTMENT_TASK_NAME).inc()

    task_params: dict = retry_task.get_params()

    campaign_status: CampaignStatuses = sync_run_query(
        lambda: db_session.execute(
            select(Campaign.status)
            .join(RetailerRewards)
            .where(RetailerRewards.slug == task_params["retailer_slug"], Campaign.slug == task_params["campaign_slug"])
        ).scalar_one(),
        db_session,
        rollback_on_exc=False,
    )

    if campaign_status in (CampaignStatuses.ENDED, CampaignStatuses.CANCELLED):
        retry_task.update_task(db_session, status=RetryTaskStatuses.CANCELLED, clear_next_attempt_time=True)
        return

    logger.info(
        f"Sending balance adjustment for tx: {task_params['processed_transaction_id']} account holder: "
        f"{task_params['account_holder_uuid']}"
    )
    balance, campaign_slug, response_audit = _process_adjustment(
        retailer_slug=task_params["retailer_slug"],
        account_holder_uuid=task_params["account_holder_uuid"],
        campaign_slug=task_params["campaign_slug"],
        idempotency_token=task_params["inc_adjustment_idempotency_token"],
        adjustment_amount=int(task_params["adjustment_amount"]),
    )
    logger.info(
        f"Balance adjustment call succeeded for tx: {task_params['processed_transaction_id']}, new balance: {balance}"
    )

    retry_task.update_task(db_session, response_audit=response_audit)

    if campaign_slug != task_params["campaign_slug"]:
        raise ValueError(
            f"Adjustment campaign slug ({task_params['campaign_slug']}) does not match campaign slug returned in "
            f"adjustment response ({campaign_slug})"
        )

    reward_achieved, reward_rule = _reward_achieved(db_session, task_params["campaign_slug"], balance)

    if reward_achieved:

        token_param_name = "allocation_idempotency_token"
        allocation_idempotency_token = retry_task.get_params().get(token_param_name) or _create_idempotency_token(
            retry_task, token_param_name, db_session
        )

        logger.info(f"Requesting reward allocation for tx: {task_params['processed_transaction_id']}")
        response_audit = _process_reward_allocation(
            retailer_slug=task_params["retailer_slug"],
            reward_slug=reward_rule.reward_slug,
            account_holder_uuid=task_params["account_holder_uuid"],
            idempotency_token=allocation_idempotency_token,
        )
        logger.info("Reward allocation request complete")
        retry_task.update_task(db_session, response_audit=response_audit)

        token_param_name = "dec_adjustment_idempotency_token"
        dec_idempotency_token = retry_task.get_params().get(token_param_name) or _create_idempotency_token(
            retry_task, token_param_name, db_session
        )

        logger.info(f"tx {task_params['processed_transaction_id']} Readjusting balance...")
        balance, campaign_slug, response_audit = _process_adjustment(
            retailer_slug=task_params["retailer_slug"],
            account_holder_uuid=task_params["account_holder_uuid"],
            campaign_slug=task_params["campaign_slug"],
            idempotency_token=dec_idempotency_token,
            adjustment_amount=-int(reward_rule.reward_goal),
        )
        logger.info(f"Balance readjusted for tx: {task_params['processed_transaction_id']}. New balance: {balance}")
        retry_task.update_task(db_session, response_audit=response_audit)

    retry_task.update_task(db_session, status=RetryTaskStatuses.SUCCESS, clear_next_attempt_time=True)
