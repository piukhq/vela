import json

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from retry_tasks_lib.db.models import RetryTask
from retry_tasks_lib.enums import RetryTaskStatuses
from retry_tasks_lib.utils.synchronous import (
    RetryTaskAdditionalSubqueryData,
    enqueue_retry_task,
    get_retry_task,
    retryable_task,
    sync_create_task,
)
from rq.job import Job
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
    request_url = "{base_url}/bpl/vouchers/{retailer_slug}/rewards/{reward_slug}/allocation".format(
        base_url=settings.CARINA_URL,
        retailer_slug=retailer_slug,
        reward_slug=reward_slug,
    )
    payload = {
        "account_url": "{base_url}/bpl/loyalty/{retailer_slug}/accounts/{account_holder_uuid}/rewards".format(
            base_url=settings.POLARIS_URL,
            retailer_slug=retailer_slug,
            account_holder_uuid=account_holder_uuid,
        )
    }
    response_audit: dict = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "request": {"url": request_url, "body": json.dumps(payload)},
    }
    resp = send_request_with_metrics(
        "POST",
        request_url,
        json=payload,
        headers={
            "Authorization": f"Token {settings.CARINA_API_AUTH_TOKEN}",
            "idempotency-token": idempotency_token,
        },
        timeout=(3.03, 10),
    )
    resp.raise_for_status()
    response_audit["response"] = {"status": resp.status_code, "body": resp.text}
    return response_audit


def _get_reward_rule(db_session: "Session", campaign_slug: str) -> RewardRule:
    reward_rule: RewardRule = sync_run_query(
        lambda: db_session.execute(
            select(RewardRule).where(RewardRule.campaign_id == Campaign.id, Campaign.slug == campaign_slug)
        ).scalar_one(),
        db_session,
        rollback_on_exc=False,
    )
    return reward_rule


def _reward_achieved(reward_rule: RewardRule, new_balance: int) -> bool:
    return new_balance >= reward_rule.reward_goal


def _process_balance_adjustment(
    *,
    retailer_slug: str,
    account_holder_uuid: str,
    adjustment_amount: int,
    campaign_slug: str,
    idempotency_token: str,
) -> tuple[int, dict]:
    request_url = "{base_url}/bpl/loyalty/{retailer_slug}/accounts/{account_holder_uuid}/adjustments".format(
        base_url=settings.POLARIS_URL,
        retailer_slug=retailer_slug,
        account_holder_uuid=account_holder_uuid,
    )
    payload = {
        "balance_change": adjustment_amount,
        "campaign_slug": campaign_slug,
    }

    response_audit: dict = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "request": {"url": request_url, "body": json.dumps(payload)},
    }

    resp = send_request_with_metrics(
        "POST",
        request_url,
        json=payload,
        headers={
            "Authorization": f"Token {settings.POLARIS_API_AUTH_TOKEN}",
            "idempotency-token": idempotency_token,
        },
        timeout=(3.03, 10),
    )
    resp.raise_for_status()
    response_audit["response"] = {"status": resp.status_code, "body": resp.text}
    resp_data = resp.json()

    if resp_data["campaign_slug"] != campaign_slug:
        raise ValueError(
            f"Adjustment campaign slug ({campaign_slug}) does not match campaign slug returned in "
            f"adjustment response ({resp_data['campaign_slug']})"
        )
    return resp_data["new_balance"], response_audit


def _set_param_value(
    db_session: "Session", retry_task: RetryTask, param_name: str, param_value: Any, commit: bool = True
) -> str:
    key_ids_by_name = retry_task.task_type.get_key_ids_by_name()
    task_type_key_val = retry_task.get_task_type_key_values([(key_ids_by_name[param_name], param_value)])[0]
    db_session.add(task_type_key_val)
    if commit:
        db_session.commit()
    return task_type_key_val.value


def _get_campaign_status(db_session: "Session", retailer_slug: str, campaign_slug: str) -> CampaignStatuses:
    campaign_status: CampaignStatuses = sync_run_query(
        lambda: db_session.execute(
            select(Campaign.status)
            .join(RetailerRewards)
            .where(RetailerRewards.slug == retailer_slug, Campaign.slug == campaign_slug)
        ).scalar_one(),
        db_session,
        rollback_on_exc=False,
    )
    return campaign_status


