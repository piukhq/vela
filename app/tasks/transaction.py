from typing import List

from retry_tasks_lib.utils.asynchronous import enqueue_many_retry_tasks

from app.core.config import redis, settings
from app.db.session import AsyncSessionMaker


async def enqueue_reward_adjustment_tasks(retry_tasks_ids: List[int]) -> None:  # pragma: no cover
    from app.tasks.reward_adjustment import adjust_balance

    async with AsyncSessionMaker() as db_session:
        enqueue_many_retry_tasks(
            db_session=db_session,
            retry_tasks_ids=retry_tasks_ids,
            action=adjust_balance,
            queue=settings.REWARD_ADJUSTMENT_TASK_QUEUE,
            connection=redis,
        )
