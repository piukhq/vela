from typing import TYPE_CHECKING, Optional

from sqlalchemy.future import select  # type: ignore

from app.db.base_class import async_run_query
from app.models import Campaign

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore


async def get_campaign_by_slug(db_session: "AsyncSession", campaign_slug: str) -> Campaign:
    async def _query() -> Optional[Campaign]:
        return (
            await db_session.execute(select(Campaign).with_for_update().where(Campaign.slug == campaign_slug))
        ).scalar_one_or_none()

    return await async_run_query(_query, db_session, rollback_on_exc=False)
