import json

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from retry_tasks_lib.db.models import RetryTask
from retry_tasks_lib.enums import RetryTaskStatuses
from retry_tasks_lib.utils.synchronous import RetryTaskAdditionalQueryData, retryable_task
from sqlalchemy.future import select

from vela.activity_utils.utils import pence_integer_to_currency_string
from vela.core.config import redis_raw, settings
from vela.db.base_class import sync_run_query
from vela.db.session import SyncSessionMaker
from vela.enums import CampaignStatuses
from vela.models import Campaign, RetailerRewards, RewardRule
from vela.tasks.prometheus.metrics import tasks_run_total
from vela.tasks.prometheus.synchronous import task_processing_time_callback_fn

from . import logger, send_request_with_metrics

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session


def _process_reward_allocation(
    *,
    retailer_slug: str,
    reward_slug: str,
    campaign_slug: str,
    account_holder_uuid: str,
    idempotency_token: str,
    count: int,
) -> dict:
    url_template = "{base_url}/{retailer_slug}/rewards/{reward_slug}/allocation"
    url_kwargs = {
        "base_url": settings.CARINA_BASE_URL,
        "retailer_slug": retailer_slug,
        "reward_slug": reward_slug,
    }
    payload = {
        "count": count,
        "account_url": "{base_url}/{retailer_slug}/accounts/{account_holder_uuid}/rewards".format(
            base_url=settings.POLARIS_BASE_URL,
            retailer_slug=retailer_slug,
            account_holder_uuid=account_holder_uuid,
        ),
        "campaign_slug": campaign_slug,
    }
    response_audit: dict = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "request": {"url": url_template.format(**url_kwargs), "body": json.dumps(payload)},
    }
    resp = send_request_with_metrics(
        "POST",
        url_template,
        url_kwargs,
        exclude_from_label_url=["retailer_slug", "reward_slug"],
        json=payload,
        headers={
            "Authorization": f"Token {settings.CARINA_API_AUTH_TOKEN}",
            "idempotency-token": idempotency_token,
        },
    )
    resp.raise_for_status()
    response_audit["response"] = {"status": resp.status_code, "body": resp.text}
    return response_audit


