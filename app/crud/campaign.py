from typing import TYPE_CHECKING

from sqlalchemy.future import select
from sqlalchemy.orm import noload, selectinload

from app.db.base_class import async_run_query
from app.models import Campaign, RetailerRewards

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession


async def get_campaigns_by_slug(
    db_session: "AsyncSession", campaign_slugs: list[str], retailer: RetailerRewards, load_rules: bool = False
) -> list[Campaign]:
    option = selectinload if load_rules else noload

    async def _query() -> list[Campaign]:
        return (
            (
                await db_session.execute(
                    select(Campaign)
                    .options(option(Campaign.earn_rules), option(Campaign.reward_rule))
                    .with_for_update()
                    .where(Campaign.slug.in_(campaign_slugs), Campaign.retailer_id == retailer.id)
                )
            )
            .scalars()
            .all()
        )

    return await async_run_query(_query, db_session, rollback_on_exc=False)
