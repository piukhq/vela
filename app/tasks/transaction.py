from typing import List

import rq
import sentry_sdk

from sqlalchemy import update

from app.core.config import redis, settings
from app.db.base_class import async_run_query
from app.db.session import AsyncSessionMaker
from app.enums import RewardAdjustmentStatuses
from app.models import RewardAdjustment


async def enqueue_reward_adjustment_tasks(reward_adjustment_ids: List[int]) -> None:
    from app.tasks.reward_adjustment import adjust_balance

    async with AsyncSessionMaker() as db_session:

        async def _update_status_and_flush() -> None:
            (
                await db_session.execute(
                    update(RewardAdjustment)  # type: ignore
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
                            kwargs={"reward_adjustment_id": reward_adjustment_id},
                            failure_ttl=60 * 60 * 24 * 7,  # 1 week
                        )
                        for reward_adjustment_id in reward_adjustment_ids
                    ]
                )
            except Exception as ex:
                await async_run_query(_rollback, db_session)
                raise
            else:
                await async_run_query(_commit, db_session, rollback_on_exc=False)

        except Exception as ex:  # pragma: no cover
            sentry_sdk.capture_exception(ex)
