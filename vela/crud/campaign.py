from typing import TYPE_CHECKING, Optional

from retry_tasks_lib.db.models import RetryTask
from retry_tasks_lib.utils.asynchronous import async_create_task
from sqlalchemy.future import select
from sqlalchemy.orm import noload, selectinload

from vela.core.config import settings
from vela.db.base_class import async_run_query
from vela.enums import CampaignStatuses
from vela.models import Campaign, RetailerRewards

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


async def create_reward_status_adjustment_and_campaign_balances_tasks(
    db_session: "AsyncSession",
    retailer: RetailerRewards,
    campaigns: list[Campaign],
    status: CampaignStatuses,
    balance_task_type: str,
) -> list[int]:
    async def _query() -> list[RetryTask]:
        tasks = []
        for campaign in campaigns:
            if status is CampaignStatuses.ENDED:
                tasks.append(
                    await async_create_task(
                        db_session=db_session,
                        task_type_name=settings.REWARD_STATUS_ADJUSTMENT_TASK_NAME,
                        params={
                            "retailer_slug": retailer.slug,
                            "reward_slug": campaign.reward_rule.reward_slug,
                            "status": status.value,
                        },
                    )
                )
            elif status is CampaignStatuses.CANCELLED:
                tasks.append(
                    await async_create_task(
                        db_session=db_session,
                        task_type_name=settings.REWARD_CANCELLATION_TASK_NAME,
                        params={
                            "retailer_slug": retailer.slug,
                            "campaign_slug": campaign.slug,
                        },
                    )
                )

            tasks.append(
                await async_create_task(
                    db_session=db_session,
                    task_type_name=balance_task_type,
                    params={
                        "retailer_slug": retailer.slug,
                        "campaign_slug": campaign.slug,
                    },
                )
            )

        await db_session.commit()
        return tasks

    return [task.retry_task_id for task in await async_run_query(_query, db_session)]


async def create_pending_rewards_tasks(
    db_session: "AsyncSession",
    campaigns: list[Campaign],
    retailer: RetailerRewards,
    issue_pending_rewards: Optional[bool] = False,
) -> list[int]:
    async def _query() -> list[RetryTask]:
        tasks = []
        for campaign in campaigns:
            tasks.append(
                await async_create_task(
                    db_session=db_session,
                    task_type_name=settings.PENDING_REWARDS_TASK_NAME,
                    params={
                        "retailer_slug": retailer.slug,
                        "campaign_slug": campaign.slug,
                        "issue_pending_rewards": issue_pending_rewards,
                    },
                )
            )

        await db_session.commit()
        return tasks

    return [task.retry_task_id for task in await async_run_query(_query, db_session)]


async def get_campaign(
    db_session: "AsyncSession",
    campaign_slug: str,
    retailer: RetailerRewards,
) -> Campaign:
    async def _query() -> Campaign:
        return (
            await db_session.execute(
                select(Campaign)
                .with_for_update()
                .where(Campaign.slug == campaign_slug, Campaign.retailer_id == retailer.id)
            )
        ).scalar_one_or_none()

    return await async_run_query(_query, db_session, rollback_on_exc=False)
