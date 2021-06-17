from datetime import datetime
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from fastapi import status
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture
from requests import Response

from app.core.config import settings
from app.enums import CampaignStatuses
from app.models import Campaign, EarnRule, ProcessedTransaction, Transaction
from asgi import app
from tests.api.conftest import SetupType

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

client = TestClient(app, raise_server_exceptions=False)
auth_headers = {"Authorization": f"Token {settings.VELA_AUTH_TOKEN}"}

account_holder_uuid = uuid4()
now = int(datetime.utcnow().timestamp())


class RetrySessionMock:
    def __init__(self, response: Response) -> None:
        self.response = response

    def get(self, *args: Any, **kwargs: Any) -> Response:
        return self.response


@pytest.fixture(scope="function")
def earn_rule(db_session: "Session", campaign: Campaign) -> EarnRule:
    earn_rule = EarnRule(campaign_id=campaign.id, threshold=300, increment_multiplier=1, increment=1)
    db_session.add(earn_rule)
    db_session.commit()
    return earn_rule


@pytest.fixture(scope="function")
def payload() -> dict:
    return {
        "id": "BPL123456789",
        "transaction_total": 1125,
        "datetime": str(now),
        "MID": "12345678",
        "loyalty_id": str(account_holder_uuid),
    }


def test_post_transaction_happy_path(
    setup: SetupType, payload: dict, earn_rule: EarnRule, mocker: MockerFixture
) -> None:
    db_session, retailer, _ = setup
    response = MagicMock(spec=Response, json=lambda: {"status": "active"}, status_code=status.HTTP_200_OK)
    mocker.patch("app.internal_requests.retry_session", return_value=RetrySessionMock(response))

    resp = client.post(f"/bpl/rewards/{retailer.slug}/transaction", json=payload, headers=auth_headers)

    assert resp.status_code == status.HTTP_200_OK
    assert resp.json() == "Awarded"

    processed_transaction = (
        db_session.query(ProcessedTransaction).filter_by(transaction_id=payload["id"], retailer_id=retailer.id).first()
    )

    assert processed_transaction is not None
    assert processed_transaction.mid == payload["MID"]
    assert processed_transaction.amount == payload["transaction_total"]
    assert processed_transaction.datetime == datetime.fromtimestamp(now)
    assert processed_transaction.account_holder_uuid == account_holder_uuid


def test_post_transaction_not_awarded(
    setup: SetupType, payload: dict, earn_rule: EarnRule, mocker: MockerFixture
) -> None:
    db_session, retailer, _ = setup
    response = MagicMock(spec=Response, json=lambda: {"status": "active"}, status_code=status.HTTP_200_OK)
    mocker.patch("app.internal_requests.retry_session", return_value=RetrySessionMock(response))

    payload["transaction_total"] = 250
    resp = client.post(f"/bpl/rewards/{retailer.slug}/transaction", json=payload, headers=auth_headers)

    assert resp.status_code == status.HTTP_200_OK
    assert resp.json() == "Threshold not met"

    processed_transaction = (
        db_session.query(ProcessedTransaction).filter_by(transaction_id=payload["id"], retailer_id=retailer.id).first()
    )

    assert processed_transaction is not None
    assert processed_transaction.mid == payload["MID"]
    assert processed_transaction.amount == payload["transaction_total"]
    assert processed_transaction.datetime == datetime.fromtimestamp(now)
    assert processed_transaction.account_holder_uuid == account_holder_uuid


def test_post_transaction_no_active_campaigns(
    setup: SetupType, payload: dict, earn_rule: EarnRule, mocker: MockerFixture
) -> None:
    db_session, retailer, campaign = setup

    campaign.status = CampaignStatuses.DRAFT
    db_session.commit()

    response = MagicMock(spec=Response, json=lambda: {"status": "active"}, status_code=status.HTTP_200_OK)
    mocker.patch("app.internal_requests.retry_session", return_value=RetrySessionMock(response))

    resp = client.post(f"/bpl/rewards/{retailer.slug}/transaction", json=payload, headers=auth_headers)

    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert resp.json() == {"display_message": "No active campaigns found for retailer.", "error": "NO_ACTIVE_CAMPAIGNS"}

    transaction = db_session.query(Transaction).filter_by(transaction_id=payload["id"], retailer_id=retailer.id).first()

    assert transaction is not None
    assert transaction.mid == payload["MID"]
    assert transaction.amount == payload["transaction_total"]
    assert transaction.datetime == datetime.fromtimestamp(now)
    assert transaction.account_holder_uuid == account_holder_uuid


def test_post_transaction_existing_transaction(setup: SetupType, payload: dict, mocker: MockerFixture) -> None:
    retailer_slug = setup.retailer.slug
    response = MagicMock(spec=Response, json=lambda: {"status": "active"}, status_code=status.HTTP_200_OK)
    mocker.patch("app.internal_requests.retry_session", return_value=RetrySessionMock(response))

    resp = client.post(f"/bpl/rewards/{retailer_slug}/transaction", json=payload, headers=auth_headers)

    assert resp.status_code == status.HTTP_200_OK

    resp = client.post(f"/bpl/rewards/{retailer_slug}/transaction", json=payload, headers=auth_headers)

    assert resp.status_code == status.HTTP_409_CONFLICT
    assert resp.json() == {"display_message": "Duplicate Transaction.", "error": "DUPLICATE_TRANSACTION"}


def test_post_transaction_wrong_retailer(payload: dict) -> None:
    resp = client.post("/bpl/rewards/NOT_A_RETIALER/transaction", json=payload, headers=auth_headers)
    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert resp.json() == {"display_message": "Requested retailer is invalid.", "error": "INVALID_RETAILER"}


def test_post_transaction_account_holder_validation_errors(
    setup: SetupType, payload: dict, mocker: MockerFixture
) -> None:
    retailer_slug = setup.retailer.slug

    mocked_session = mocker.patch("app.internal_requests.retry_session")
    mocked_session.return_value = RetrySessionMock(
        MagicMock(spec=Response, json=lambda: {"status": "pending"}, status_code=status.HTTP_200_OK)
    )

    resp = client.post(f"/bpl/rewards/{retailer_slug}/transaction", json=payload, headers=auth_headers)

    assert resp.status_code == status.HTTP_409_CONFLICT
    assert resp.json() == {"display_message": "User Account not Active", "error": "USER_NOT_ACTIVE"}

    response = Response()
    response.status_code = status.HTTP_404_NOT_FOUND
    mocked_session.return_value = RetrySessionMock(response)

    resp = client.post(f"/bpl/rewards/{retailer_slug}/transaction", json=payload, headers=auth_headers)

    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert resp.json() == {"display_message": "Unknown User.", "error": "USER_NOT_FOUND"}

    response = Response()
    response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    mocked_session.return_value = RetrySessionMock(response)

    resp = client.post(f"/bpl/rewards/{retailer_slug}/transaction", json=payload, headers=auth_headers)

    assert resp.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert resp.json() == {
        "display_message": "An unexpected system error occurred, please try again later.",
        "error": "INTERNAL_ERROR",
    }
