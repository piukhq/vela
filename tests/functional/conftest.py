from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from retry_tasks_lib.db.models import RetryTask, TaskType, TaskTypeKeyValue
from retry_tasks_lib.utils.synchronous import sync_create_task

from vela.core.config import settings
from vela.enums import CampaignStatuses
from vela.models import Campaign, ProcessedTransaction

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# conftest for API tests: tables will be dropped after each test to ensure a clean state


@pytest.fixture(scope="function")
def processed_transaction(db_session: "Session", campaign: Campaign) -> ProcessedTransaction:
    transaction = ProcessedTransaction(
        transaction_id="TEST123456",
        amount=300,
        mid="123456789",
        datetime=datetime.now(tz=timezone.utc),
        account_holder_uuid=uuid4(),
        retailer_id=campaign.retailer_id,
        campaign_slugs=[campaign.slug],
    )
    db_session.add(transaction)
    db_session.commit()
    return transaction


@pytest.fixture(scope="function")
def reward_adjustment_task(
    db_session: "Session", processed_transaction: ProcessedTransaction, reward_adjustment_task_type: TaskType
) -> RetryTask:
    task = sync_create_task(
        db_session,
        task_type_name=reward_adjustment_task_type.name,
        params={
            "account_holder_uuid": processed_transaction.account_holder_uuid,
            "retailer_slug": processed_transaction.retailer.slug,
            "processed_transaction_id": processed_transaction.transaction_id,
            "campaign_slug": processed_transaction.campaign_slugs[0],
            "adjustment_amount": 100,
            "pre_allocation_token": uuid4(),
            "transaction_datetime": processed_transaction.datetime,
        },
    )
    db_session.commit()
    return task


@pytest.fixture(scope="function")
def adjustment_url(reward_adjustment_task: RetryTask) -> str:
    task_params = reward_adjustment_task.get_params()

    return "{base_url}/{retailer_slug}/accounts/{account_holder_uuid}/adjustments".format(
        base_url=settings.POLARIS_BASE_URL,
        retailer_slug=task_params["retailer_slug"],
        account_holder_uuid=task_params["account_holder_uuid"],
    )


@pytest.fixture(scope="function")
def allocation_url(reward_adjustment_task: RetryTask, reward_slug: str) -> str:
    return "{base_url}/{retailer_slug}/rewards/{reward_slug}/allocation".format(
        base_url=settings.CARINA_BASE_URL,
        retailer_slug=reward_adjustment_task.get_params()["retailer_slug"],
        reward_slug=reward_slug,
    )


@pytest.fixture(scope="function")
def reward_status_adjustment_task_params(reward_slug: str, mock_retailer: dict) -> dict:
    return {
        "retailer_slug": mock_retailer["slug"],
        "reward_slug": reward_slug,
        "status": CampaignStatuses.ACTIVE.value,
    }


@pytest.fixture(scope="function")
def reward_status_adjustment_retry_task(
    db_session: "Session", reward_status_adjustment_task_params: dict, reward_status_adjustment_task_type: TaskType
) -> RetryTask:
    task = RetryTask(task_type_id=reward_status_adjustment_task_type.task_type_id)
    db_session.add(task)
    db_session.flush()

    key_ids = reward_status_adjustment_task_type.get_key_ids_by_name()
    db_session.add_all(
        [
            TaskTypeKeyValue(
                task_type_key_id=key_ids[key],
                value=value,
                retry_task_id=task.retry_task_id,
            )
            for key, value in reward_status_adjustment_task_params.items()
        ]
    )
    db_session.commit()
    return task


@pytest.fixture(scope="function")
def reward_status_adjustment_expected_payload(reward_status_adjustment_retry_task: RetryTask) -> dict:
    params = reward_status_adjustment_retry_task.get_params()
    return {
        "status": params["status"],
    }


@pytest.fixture(scope="function")
def reward_status_adjustment_url(reward_status_adjustment_task_params: dict) -> str:
    return "{base_url}/{retailer_slug}/rewards/{reward_slug}/status".format(
        base_url=settings.CARINA_BASE_URL,
        retailer_slug=reward_status_adjustment_task_params["retailer_slug"],
        reward_slug=reward_status_adjustment_task_params["reward_slug"],
    )


@pytest.fixture(scope="function")
def reward_cancellatin_task_params(mock_campaign: dict, mock_retailer: dict) -> dict:
    return {
        "retailer_slug": mock_retailer["slug"],
        "campaign_slug": mock_campaign["slug"],
        "cancel_datetime": datetime.now(tz=timezone.utc).isoformat(),
    }


@pytest.fixture(scope="function")
def reward_cancellation_url(reward_cancellatin_task_params: dict) -> str:
    return "{base_url}/{retailer_slug}/rewards/{campaign_slug}/cancel".format(
        base_url=settings.POLARIS_BASE_URL,
        retailer_slug=reward_cancellatin_task_params["retailer_slug"],
        campaign_slug=reward_cancellatin_task_params["campaign_slug"],
    )


@pytest.fixture(scope="function")
def reward_cancellation_retry_task(
    db_session: "Session", reward_cancellatin_task_params: dict, account_holder_cancel_reward_task_type: TaskType
) -> RetryTask:
    task = RetryTask(task_type_id=account_holder_cancel_reward_task_type.task_type_id)
    db_session.add(task)
    db_session.flush()

    key_ids = account_holder_cancel_reward_task_type.get_key_ids_by_name()
    db_session.add_all(
        [
            TaskTypeKeyValue(
                task_type_key_id=key_ids[key],
                value=value,
                retry_task_id=task.retry_task_id,
            )
            for key, value in reward_cancellatin_task_params.items()
        ]
    )
    db_session.commit()
    return task
