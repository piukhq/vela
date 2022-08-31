from collections import namedtuple
from copy import deepcopy
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Callable, Generator

import pytest

from retry_tasks_lib.db.models import TaskType, TaskTypeKey
from retry_tasks_lib.enums import TaskParamsKeyTypes
from sqlalchemy_utils import create_database, database_exists, drop_database

from app.core.config import redis, settings
from app.db.base import Base
from app.db.session import SyncSessionMaker, sync_engine
from app.enums import CampaignStatuses
from app.models import Campaign, EarnRule, RetailerRewards, RetailerStore, Transaction
from app.models.retailer import RewardRule

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# Top-level conftest for tests, doing things like setting up DB


SetupType = namedtuple("SetupType", ["db_session", "retailer", "campaign"])


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


@pytest.fixture(scope="session", autouse=True)
def setup_redis() -> Generator:

    yield

    # At end of all tests, delete the tasks from the queue
    redis.flushdb()


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


@pytest.fixture(scope="module")
def main_db_session() -> Generator["Session", None, None]:
    with SyncSessionMaker() as session:
        yield session


@pytest.fixture(scope="function")
def db_session(main_db_session: "Session") -> Generator["Session", None, None]:
    yield main_db_session
    main_db_session.rollback()
    main_db_session.expunge_all()


@pytest.fixture(scope="function")
def mock_retailer() -> dict:
    return {
        "slug": "test-retailer",
    }


@pytest.fixture(scope="function")
def retailer(db_session: "Session", mock_retailer: dict) -> RetailerRewards:
    rtl = RetailerRewards(**mock_retailer)
    db_session.add(rtl)
    db_session.commit()

    return rtl


@pytest.fixture(scope="function")
def mock_campaign() -> dict:
    return {
        "status": CampaignStatuses.ACTIVE,
        "name": "testcampaign",
        "slug": "test-campaign",
        "start_date": datetime.utcnow() - timedelta(minutes=5),
    }


@pytest.fixture(scope="function")
def campaign(db_session: "Session", retailer: RetailerRewards, mock_campaign: dict) -> Campaign:
    cpn = Campaign(**mock_campaign, retailer_id=retailer.id)
    db_session.add(cpn)
    db_session.commit()

    return cpn


@pytest.fixture
def reward_slug() -> str:
    return "the-big-reward-slug"


@pytest.fixture(scope="function")
def reward_rule(db_session: "Session", campaign: Campaign, reward_slug: str) -> RewardRule:
    rrl = RewardRule(reward_goal=5, reward_slug=reward_slug, campaign_id=campaign.id)
    db_session.add(rrl)
    db_session.commit()
    return rrl


@pytest.fixture(scope="function")
def earn_rule(db_session: "Session", campaign: Campaign) -> EarnRule:
    erl = EarnRule(campaign_id=campaign.id, threshold=300, increment_multiplier=1, increment=1)
    db_session.add(erl)
    db_session.commit()
    return erl


@pytest.fixture(scope="function")
def create_mock_transaction(db_session: "Session") -> Callable:
    def _create_mock_transaction(retailer_id: int, **transaction_data: dict) -> Transaction:
        """
        Create a transaction in the test DB
        :param transaction_data: field and valus required for a Transaction
        :return: Callable function
        """

        transaction = Transaction(retailer_id=retailer_id, **transaction_data)
        db_session.add(transaction)
        db_session.commit()

        return transaction

    return _create_mock_transaction


@pytest.fixture(scope="function")
def create_mock_campaign(db_session: "Session", retailer: RetailerRewards, mock_campaign: dict) -> Callable:
    def _create_mock_campaign(**campaign_params: dict) -> Campaign:
        """
        Create a campaign in the test DB
        :param campaign_params: override any values for the campaign, from what the mock_campaign fixture provides
        :return: Callable function
        """
        mock_campaign_params = deepcopy(mock_campaign)
        mock_campaign_params["retailer_id"] = retailer.id

        mock_campaign_params.update(campaign_params)
        cpn = Campaign(**mock_campaign_params)
        db_session.add(cpn)
        db_session.commit()

        return cpn

    return _create_mock_campaign


