from typing import List

from retry_tasks_lib.utils.asynchronous import enqueue_many_retry_tasks

from app.core.config import redis
from app.db.session import AsyncSessionMaker


async def enqueue_reward_adjustment_tasks(retry_tasks_ids: List[int]) -> None:  # pragma: no cover

    async with AsyncSessionMaker() as db_session:
        enqueue_many_retry_tasks(db_session=db_session, retry_tasks_ids=retry_tasks_ids, connection=redis)
