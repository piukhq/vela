from typing import TYPE_CHECKING, Dict, Generator

import pytest

from sqlalchemy_utils import create_database, database_exists, drop_database

from app.db.session import engine
from app.enums import CampaignStatuses
from app.models import Campaign, RetailerRewards

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# Top-level conftest for tests, doing things like setting up DB


@pytest.fixture(scope="session", autouse=True)
def setup_db() -> Generator:
    if engine.url.database != "vela_test":
        raise ValueError(f"Unsafe attempt to recreate database: {engine.url.database}")

    if database_exists(engine.url):
        drop_database(engine.url)
    create_database(engine.url)

    yield

    # At end of all tests, drop the test db
    drop_database(engine.url)


@pytest.fixture(scope="function")
def mock_retailer() -> Dict:
    return {
        "slug": "test-retailer",
    }


@pytest.fixture(scope="function")
def retailer(db_session: "Session", mock_retailer: Dict) -> RetailerRewards:
    retailer = RetailerRewards(**mock_retailer)
    db_session.add(retailer)
    db_session.commit()

    return retailer


@pytest.fixture(scope="function")
def mock_campaign() -> Dict:
    return {
        "status": CampaignStatuses.ACTIVE,
        "name": "testcampaign",
        "slug": "test-campaign",
    }


@pytest.fixture(scope="function")
def campaign(db_session: "Session", retailer: RetailerRewards, mock_campaign: Dict) -> Campaign:
    campaign = Campaign(**mock_campaign, retailer_id=retailer.id)
    db_session.add(campaign)
    db_session.commit()

    return campaign