@pytest.fixture(scope="function")
def create_mock_reward_rule(db_session: "Session", retailer: RetailerRewards, mock_campaign: dict) -> Callable:
    def _create_mock_reward_rule(
        reward_slug: str,  # pylint: disable=redefined-outer-name
        campaign_id: int,
        reward_goal: int = 5,
        allocation_window: int = 0,
    ) -> RewardRule:
        """
        Create a reward rule in the test DB
        :return: Callable function
        """
        rrl = RewardRule(
            reward_goal=reward_goal,
            reward_slug=reward_slug,
            campaign_id=campaign_id,
            allocation_window=allocation_window,
        )
        db_session.add(rrl)
        db_session.commit()
        return rrl

    return _create_mock_reward_rule


@pytest.fixture(scope="function")
def create_mock_earn_rule(db_session: "Session") -> Callable:
    def _create_mock_earn_rule(campaign_id: int, **earn_rule_params: dict) -> EarnRule:
        """
        Create an earn rule in the test DB
        earn_rule_params eg. threshold=300, increment_multiplier=1, increment=1
        :return: Callable function
        """
        erl = EarnRule(campaign_id=campaign_id, **earn_rule_params)
        db_session.add(erl)
        db_session.commit()
        return erl

    return _create_mock_earn_rule


@pytest.fixture(scope="function")
def create_mock_retailer(db_session: "Session", mock_retailer: dict) -> Callable:
    def _create_mock_retailer(**retailer_params: dict) -> RetailerRewards:
        """
        Create a retailer in the test DB
        :param retailer_params: override any values for the retailer, from what the mock_retailer fixture provides
        :return: Callable function
        """
        mock_retailer_params = deepcopy(mock_retailer)

        mock_retailer_params.update(retailer_params)
        rtl = RetailerRewards(**mock_retailer_params)
        db_session.add(rtl)
        db_session.commit()

        return rtl

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
                ("pre_allocation_token", TaskParamsKeyTypes.STRING),
                ("post_allocation_token", TaskParamsKeyTypes.STRING),
                ("allocation_token", TaskParamsKeyTypes.STRING),
                ("secondary_reward_retry_task_id", TaskParamsKeyTypes.INTEGER),
                ("transaction_datetime", TaskParamsKeyTypes.DATETIME),
            )
        ]
    )
    db_session.commit()
    return task_type


@pytest.fixture(scope="function")
def reward_status_adjustment_task_type(db_session: "Session") -> TaskType:
    task = TaskType(
        name=settings.REWARD_STATUS_ADJUSTMENT_TASK_NAME,
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
                ("reward_slug", "STRING"),
                ("retailer_slug", "STRING"),
                ("status", "STRING"),
            )
        ]
    )

    db_session.commit()
    return task


@pytest.fixture(scope="function")
def create_campaign_balances_task_type(db_session: "Session") -> TaskType:
    task = TaskType(
        name=settings.CREATE_CAMPAIGN_BALANCES_TASK_NAME,
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
                ("retailer_slug", "STRING"),
                ("campaign_slug", "STRING"),
            )
        ]
    )

    db_session.commit()
    return task


@pytest.fixture(scope="function")
def delete_campaign_balances_task_type(db_session: "Session") -> TaskType:
    task = TaskType(
        name=settings.DELETE_CAMPAIGN_BALANCES_TASK_NAME,
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
                ("retailer_slug", "STRING"),
                ("campaign_slug", "STRING"),
            )
        ]
    )

    db_session.commit()
    return task


@pytest.fixture(scope="function")
def convert_or_delete_pending_rewards_task_type(db_session: "Session") -> TaskType:
    task = TaskType(
        name=settings.PENDING_REWARDS_TASK_NAME,
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
                ("retailer_slug", "STRING"),
                ("campaign_slug", "STRING"),
                ("issue_pending_rewards", "BOOLEAN"),
            )
        ]
    )

    db_session.commit()
    return task


@pytest.fixture
def run_task_with_metrics() -> Generator:
    val = settings.ACTIVATE_TASKS_METRICS
    settings.ACTIVATE_TASKS_METRICS = True  # pylint: disable=invalid-name
    yield
    settings.ACTIVATE_TASKS_METRICS = val


@pytest.fixture
def retailer_store(db_session: "Session", retailer: RetailerRewards) -> RetailerStore:
    rstore = RetailerStore(store_name="Test Store", mid="TS123456", retailer=retailer)
    db_session.add(rstore)

    return rstore
