from typing import TYPE_CHECKING, Generator

import pytest

from app.db.base import Base
from app.db.session import SessionMaker, engine

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# conftest for API tests: tables will be dropped after each test to ensure a clean state


@pytest.fixture(scope="module")
def api_db_session() -> Generator["Session", None, None]:
    with SessionMaker() as db_session:
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
    Base.metadata.create_all(bind=engine)

    yield

    # Drop all tables after each test
    Base.metadata.drop_all(bind=engine)