def _process_pending_reward_allocation(
    *,
    retailer_slug: str,
    reward_slug: str,
    account_holder_uuid: str,
    idempotency_token: str,
    reward_value: int,
    allocation_window: int,
    campaign_slug: str,
    count: int,
    tot_cost_to_user: int,
) -> dict:
    # we are storing the date as a DateTime in Polaris so we want to send a midnight utc datetime
    today = datetime.now(tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    url_template = "{base_url}/{retailer_slug}/accounts/{account_holder_uuid}/pendingrewardallocation"
    url_kwargs = {
        "base_url": settings.POLARIS_BASE_URL,
        "retailer_slug": retailer_slug,
        "account_holder_uuid": account_holder_uuid,
    }
    payload = {
        "created_date": today.timestamp(),
        "conversion_date": (today + timedelta(days=allocation_window)).timestamp(),
        "value": reward_value,
        "campaign_slug": campaign_slug,
        "reward_slug": reward_slug,
        "count": count,
        "total_cost_to_user": tot_cost_to_user,
    }
    response_audit: dict = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "request": {"url": url_template.format(**url_kwargs), "body": json.dumps(payload)},
    }
    resp = send_request_with_metrics(
        "POST",
        url_template,
        url_kwargs,
        exclude_from_label_url=["retailer_slug", "account_holder_uuid"],
        json=payload,
        headers={
            "Authorization": f"Token {settings.POLARIS_API_AUTH_TOKEN}",
            "idempotency-token": idempotency_token,
        },
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


def _number_of_rewards_achieved(reward_rule: RewardRule, new_balance: int, adjustment_amount: int) -> tuple[int, bool]:
    n_reward_achieved = new_balance // reward_rule.reward_goal
    trc_reached = False

    if reward_rule.reward_cap and (
        n_reward_achieved > reward_rule.reward_cap
        or adjustment_amount > reward_rule.reward_cap * reward_rule.reward_goal
    ):
        n_reward_achieved = reward_rule.reward_cap
        trc_reached = True

    return n_reward_achieved, trc_reached


def _process_balance_adjustment(
    *,
    retailer_slug: str,
    account_holder_uuid: str,
    adjustment_amount: int,
    campaign_slug: str,
    idempotency_token: str,
    reason: str,
    is_transaction: bool = True,
    tx_datetime: datetime | None = None,
    tx_id: str | None = None,
    loyalty_type: str,
) -> tuple[int, dict]:
    url_template = "{base_url}/{retailer_slug}/accounts/{account_holder_uuid}/adjustments"
    url_kwargs = {
        "base_url": settings.POLARIS_BASE_URL,
        "retailer_slug": retailer_slug,
        "account_holder_uuid": account_holder_uuid,
    }
    activity_metadata: dict[str, str | float] = {
        "reason": reason,
        "loyalty_type": loyalty_type,
    }
    if is_transaction and tx_datetime and tx_id:
        activity_metadata |= {
            "transaction_datetime": tx_datetime.replace(tzinfo=timezone.utc).timestamp(),
            "transaction_id": tx_id,
        }

    payload = {
        "balance_change": adjustment_amount,
        "campaign_slug": campaign_slug,
        "is_transaction": is_transaction,
        "activity_metadata": activity_metadata,
    }

    response_audit: dict = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "request": {"url": url_template.format(**url_kwargs), "body": json.dumps(payload)},
    }

    resp = send_request_with_metrics(
        "POST",
        url_template,
        url_kwargs,
        exclude_from_label_url=["retailer_slug", "account_holder_uuid"],
        json=payload,
        headers={
            "Authorization": f"Token {settings.POLARIS_API_AUTH_TOKEN}",
            "idempotency-token": idempotency_token,
        },
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
    def _query() -> str:
        key_ids_by_name = retry_task.task_type.get_key_ids_by_name()
        task_type_key_val = retry_task.get_task_type_key_values([(key_ids_by_name[param_name], param_value)])[0]
        db_session.add(task_type_key_val)
        if commit:
            db_session.commit()

        return task_type_key_val.value

    return sync_run_query(_query, db_session)


def _get_campaign(db_session: "Session", retailer_slug: str, campaign_slug: str) -> Campaign:
    campaign: Campaign = sync_run_query(
        lambda: db_session.execute(
            select(Campaign)
            .join(RetailerRewards)
            .where(RetailerRewards.slug == retailer_slug, Campaign.slug == campaign_slug)
        ).scalar_one(),
        db_session,
        rollback_on_exc=False,
    )
    return campaign


def _get_balance_adjustment_reason(
    loyalty_type: str, reward_goal: int, rewards_achieved: int, allocation_window: int
) -> str:
    reward_type = "Pending reward" if allocation_window > 0 else "Reward"
    if loyalty_type == "accumulator":
        return (
            f"{reward_type} value {pence_integer_to_currency_string(reward_goal, 'GBP', currency_sign=True)},"
            f" {rewards_achieved} issued"
        )
    formatted_value = int(reward_goal // 100)
    plural_stamps = "s" if formatted_value != 1 else ""
    return f"{reward_type} value {formatted_value} stamp{plural_stamps}, {rewards_achieved} issued"


def _process_reward_path(
    *,
    log_suffix: str,
    task_params: dict,
    campaign_slug: str,
    reward_rule: RewardRule,
    allocation_token: str,
    count: int,
    tot_cost_to_user: int,
) -> dict:
    if reward_rule.allocation_window > 0:
        logger.info("Requesting pending reward allocation %s", log_suffix)
        response_audit = _process_pending_reward_allocation(
            retailer_slug=task_params["retailer_slug"],
            reward_slug=reward_rule.reward_slug,
            account_holder_uuid=task_params["account_holder_uuid"],
            idempotency_token=allocation_token,
            reward_value=reward_rule.reward_goal,
            allocation_window=reward_rule.allocation_window,
            campaign_slug=campaign_slug,
            count=count,
            tot_cost_to_user=tot_cost_to_user,
        )
        logger.info("Pending reward allocation request complete %s", log_suffix)

    else:
        logger.info("Requesting reward allocation %s", log_suffix)
        response_audit = _process_reward_allocation(
            retailer_slug=task_params["retailer_slug"],
            reward_slug=reward_rule.reward_slug,
            campaign_slug=campaign_slug,
            account_holder_uuid=task_params["account_holder_uuid"],
            idempotency_token=allocation_token,
            count=count,
        )
        logger.info("Reward allocation request complete %s", log_suffix)

    return response_audit


def update_metrics() -> None:
    if settings.ACTIVATE_TASKS_METRICS:
        tasks_run_total.labels(app=settings.PROJECT_NAME, task_name=settings.REWARD_ADJUSTMENT_TASK_NAME).inc()


class TokenParamNames(Enum):
    PRE_ALLOCATION_TOKEN = "pre_allocation_token"  # noqa: S105
    ALLOCATION_TOKEN = "allocation_token"  # noqa: S105
    POST_ALLOCATION_TOKEN = "post_allocation_token"  # noqa: S105


# NOTE: Inter-dependency: If this function's name or module changes, ensure that
# it is relevantly reflected in the TaskType table
@retryable_task(
    db_session_factory=SyncSessionMaker,
    exclusive_constraints=[
        RetryTaskAdditionalQueryData(
            matching_val_keys=["account_holder_uuid", "campaign_slug"],
            additional_statuses=[RetryTaskStatuses.FAILED],
        )
    ],
    redis_connection=redis_raw,
    metrics_callback_fn=task_processing_time_callback_fn,
)
def adjust_balance(retry_task: RetryTask, db_session: "Session") -> None:
    update_metrics()
    task_params: dict = retry_task.get_params()
    processed_tx_id = task_params["processed_transaction_id"]
    log_suffix = f"(tx_id: {processed_tx_id}, retry_task_id: {retry_task.retry_task_id})"

    campaign = _get_campaign(db_session, task_params["retailer_slug"], task_params["campaign_slug"])
    if campaign.status in (CampaignStatuses.ENDED, CampaignStatuses.CANCELLED):
        retry_task.update_task(db_session, status=RetryTaskStatuses.CANCELLED, clear_next_attempt_time=True)
        return

    retailer_slug = task_params["retailer_slug"]
    campaign_slug = task_params["campaign_slug"]
    account_holder_uuid = task_params["account_holder_uuid"]
    reward_rule = _get_reward_rule(db_session, campaign_slug)

    adjustment_amount = task_params["adjustment_amount"]
    logger.info("Adjusting balance by %s %s", adjustment_amount, log_suffix)

    pre_allocation_token = retry_task.get_params().get(TokenParamNames.PRE_ALLOCATION_TOKEN.value) or _set_param_value(
        db_session, retry_task, TokenParamNames.PRE_ALLOCATION_TOKEN.value, str(uuid4())
    )
    reason = "Refund" if adjustment_amount < 0 else "Purchase"
    new_balance, response_audit = _process_balance_adjustment(
        account_holder_uuid=account_holder_uuid,
        retailer_slug=retailer_slug,
        campaign_slug=campaign_slug,
        adjustment_amount=adjustment_amount,
        idempotency_token=pre_allocation_token,
        reason=f"{reason} transaction id: {processed_tx_id}",
        tx_datetime=task_params["transaction_datetime"],
        tx_id=processed_tx_id,
        loyalty_type=campaign.loyalty_type.value,
    )
    logger.info("Balance adjusted - new balance: %s %s", new_balance, log_suffix)
    retry_task.update_task(db_session, response_audit=response_audit)

    rewards_achieved_n, trc_reached = _number_of_rewards_achieved(reward_rule, new_balance, adjustment_amount)

    if rewards_achieved_n > 0:
        if trc_reached:
            tot_cost_to_user = adjustment_amount
            logger.info("Transaction reward cap '%s' reached %s", reward_rule.reward_cap, log_suffix)
            post_msg = "Transaction reward cap reached, decreasing balance by original adjustment amount (%s) %s"

        else:
            tot_cost_to_user = rewards_achieved_n * reward_rule.reward_goal
            logger.info(
                "Reward goal (%d) met %d time%s %s",
                reward_rule.reward_goal,
                rewards_achieved_n,
                "s" if rewards_achieved_n > 1 else "",
                log_suffix,
            )
            post_msg = "Decreasing balance by total rewards value (%s) %s"

        allocation_token = retry_task.get_params().get(TokenParamNames.ALLOCATION_TOKEN.value) or _set_param_value(
            db_session, retry_task, TokenParamNames.ALLOCATION_TOKEN.value, str(uuid4())
        )

        response_audit = _process_reward_path(
            log_suffix=log_suffix,
            task_params=task_params,
            campaign_slug=campaign_slug,
            reward_rule=reward_rule,
            allocation_token=allocation_token,
            count=rewards_achieved_n,
            tot_cost_to_user=tot_cost_to_user,
        )
        retry_task.update_task(db_session, response_audit=response_audit)

        logger.info(post_msg, tot_cost_to_user, log_suffix)

        post_allocation_token = retry_task.get_params().get(
            TokenParamNames.POST_ALLOCATION_TOKEN.value
        ) or _set_param_value(db_session, retry_task, TokenParamNames.POST_ALLOCATION_TOKEN.value, str(uuid4()))

        reason = _get_balance_adjustment_reason(
            campaign.loyalty_type.value,
            reward_rule.reward_goal,
            rewards_achieved_n,
            campaign.reward_rule.allocation_window,
        )

        balance, response_audit = _process_balance_adjustment(
            retailer_slug=retailer_slug,
            account_holder_uuid=account_holder_uuid,
            campaign_slug=campaign_slug,
            idempotency_token=post_allocation_token,
            adjustment_amount=-tot_cost_to_user,
            reason=reason,
            is_transaction=False,
            loyalty_type=campaign.loyalty_type.value,
        )
        logger.info(f"Balance readjusted - new balance: {balance} {log_suffix}")
        retry_task.update_task(db_session, response_audit=response_audit)

    retry_task.update_task(db_session, status=RetryTaskStatuses.SUCCESS, clear_next_attempt_time=True)
