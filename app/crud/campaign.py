from typing import TYPE_CHECKING, List

from sqlalchemy.future import select  # type: ignore

from app.db.base_class import async_run_query
from app.models import Campaign

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore


async def get_campaigns_by_slug(db_session: "AsyncSession", campaign_slugs: list[str]) -> list[Campaign]:
    async def _query() -> List[Campaign]:
        return (
            (await db_session.execute(select(Campaign).with_for_update().where(Campaign.slug.in_(campaign_slugs))))
            .scalars()
            .all()
        )

    return await async_run_query(_query, db_session, rollback_on_exc=False)
