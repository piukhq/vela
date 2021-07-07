from collections import namedtuple
from typing import TYPE_CHECKING, Generator

import pytest

from app.db.base import Base
from app.db.session import SyncSessionMaker, sync_engine
from app.models import Campaign, RetailerRewards

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# conftest for API tests: tables will be dropped after each test to ensure a clean state
SetupType = namedtuple("SetupType", ["db_session", "retailer", "campaign"])


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
def setup(db_session: "Session", retailer: RetailerRewards, campaign: Campaign) -> Generator[SetupType, None, None]:
    yield SetupType(db_session, retailer, campaign)
