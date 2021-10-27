from copy import deepcopy
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Callable, Dict, Generator

import pytest

from retry_tasks_lib.db.models import TaskType, TaskTypeKey
from retry_tasks_lib.enums import TaskParamsKeyTypes
from sqlalchemy_utils import create_database, database_exists, drop_database

from app.db.session import SyncSessionMaker, sync_engine
from app.enums import CampaignStatuses
from app.models import Campaign, RetailerRewards

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# Top-level conftest for tests, doing things like setting up DB


@pytest.fixture(scope="session", autouse=True)
def setup_db() -> Generator:
    if sync_engine.url.database != "vela_test":
        raise ValueError(f"Unsafe attempt to recreate database: {sync_engine.url.database}")

    if database_exists(sync_engine.url):
        drop_database(sync_engine.url)
    create_database(sync_engine.url)

    yield

    # At end of all tests, drop the test db
    drop_database(sync_engine.url)


@pytest.fixture(scope="module")
def main_db_session() -> Generator["Session", None, None]:
    with SyncSessionMaker() as db_session:
        yield db_session


@pytest.fixture(scope="function")
def db_session(main_db_session: "Session") -> Generator["Session", None, None]:
    yield main_db_session
    main_db_session.rollback()
    main_db_session.expunge_all()


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
        "start_date": datetime.utcnow() - timedelta(minutes=5),
    }


@pytest.fixture(scope="function")
def campaign(db_session: "Session", retailer: RetailerRewards, mock_campaign: Dict) -> Campaign:
    campaign = Campaign(**mock_campaign, retailer_id=retailer.id)
    db_session.add(campaign)
    db_session.commit()

    return campaign


@pytest.fixture(scope="function")
def create_mock_campaign(db_session: "Session", retailer: RetailerRewards, mock_campaign: Dict) -> Callable:
    def _create_mock_campaign(**campaign_params: Dict) -> Campaign:
        """
        Create a campaign in the test DB
        :param campaign_params: override any values for the campaign, from what the mock_campaign fixture provides
        :return: Callable function
        """
        mock_campaign_params = deepcopy(mock_campaign)

        mock_campaign_params.update(campaign_params)  # type: ignore
        campaign = Campaign(**mock_campaign_params, retailer_id=retailer.id)
        db_session.add(campaign)
        db_session.commit()

        return campaign

    return _create_mock_campaign


@pytest.fixture(scope="function")
def reward_adjustment_task_type(db_session: "Session") -> TaskType:
    task_type = TaskType(name="reward_adjustment", path="sample.path")
    db_session.add(task_type)
    db_session.flush()
    db_session.bulk_save_objects(
        [
            TaskTypeKey(task_type_id=task_type.task_type_id, name=key_name, type=key_type)
            for key_name, key_type in (
                ("account_holder_uuid", TaskParamsKeyTypes.STRING),
                ("retailer_slug", TaskParamsKeyTypes.STRING),
                ("processed_transaction_id", TaskParamsKeyTypes.INTEGER),
                ("campaign_slug", TaskParamsKeyTypes.STRING),
                ("adjustment_amount", TaskParamsKeyTypes.INTEGER),
                ("idempotency_token", TaskParamsKeyTypes.STRING),
            )
        ]
    )
    db_session.commit()
    return task_type
