from datetime import datetime
from typing import TYPE_CHECKING, Generator
from uuid import uuid4

import pytest

from app.core.config import settings
from app.db.base import Base
from app.db.session import SyncSessionMaker, sync_engine
from app.models import Campaign, ProcessedTransaction, RewardAdjustment

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# conftest for API tests: tables will be dropped after each test to ensure a clean state


@pytest.fixture(scope="module")
def api_db_session() -> Generator["Session", None, None]:
    with SyncSessionMaker() as db_session:
        yield db_session


@pytest.fixture(scope="function")
def db_session(api_db_session: "Session") -> Generator["Session", None, None]:
    yield api_db_session
    api_db_session.rollback()


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
def reward_adjustment(db_session: "Session", processed_transaction: ProcessedTransaction) -> RewardAdjustment:
    adjustment = RewardAdjustment(
        adjustment_amount=50,
        campaign_slug=processed_transaction.campaign_slugs[0],
        processed_transaction_id=processed_transaction.id,
    )
    db_session.add(adjustment)
    db_session.commit()
    return adjustment


@pytest.fixture(scope="function")
def adjustment_url(reward_adjustment: RewardAdjustment) -> str:
    return "{base_url}/bpl/loyalty/{retailer_slug}/accounts/{account_holder_uuid}/adjustments".format(
        base_url=settings.POLARIS_URL,
        retailer_slug=reward_adjustment.processed_transaction.retailer.slug,
        account_holder_uuid=reward_adjustment.processed_transaction.account_holder_uuid,
    )