def _enqueue_secondary_reward_only_task(db_session: "Session", retry_task: RetryTask) -> tuple[RetryTask, Job]:
    task_params = retry_task.get_params()
    if secondary_task_id := task_params.get("secondary_reward_retry_task_id"):
        secondary_reward_task = get_retry_task(db_session, secondary_task_id)
    else:
        secondary_reward_task = sync_create_task(
            db_session,
            task_type_name=settings.REWARD_ADJUSTMENT_TASK_NAME,
            params={
                "processed_transaction_id": task_params["processed_transaction_id"],
                "account_holder_uuid": task_params["account_holder_uuid"],
                "retailer_slug": task_params["retailer_slug"],
                "campaign_slug": task_params["campaign_slug"],
                "reward_only": True,
            },
        )
        # To allow this to be re-runnable
        _set_param_value(
            db_session,
            retry_task,
            "secondary_reward_retry_task_id",
            secondary_reward_task.retry_task_id,
            commit=False,
        )
        db_session.commit()

    rq_job = enqueue_retry_task(connection=redis, retry_task=secondary_reward_task, at_front=True)
    return secondary_reward_task, rq_job


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
    processed_tx_id = task_params["processed_transaction_id"]
    log_suffix = f" (tx_id: {processed_tx_id}, retry_task_id: {retry_task.retry_task_id})"

    campaign_status = _get_campaign_status(db_session, task_params["retailer_slug"], task_params["campaign_slug"])
    if campaign_status in (CampaignStatuses.ENDED, CampaignStatuses.CANCELLED):
        retry_task.update_task(db_session, status=RetryTaskStatuses.CANCELLED, clear_next_attempt_time=True)
        return

    retailer_slug = task_params["retailer_slug"]
    campaign_slug = task_params["campaign_slug"]
    account_holder_uuid = task_params["account_holder_uuid"]
    reward_rule = _get_reward_rule(db_session, campaign_slug)
    reward_achieved = False
    reward_only = task_params.get("reward_only", False)

    if not reward_only:
        adjustment_amount = task_params["adjustment_amount"]
        logger.info(f"Adjusting balance by {adjustment_amount}" + log_suffix)
        token_param_name = "pre_allocation_token"
        pre_allocation_token = retry_task.get_params().get(token_param_name) or _set_param_value(
            db_session, retry_task, token_param_name, str(uuid4())
        )
        new_balance, response_audit = _process_balance_adjustment(
            account_holder_uuid=account_holder_uuid,
            retailer_slug=retailer_slug,
            campaign_slug=campaign_slug,
            adjustment_amount=adjustment_amount,
            idempotency_token=pre_allocation_token,
        )
        logger.info(f"Balance adjusted - new balance: {new_balance}" + log_suffix)
        retry_task.update_task(db_session, response_audit=response_audit)

        reward_achieved = _reward_achieved(reward_rule, new_balance)

    if reward_achieved or reward_only:
        logger.info((f"Reward goal ({reward_rule.reward_goal}) met" if reward_achieved else "Reward only") + log_suffix)

        token_param_name = "allocation_token"
        allocation_token = retry_task.get_params().get(token_param_name) or _set_param_value(
            db_session, retry_task, token_param_name, str(uuid4())
        )

        logger.info("Requesting reward allocation" + log_suffix)
        response_audit = _process_reward_allocation(
            retailer_slug=task_params["retailer_slug"],
            reward_slug=reward_rule.reward_slug,
            account_holder_uuid=task_params["account_holder_uuid"],
            idempotency_token=allocation_token,
        )
        logger.info("Reward allocation request complete" + log_suffix)
        retry_task.update_task(db_session, response_audit=response_audit)

        logger.info(f"Decreasing balance by reward goal ({reward_rule.reward_goal})" + log_suffix)
        token_param_name = "post_allocation_token"
        post_allocation_token = retry_task.get_params().get(token_param_name) or _set_param_value(
            db_session, retry_task, token_param_name, str(uuid4())
        )
        balance, response_audit = _process_balance_adjustment(
            retailer_slug=retailer_slug,
            account_holder_uuid=account_holder_uuid,
            campaign_slug=campaign_slug,
            idempotency_token=post_allocation_token,
            adjustment_amount=-int(reward_rule.reward_goal),
        )
        logger.info(f"Balance readjusted - new balance: {balance}" + log_suffix)
        retry_task.update_task(db_session, response_audit=response_audit)

        secondary_reward_achieved = _reward_achieved(reward_rule, balance)

        if secondary_reward_achieved:
            logger.info("Further reward allocation required" + log_suffix)
            secondary_task, rq_job = _enqueue_secondary_reward_only_task(db_session, retry_task)
            logger.info(
                f"Secondary task (retry_task_id: {secondary_task.retry_task_id}, job_id: {rq_job.id}) queued"
                + log_suffix
            )

    retry_task.update_task(db_session, status=RetryTaskStatuses.SUCCESS, clear_next_attempt_time=True)
