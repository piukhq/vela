from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic.types import constr
from retry_tasks_lib.db.models import RetryTask
from retry_tasks_lib.utils.asynchronous import enqueue_many_retry_tasks
from sqlalchemy.ext.asyncio import AsyncSession

from vela import crud
from vela.api.deps import get_session, retailer_is_valid, user_is_authorised
from vela.core.config import redis_raw, settings
from vela.db.base_class import async_run_query
from vela.enums import CampaignStatuses, HttpErrors, HttpsErrorTemplates
from vela.models.retailer import Campaign, RetailerRewards
from vela.schemas import CampaignsStatusChangeSchema

router = APIRouter()


class CampaignStatusError(Exception):
    pass


async def _check_remaining_active_campaigns(
    db_session: "AsyncSession", campaign_slugs: list[str], retailer: RetailerRewards
) -> None:
    try:
        active_campaigns: list[Campaign] = await crud.get_active_campaigns(db_session, retailer)
    except HTTPException as ex:
        # This would actually be an invalid status request
        if ex.detail["code"] == "NO_ACTIVE_CAMPAIGNS":  # type: ignore [index]
            raise HttpErrors.INVALID_STATUS_REQUESTED.value

    # If you've requested to end or cancel all of your active campaigns..
    active_campaign_slugs = [campaign.slug for campaign in active_campaigns]
    if set(active_campaign_slugs).issubset(set(campaign_slugs)):
        raise HttpErrors.INVALID_STATUS_REQUESTED.value


async def _check_valid_campaigns(
    campaign_slugs: list[str], campaigns: list[Campaign], requested_status: CampaignStatuses
) -> tuple[list[dict], int, list[Campaign]]:
    status_code = status.HTTP_200_OK
    is_activation = requested_status == CampaignStatuses.ACTIVE

    errors: dict[HttpsErrorTemplates, list[str]] = {
        HttpsErrorTemplates.NO_CAMPAIGN_FOUND: [],
        HttpsErrorTemplates.INVALID_STATUS_REQUESTED: [],
        HttpsErrorTemplates.MISSING_CAMPAIGN_COMPONENTS: [],
    }

    # Add in any campaigns that were not found
    missing_campaigns = list(set(campaign_slugs) - {campaign.slug for campaign in campaigns})
    if missing_campaigns:
        errors[HttpsErrorTemplates.NO_CAMPAIGN_FOUND] = missing_campaigns
        status_code = status.HTTP_404_NOT_FOUND

    valid_campaigns: list[Campaign] = []
    for campaign in campaigns:
        if requested_status.is_valid_status_transition(current_status=campaign.status):
            if not is_activation or campaign.is_activable():
                valid_campaigns.append(campaign)
            else:
                status_code = status.HTTP_409_CONFLICT
                errors[HttpsErrorTemplates.MISSING_CAMPAIGN_COMPONENTS].append(campaign.slug)
        else:
            status_code = status.HTTP_409_CONFLICT
            errors[HttpsErrorTemplates.INVALID_STATUS_REQUESTED].append(campaign.slug)

    formatted_errors = [
        error_type.value_with_slugs(campaign_slugs) for error_type, campaign_slugs in errors.items() if campaign_slugs
    ]
    return formatted_errors, status_code, valid_campaigns


async def _campaign_status_change(
    db_session: "AsyncSession", campaigns: list[Campaign], requested_status: CampaignStatuses
) -> None:
    async def _query(campaigns: list[Campaign]) -> None:
        for campaign in campaigns:
            campaign.status = requested_status
            now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
            if requested_status in (CampaignStatuses.CANCELLED, CampaignStatuses.ENDED):
                campaign.end_date = now
            elif requested_status == CampaignStatuses.ACTIVE:
                campaign.start_date = now

        await db_session.commit()

    await async_run_query(_query, db_session, campaigns=campaigns)


