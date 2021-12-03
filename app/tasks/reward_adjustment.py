from datetime import datetime
from typing import TYPE_CHECKING, cast
from uuid import uuid4

from retry_tasks_lib.db.models import RetryTask
from retry_tasks_lib.enums import RetryTaskStatuses
from retry_tasks_lib.utils.synchronous import enqueue_retry_task, get_retry_task, sync_create_task
from sqlalchemy.future import select

from app.core.config import redis, settings
from app.db.base_class import sync_run_query
from app.db.session import SyncSessionMaker
from app.enums import CampaignStatuses
from app.models import Campaign, RetailerRewards, RewardRule

from . import BalanceAdjustmentEnqueueException, logger, send_request_with_metrics
from .prometheus import tasks_run_total

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session


def _process_voucher_allocation(task_params: dict, voucher_type_slug: str) -> dict:
    logger.info(f"Requesting voucher allocation for tx: {task_params['processed_transaction_id']}")
    timestamp = datetime.utcnow()
    request_url = "{base_url}/bpl/vouchers/{retailer_slug}/vouchers/{voucher_type_slug}/allocation".format(
        base_url=settings.CARINA_URL,
        retailer_slug=task_params["retailer_slug"],
        voucher_type_slug=voucher_type_slug,
    )
    response_audit: dict = {
        "timestamp": timestamp.isoformat(),
        "request": {"url": request_url},
    }
    resp = send_request_with_metrics(
        "POST",
        request_url,
        json={
            "account_url": "{base_url}/bpl/loyalty/{retailer_slug}/accounts/{account_holder_uuid}/vouchers".format(
                base_url=settings.POLARIS_URL,
                retailer_slug=task_params["retailer_slug"],
                account_holder_uuid=task_params["account_holder_uuid"],
            )
        },
        headers={
            "Authorization": f"Token {settings.CARINA_AUTH_TOKEN}",
            "idempotency-token": task_params["idempotency_token"],
        },
        timeout=(3.03, 10),
    )
    resp.raise_for_status()
    response_audit["response"] = {"status": resp.status_code, "body": resp.text}
    logger.info("Voucher allocation request complete")
    return response_audit


def _voucher_is_awardable(db_session: "Session", campaign_slug: str, new_balance: int) -> tuple[bool, RewardRule]:
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


def _process_adjustment(task_params: dict) -> tuple[int, str, dict]:
    logger.info(f"Sending balance adjustment for tx: {task_params['processed_transaction_id']}")
    timestamp = datetime.utcnow()
    request_url = "{base_url}/bpl/loyalty/{retailer_slug}/accounts/{account_holder_uuid}/adjustments".format(
        base_url=settings.POLARIS_URL,
        retailer_slug=task_params["retailer_slug"],
        account_holder_uuid=task_params["account_holder_uuid"],
    )
    response_audit: dict = {
        "timestamp": timestamp.isoformat(),
        "request": {"url": request_url},
    }

    resp = send_request_with_metrics(
        "POST",
        request_url,
        json={
            "balance_change": task_params["adjustment_amount"],
            "campaign_slug": task_params["campaign_slug"],
        },
        headers={
            "Authorization": f"Token {settings.POLARIS_AUTH_TOKEN}",
            "idempotency-token": task_params["idempotency_token"],
        },
        timeout=(3.03, 10),
    )
    resp.raise_for_status()
    response_audit["response"] = {"status": resp.status_code, "body": resp.text}
    logger.info(f"Balance adjustment call succeeded for tx: {task_params['processed_transaction_id']}")
    resp_data = resp.json()

    return resp_data["new_balance"], resp_data["campaign_slug"], response_audit


def adjust_balance_for_issued_voucher(db_session: "Session", task_params: dict, reward_rule: RewardRule) -> None:

    retry_task = sync_create_task(
        db_session,
        task_type_name=settings.REWARD_ADJUSTMENT_TASK_NAME,
        params={
            "account_holder_uuid": task_params["account_holder_uuid"],
            "retailer_slug": task_params["retailer_slug"],
            "processed_transaction_id": task_params["processed_transaction_id"],
            "campaign_slug": task_params["campaign_slug"],
            "adjustment_amount": -reward_rule.reward_goal,
            "idempotency_token": uuid4(),
        },
    )
    retry_task.status = RetryTaskStatuses.IN_PROGRESS
    db_session.commit()

    try:
        enqueue_retry_task(connection=redis, retry_task=retry_task)

    except Exception:
        raise BalanceAdjustmentEnqueueException(retry_task.retry_task_id)


def adjust_balance(retry_task_id: int) -> None:
    tasks_run_total.labels(app=settings.PROJECT_NAME, task_name=settings.REWARD_ADJUSTMENT_TASK_NAME).inc()
    with SyncSessionMaker() as db_session:

        retry_task: RetryTask = get_retry_task(db_session, retry_task_id)
        task_params: dict = retry_task.get_params()
        retry_task.update_task(db_session, increase_attempts=True)

        campaign_status: CampaignStatuses = sync_run_query(
            lambda: db_session.execute(
                select(Campaign.status)
                .join(RetailerRewards)
                .where(
                    RetailerRewards.slug == task_params["retailer_slug"], Campaign.slug == task_params["campaign_slug"]
                )
            ).scalar_one(),
            db_session,
            rollback_on_exc=False,
        )

        if campaign_status in (CampaignStatuses.ENDED, CampaignStatuses.CANCELLED):
            retry_task.update_task(db_session, status=RetryTaskStatuses.CANCELLED, clear_next_attempt_time=True)
            return

        balance, campaign_slug, response_audit = _process_adjustment(task_params)

        retry_task.update_task(db_session, response_audit=response_audit)

        if campaign_slug != task_params["campaign_slug"]:  # pragma: coverage bug 1012
            raise ValueError(
                f"Adjustment campaign slug ({task_params['campaign_slug']}) does not match campaign slug returned in "
                f"adjustment response ({campaign_slug})"
            )

        voucher_awardable, reward_rule = _voucher_is_awardable(db_session, task_params["campaign_slug"], balance)

        if voucher_awardable:  # pragma: coverage bug 1012
            response_audit = _process_voucher_allocation(task_params, reward_rule.voucher_type_slug)
            retry_task.update_task(db_session, response_audit=response_audit)
            adjust_balance_for_issued_voucher(db_session, task_params, reward_rule)

        retry_task.update_task(db_session, status=RetryTaskStatuses.SUCCESS, clear_next_attempt_time=True)
