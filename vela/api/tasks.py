from retry_tasks_lib.utils.asynchronous import enqueue_many_retry_tasks

from vela.core.config import redis_raw
from vela.db.session import AsyncSessionMaker


async def enqueue_many_tasks(retry_tasks_ids: list[int], raise_exc: bool | None = False) -> None:  # pragma: no cover
    async with AsyncSessionMaker() as db_session:
        await enqueue_many_retry_tasks(
            db_session=db_session,
            retry_tasks_ids=retry_tasks_ids,
            connection=redis_raw,
            raise_exc=raise_exc,
        )
