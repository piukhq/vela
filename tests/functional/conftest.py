from datetime import datetime
from typing import TYPE_CHECKING, Generator
from uuid import uuid4

import pytest

from retry_tasks_lib.db.models import RetryTask, TaskType
from retry_tasks_lib.utils.synchronous import sync_create_task

from app.core.config import settings
from app.db.base import Base
from app.db.session import sync_engine
from app.models import Campaign, ProcessedTransaction

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# conftest for API tests: tables will be dropped after each test to ensure a clean state


@pytest.fixture(scope="function", autouse=True)
def setup_tables() -> Generator:
    """
    autouse set to True so will be run before each test function, to set up tables
    and tear them down after each test runs
    """
    Base.metadata.create_all(bind=sync_engine)

    yield

    # Drop all tables after each test
    Base.metadata.drop_all(bind=sync_engine)


@pytest.fixture(scope="function")
def processed_transaction(db_session: "Session", campaign: Campaign) -> ProcessedTransaction:
    transaction = ProcessedTransaction(
        transaction_id="TEST123456",
        amount=300,
        mid="123456789",
        datetime=datetime.utcnow(),
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
            "processed_transaction_id": processed_transaction.id,
            "campaign_slug": processed_transaction.campaign_slugs[0],
            "adjustment_amount": 100,
            "idempotency_token": uuid4(),
        },
    )
    db_session.commit()
    return task


@pytest.fixture(scope="function")
def adjustment_url(reward_adjustment_task: RetryTask) -> str:
    task_params = reward_adjustment_task.get_params()

    return "{base_url}/bpl/loyalty/{retailer_slug}/accounts/{account_holder_uuid}/adjustments".format(
        base_url=settings.POLARIS_URL,
        retailer_slug=task_params["retailer_slug"],
        account_holder_uuid=task_params["account_holder_uuid"],
    )


@pytest.fixture(scope="function")
def allocation_url(reward_adjustment_task: RetryTask, voucher_type_slug: str) -> str:

    return "{base_url}/bpl/vouchers/{retailer_slug}/vouchers/{voucher_type_slug}/allocation".format(
        base_url=settings.CARINA_URL,
        retailer_slug=reward_adjustment_task.get_params()["retailer_slug"],
        voucher_type_slug=voucher_type_slug,
    )
