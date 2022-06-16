from retry_tasks_lib.utils.asynchronous import enqueue_many_retry_tasks

from app.core.config import redis_raw
from app.db.session import AsyncSessionMaker


async def enqueue_many_tasks(retry_tasks_ids: list[int]) -> None:  # pragma: no cover
    async with AsyncSessionMaker() as db_session:
        await enqueue_many_retry_tasks(
            db_session=db_session,
            retry_tasks_ids=retry_tasks_ids,
            connection=redis_raw,
        )
