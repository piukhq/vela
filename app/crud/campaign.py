from typing import TYPE_CHECKING, Optional

from sqlalchemy.future import select  # type: ignore

from app.db.base_class import async_run_query
from app.models import Campaign, RetailerRewards

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore


async def get_campaigns_by_slug(
    db_session: "AsyncSession", campaign_slugs: list[str], retailer: RetailerRewards
) -> list[Campaign]:
    async def _query() -> Optional[Campaign]:
        return (
            (
                await db_session.execute(
                    select(Campaign)
                    .with_for_update()
                    .where(Campaign.slug.in_(campaign_slugs), Campaign.retailer_id == retailer.id)
                )
            )
            .scalars()
            .all()
        )

    return await async_run_query(_query, db_session, rollback_on_exc=False)


# async def get_active_campaign_slugs(
#     db_session: "AsyncSession", retailer: RetailerRewards, transaction_time: datetime = None
# ) -> List[str]:
#     async def _query() -> list:
#         return (
#             await db_session.execute(
#                 select(Campaign.slug, Campaign.start_date, Campaign.end_date).filter_by(
#                     retailer_id=retailer.id, status=CampaignStatuses.ACTIVE
#                 )
#             )
#         ).all()
#
#     campaign_rows = await async_run_query(_query, db_session, rollback_on_exc=False)
#
#     if transaction_time is not None:
#         valid_campaigns = [
#             slug
#             for slug, start, end in campaign_rows
#             if start <= transaction_time and (end is None or end > transaction_time)
#         ]
#
#     else:
#         valid_campaigns = [row[0] for row in campaign_rows]
#
#     if not valid_campaigns:
#         raise HttpErrors.NO_ACTIVE_CAMPAIGNS.value
#
#     return valid_campaigns
