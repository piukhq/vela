import logging

from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple
from uuid import uuid4

import click
import httpx
import rq

from sqlalchemy.future import select  # type: ignore
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.attributes import flag_modified
from tenacity import retry
from tenacity.before import before_log
from tenacity.retry import retry_if_exception_type, retry_if_result
from tenacity.stop import stop_after_attempt
from tenacity.wait import wait_fixed

from app.core.config import redis, settings
from app.db.base_class import sync_run_query
from app.db.session import SyncSessionMaker
from app.enums import RewardAdjustmentStatuses
from app.models import Campaign, ProcessedTransaction, RewardAdjustment, RewardRule

from . import BalanceAdjustmentEnqueueException, logger

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _process_voucher_allocation(adjustment: RewardAdjustment, voucher_type_slug: str) -> dict:
    logger.info(f"Requesting voucher allocation for tx: {adjustment.processed_transaction_id}")
    timestamp = datetime.utcnow()
    request_url = "{base_url}/bpl/vouchers/{retailer_slug}/vouchers/{voucher_type_slug}/allocation".format(
        base_url=settings.CARINA_URL,
        retailer_slug=adjustment.processed_transaction.retailer.slug,
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
                retailer_slug=adjustment.processed_transaction.retailer.slug,
                account_holder_uuid=adjustment.processed_transaction.account_holder_uuid,
            )
        },
        headers={
            "Authorization": f"Token {settings.CARINA_AUTH_TOKEN}",
            "idempotency-token": adjustment.idempotency_token,
        },
    )
    resp.raise_for_status()
    response_audit["response"] = {"status": resp.status_code, "body": resp.text}
    logger.info("Voucher allocation request complete")
    return response_audit


def _voucher_is_awardable(
    db_session: "Session", adjustment: RewardAdjustment, new_balance: int
) -> Tuple[bool, RewardRule]:
    def _get_reward_rule() -> RewardRule:
        return (
            db_session.execute(select(RewardRule).join(Campaign).where(Campaign.slug == adjustment.campaign_slug))
            .scalars()
            .one()
        )

    reward_rule = sync_run_query(_get_reward_rule, db_session, rollback_on_exc=False)
    if goal_met := new_balance >= reward_rule.reward_goal:
        logger.info(f"Reward goal ({reward_rule.reward_goal}) met (current balance: {new_balance}).")
    return goal_met, reward_rule


def update_metrics_hook(response: httpx.Response) -> None:
    # placeholder for when we add prometheus metrics
    pass


timeout = httpx.Timeout(15.0, connect=3.03)


@retry(
    stop=stop_after_attempt(2),
    wait=wait_fixed(1),
    reraise=True,
    before=before_log(logger, logging.INFO),
    retry_error_callback=lambda retry_state: retry_state.outcome.result(),
    retry=retry_if_result(lambda resp: 501 <= resp.status_code < 600) | retry_if_exception_type(httpx.RequestError),
)
def send_request_with_metrics(
    method: str,
    url: str,
    *,
    headers: Optional[Dict[str, Any]] = None,
    json: Optional[Dict[str, Any]] = None,
) -> httpx.Response:

    with httpx.Client(event_hooks={"response": [update_metrics_hook]}) as client:
        return client.request(method, url, headers=headers, json=json, timeout=timeout)


def _process_adjustment(adjustment: RewardAdjustment) -> Tuple[int, str, dict]:
    logger.info(f"Sending balance adjustment for tx: {adjustment.processed_transaction_id}")
    timestamp = datetime.utcnow()
    request_url = "{base_url}/bpl/loyalty/{retailer_slug}/accounts/{account_holder_uuid}/adjustments".format(
        base_url=settings.POLARIS_URL,
        retailer_slug=adjustment.processed_transaction.retailer.slug,
        account_holder_uuid=adjustment.processed_transaction.account_holder_uuid,
    )
    response_audit: dict = {
        "timestamp": timestamp.isoformat(),
        "request": {"url": request_url},
    }

    resp = send_request_with_metrics(
        "POST",
        request_url,
        json={
            "balance_change": adjustment.adjustment_amount,
            "campaign_slug": adjustment.campaign_slug,
        },
        headers={
            "Authorization": f"Token {settings.POLARIS_AUTH_TOKEN}",
            "idempotency-token": adjustment.idempotency_token,
        },
    )
    resp.raise_for_status()
    response_audit["response"] = {"status": resp.status_code, "body": resp.text}
    logger.info(f"Balance adjustment call succeeded for tx: {adjustment.processed_transaction_id}")
    resp_data = resp.json()

    return resp_data["new_balance"], resp_data["campaign_slug"], response_audit


