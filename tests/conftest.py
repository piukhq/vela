from copy import deepcopy
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Callable, Dict, Generator

import pytest

from retry_tasks_lib.db.models import TaskType, TaskTypeKey
from retry_tasks_lib.enums import TaskParamsKeyTypes
from sqlalchemy_utils import create_database, database_exists, drop_database

from app.core.config import settings
from app.db.session import SyncSessionMaker, sync_engine
from app.enums import CampaignStatuses
from app.models import Campaign, RetailerRewards
from app.models.retailer import RewardRule

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


@pytest.fixture
def voucher_type_slug() -> str:
    return "the-big-voucher-slug"


@pytest.fixture(scope="function")
def reward_rule(db_session: "Session", campaign: Campaign, voucher_type_slug: str) -> RewardRule:
    reward_rule = RewardRule(reward_goal=5, voucher_type_slug=voucher_type_slug, campaign_id=campaign.id)
    db_session.add(reward_rule)
    db_session.commit()
    return reward_rule


@pytest.fixture(scope="function")
def create_mock_campaign(db_session: "Session", retailer: RetailerRewards, mock_campaign: Dict) -> Callable:
    def _create_mock_campaign(**campaign_params: Dict) -> Campaign:
        """
        Create a campaign in the test DB
        :param campaign_params: override any values for the campaign, from what the mock_campaign fixture provides
        :return: Callable function
        """
        mock_campaign_params = deepcopy(mock_campaign)
        mock_campaign_params["retailer_id"] = retailer.id

        mock_campaign_params.update(campaign_params)
        campaign = Campaign(**mock_campaign_params)
        db_session.add(campaign)
        db_session.commit()

        return campaign

    return _create_mock_campaign


@pytest.fixture(scope="function")
def create_mock_reward_rule(db_session: "Session", retailer: RetailerRewards, mock_campaign: Dict) -> Callable:
    def _create_mock_reward_rule(voucher_type_slug: str, campaign_id: int, reward_goal: int = 5) -> RewardRule:
        """
        Create a reward rule in the test DB
        :return: Callable function
        """
        reward_rule = RewardRule(reward_goal=reward_goal, voucher_type_slug=voucher_type_slug, campaign_id=campaign_id)
        db_session.add(reward_rule)
        db_session.commit()
        return reward_rule

    return _create_mock_reward_rule


@pytest.fixture(scope="function")
def create_mock_retailer(db_session: "Session", mock_retailer: Dict) -> Callable:
    def _create_mock_retailer(**retailer_params: Dict) -> RetailerRewards:
        """
        Create a retailer in the test DB
        :param retailer_params: override any values for the retailer, from what the mock_retailer fixture provides
        :return: Callable function
        """
        mock_retailer_params = deepcopy(mock_retailer)

        mock_retailer_params.update(retailer_params)
        retailer = RetailerRewards(**mock_retailer_params)
        db_session.add(retailer)
        db_session.commit()

        return retailer

    return _create_mock_retailer


@pytest.fixture(scope="function")
def reward_adjustment_task_type(db_session: "Session") -> TaskType:
    task_type = TaskType(
        name=settings.REWARD_ADJUSTMENT_TASK_NAME,
        path="sample.path",
        queue_name="test_queue",
        error_handler_path="path.to.error_handler",
    )
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


@pytest.fixture(scope="function")
def voucher_status_adjustment_task_type(db_session: "Session") -> TaskType:
    task = TaskType(
        name=settings.VOUCHER_STATUS_ADJUSTMENT_TASK_NAME,
        path="sample.path",
        queue_name="test_queue",
        error_handler_path="path.to.error_handler",
    )
    db_session.add(task)
    db_session.flush()

    db_session.bulk_save_objects(
        [
            TaskTypeKey(task_type_id=task.task_type_id, name=key_name, type=key_type)
            for key_name, key_type in (
                ("voucher_type_slug", "STRING"),
                ("retailer_slug", "STRING"),
                ("status", "STRING"),
            )
        ]
    )

    db_session.commit()
    return task