@router.post(
    path="/{retailer_slug}/campaigns/status_change",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(user_is_authorised)],
)
async def campaigns_status_change(
    payload: CampaignsStatusChangeSchema,
    retailer: RetailerRewards = Depends(retailer_is_valid),
    db_session: AsyncSession = Depends(get_session),
) -> Any:
    balance_task_type: str = settings.CREATE_CAMPAIGN_BALANCES_TASK_NAME
    requested_status = payload.requested_status
    campaigns: list[Campaign] = await crud.get_campaigns_by_slug(
        db_session=db_session, campaign_slugs=payload.campaign_slugs, retailer=retailer, load_rules=True
    )

    errors, status_code, valid_campaigns = await _check_valid_campaigns(
        payload.campaign_slugs, campaigns, requested_status
    )

    tasks_to_run_ids: list[int] = []

    # Check that this retailer will not be left with no active campaigns
    if requested_status in [CampaignStatuses.ENDED, CampaignStatuses.CANCELLED]:
        await _check_remaining_active_campaigns(
            db_session=db_session, campaign_slugs=payload.campaign_slugs, retailer=retailer
        )
        balance_task_type = settings.DELETE_CAMPAIGN_BALANCES_TASK_NAME

        campaigns_with_refund_window = [
            campaign for campaign in valid_campaigns if campaign.reward_rule.allocation_window > 0
        ]
        if campaigns_with_refund_window:
            pending_reward_retry_task_ids = await crud.create_pending_rewards_tasks(
                db_session=db_session,
                campaigns=campaigns_with_refund_window,
                retailer=retailer,
                issue_pending_rewards=payload.issue_pending_rewards and requested_status == CampaignStatuses.ENDED,
            )
            tasks_to_run_ids.extend(pending_reward_retry_task_ids)

    if valid_campaigns:
        await _campaign_status_change(
            db_session=db_session,
            campaigns=valid_campaigns,
            requested_status=requested_status,
        )

        retry_tasks_ids = await crud.create_reward_status_adjustment_and_campaign_balances_tasks(
            db_session=db_session,
            campaigns=valid_campaigns,
            retailer=retailer,
            status=payload.requested_status,
            balance_task_type=balance_task_type,
        )
        tasks_to_run_ids.extend(retry_tasks_ids)

        try:
            await enqueue_many_retry_tasks(
                db_session=db_session,
                retry_tasks_ids=tasks_to_run_ids,
                connection=redis_raw,
                raise_exc=True,
            )

        except Exception:

            async def _clean_up() -> None:
                await db_session.execute(
                    RetryTask.__table__.delete()
                    .where(RetryTask.retry_task_id.in_(tasks_to_run_ids))
                    .execution_options(synchronize_session=False)
                )
                await db_session.commit()

            await async_run_query(_clean_up, db_session, rollback_on_exc=True)
            raise HTTPException(  # pylint: disable=raise-missing-from
                detail="Failed to enqueue tasks.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    if errors:  # pragma: no cover
        raise HTTPException(detail=errors, status_code=status_code)

    return {}


@router.delete(
    path="/{retailer_slug}/campaigns/{campaign_slug}",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(user_is_authorised)],
)
async def delete_draft_campaigns(
    campaign_slug: constr(min_length=1, strip_whitespace=True),  # type: ignore  # noqa
    retailer: RetailerRewards = Depends(retailer_is_valid),
    db_session: AsyncSession = Depends(get_session),
) -> Any:
    campaign = await crud.get_campaign(
        db_session,
        retailer=retailer,
        campaign_slug=campaign_slug,
    )

    async def _query() -> None:
        await db_session.delete(campaign)
        await db_session.commit()

    if campaign:
        if campaign.status == CampaignStatuses.DRAFT:
            await async_run_query(_query, db_session)
        else:
            raise HttpErrors.DELETE_FAILED.value
    else:
        raise HttpErrors.NO_CAMPAIGN_FOUND.value
    return {}
