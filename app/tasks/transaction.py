import logging

from datetime import datetime
from typing import Any, Dict, List, Optional

import click
import httpx
import rq
import sentry_sdk

from sqlalchemy import update
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.attributes import flag_modified
from tenacity import retry
from tenacity.before import before_log
from tenacity.retry import retry_if_exception_type, retry_if_result
from tenacity.stop import stop_after_attempt
from tenacity.wait import wait_fixed

from app.core.config import redis, settings
from app.db.base_class import async_run_query, sync_run_query
from app.db.session import AsyncSessionMaker, SyncSessionMaker
from app.enums import RewardAdjustmentStatuses
from app.models import ProcessedTransaction, RewardAdjustment

from . import logger


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


async def enqueue_reward_adjustment_tasks(reward_adjustment_ids: List[int]) -> None:
    from app.tasks.transaction import adjust_balance

    async with AsyncSessionMaker() as db_session:

        async def _update_status_and_flush() -> None:
            (
                await db_session.execute(
                    update(RewardAdjustment)
                    .where(
                        RewardAdjustment.id.in_(reward_adjustment_ids),
                        RewardAdjustment.status == RewardAdjustmentStatuses.PENDING,
                    )
                    .values(status=RewardAdjustmentStatuses.IN_PROGRESS)
                )
            )

            await db_session.flush()

        async def _commit() -> None:
            await db_session.commit()

        async def _rollback() -> None:
            await db_session.rollback()

        try:
            q = rq.Queue(settings.REWARD_ADJUSTMENT_TASK_QUEUE, connection=redis)
            await async_run_query(_update_status_and_flush, db_session)
            try:
                q.enqueue_many(
                    [
                        rq.Queue.prepare_data(
                            adjust_balance,
                            reward_adjustment_id=reward_adjustment_id,
                            failure_ttl=60 * 60 * 24 * 7,  # 1 week
                        )
                        for reward_adjustment_id in reward_adjustment_ids
                    ]
                )
            except Exception:
                await async_run_query(_rollback, db_session)
                raise
            else:
                await async_run_query(_commit, db_session, rollback_on_exc=False)

        except Exception as ex:  # pragma: no cover
            sentry_sdk.capture_exception(ex)


def _process_adjustment(adjustment: RewardAdjustment) -> dict:
    logger.info(f"Processing callback for tx: {adjustment.processed_transaction_id}")
    timestamp = datetime.utcnow()
    response_audit: dict = {"timestamp": timestamp.isoformat()}

    resp = send_request_with_metrics(
        "POST",
        "{base_url}/bpl/loyalty/{retailer_slug}/accounts/{account_holder_uuid}/adjustments".format(
            base_url=settings.POLARIS_URL,
            retailer_slug=adjustment.processed_transaction.retailer.slug,
            account_holder_uuid=adjustment.processed_transaction.account_holder_uuid,
        ),
        json={
            "balance_change": adjustment.adjustment_amount,
            "campaign_slug": adjustment.campaign_slug,
        },
        headers={"Authorization": f"Token {settings.POLARIS_AUTH_TOKEN}"},
    )
    resp.raise_for_status()
    response_audit["response"] = {"status": resp.status_code, "body": resp.text}
    logger.info(f"Callback succeeded for tx: {adjustment.processed_transaction_id}")

    return response_audit


def adjust_balance(reward_adjustment_id: int) -> None:
    with SyncSessionMaker() as db_session:

        def _get_adjustment() -> RewardAdjustment:
            return (
                db_session.query(RewardAdjustment)
                .options(joinedload(RewardAdjustment.processed_transaction).joinedload(ProcessedTransaction.retailer))
                .filter_by(id=reward_adjustment_id)
                .one()
            )

        adjustment = sync_run_query(_get_adjustment, db_session)
        if adjustment.status != RewardAdjustmentStatuses.IN_PROGRESS:
            raise ValueError(f"Incorrect state: {adjustment.status}")

        def _increase_attempts() -> None:
            adjustment.attempts += 1
            db_session.commit()

        sync_run_query(_increase_attempts, db_session)
        response_audit = _process_adjustment(adjustment)

        def _update_adjustment() -> None:
            adjustment.response_data.append(response_audit)
            flag_modified(adjustment, "response_data")
            adjustment.status = RewardAdjustmentStatuses.SUCCESS
            adjustment.next_attempt_time = None
            db_session.commit()

        sync_run_query(_update_adjustment, db_session)


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
