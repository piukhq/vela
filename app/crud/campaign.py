from typing import TYPE_CHECKING, List

from retry_tasks_lib.db.models import RetryTask
from retry_tasks_lib.utils.asynchronous import async_create_task
from sqlalchemy.future import select
from sqlalchemy.orm import noload, selectinload

from app.core.config import settings
from app.db.base_class import async_run_query
from app.enums import CampaignStatuses
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


async def create_voucher_status_adjustment_tasks(
    db_session: "AsyncSession", campaign_slugs: list[str], retailer: RetailerRewards, status: CampaignStatuses
) -> List[int]:
    campaigns: list[Campaign] = await get_campaigns_by_slug(
        db_session=db_session, campaign_slugs=campaign_slugs, retailer=retailer, load_rules=True
    )

    async def _query() -> List[RetryTask]:
        adjustment_tasks = []
        for campaign in campaigns:
            adjustment_task = await async_create_task(
                db_session=db_session,
                task_type_name=settings.VOUCHER_STATUS_ADJUSTMENT_TASK_NAME,
                params={
                    "retailer_slug": retailer.slug,
                    "voucher_type_slug": campaign.reward_rule.voucher_type_slug,
                    "status": status.value,
                },
            )

            adjustment_tasks.append(adjustment_task)  # pragma: coverage bug 1012

        await db_session.commit()
        return adjustment_tasks  # pragma: coverage bug 1012

    retry_task_ids = [task.retry_task_id for task in await async_run_query(_query, db_session)]

    return retry_task_ids