def adjust_balance_for_issued_voucher(
    db_session: "Session", current_adjustment: RewardAdjustment, reward_rule: RewardRule
) -> None:
    def _query() -> RewardAdjustment:
        adjustment = RewardAdjustment(
            processed_transaction_id=current_adjustment.processed_transaction_id,
            campaign_slug=current_adjustment.campaign_slug,
            adjustment_amount=-reward_rule.reward_goal,
            idempotency_token=str(uuid4()),
            status=RewardAdjustmentStatuses.IN_PROGRESS,
        )
        db_session.add(adjustment)
        db_session.commit()
        return adjustment

    new_adjustment = sync_run_query(_query, db_session)
    try:
        q = rq.Queue(settings.REWARD_ADJUSTMENT_TASK_QUEUE, connection=redis)
        q.enqueue(
            adjust_balance,
            kwargs={"reward_adjustment_id": new_adjustment.id},
            failure_ttl=60 * 60 * 24 * 7,  # 1 week
        )

    except Exception:
        raise BalanceAdjustmentEnqueueException(new_adjustment.id)


def adjust_balance(reward_adjustment_id: int) -> None:
    with SyncSessionMaker() as db_session:

        def _get_adjustment() -> RewardAdjustment:
            return (
                db_session.query(RewardAdjustment)
                .options(joinedload(RewardAdjustment.processed_transaction).joinedload(ProcessedTransaction.retailer))
                .filter_by(id=reward_adjustment_id)
                .one()
            )

        adjustment = sync_run_query(_get_adjustment, db_session, rollback_on_exc=False)
        if adjustment.status != RewardAdjustmentStatuses.IN_PROGRESS:
            raise ValueError(f"Incorrect state: {adjustment.status}")

        def _increase_attempts() -> None:
            adjustment.attempts += 1
            db_session.commit()

        sync_run_query(_increase_attempts, db_session)

        balance, campaign_slug, response_audit = _process_adjustment(adjustment)

        def _update_response_data(audit_data: dict) -> None:
            adjustment.response_data.append(audit_data)
            flag_modified(adjustment, "response_data")
            db_session.commit()

        sync_run_query(_update_response_data, db_session, audit_data=response_audit)

        if campaign_slug != adjustment.campaign_slug:
            raise ValueError(
                f"Adjustment campaign slug ({adjustment.campaign_slug}) does not match campaign slug returned in "
                f"adjustment response ({campaign_slug})"
            )

        voucher_awardable, reward_rule = _voucher_is_awardable(db_session, adjustment, balance)

        if voucher_awardable:
            response_audit = _process_voucher_allocation(adjustment, reward_rule.voucher_type_slug)
            sync_run_query(_update_response_data, db_session, audit_data=response_audit)
            adjust_balance_for_issued_voucher(db_session, adjustment, reward_rule)

        def _finalise_adjustment() -> None:
            adjustment.status = RewardAdjustmentStatuses.SUCCESS
            adjustment.next_attempt_time = None
            db_session.commit()

        sync_run_query(_finalise_adjustment, db_session)


@click.group()
def cli() -> None:  # pragma: no cover
    pass


@cli.command()
def worker(burst: bool = False) -> None:  # pragma: no cover
    from app.tasks.error_handlers import handle_adjust_balance_error

    # placeholder for when we implement prometheus metrics
    # registry = prometheus_client.CollectorRegistry()
    # prometheus_client.multiprocess.MultiProcessCollector(registry)
    # prometheus_client.start_http_server(9100, registry=registry)

    q = rq.Queue(settings.REWARD_ADJUSTMENT_TASK_QUEUE, connection=redis)
    worker = rq.Worker(
        queues=[q],
        connection=redis,
        log_job_description=True,
        exception_handlers=[handle_adjust_balance_error],
    )
    worker.work(burst=burst, with_scheduler=True)


if __name__ == "__main__":  # pragma: no cover
    cli()
