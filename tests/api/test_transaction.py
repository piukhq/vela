from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import requests

from fastapi import status
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture
from requests import Response

from app.core.config import settings
from app.models import Transaction
from asgi import app
from tests.api.conftest import SetupType

client = TestClient(app)
auth_headers = {"Authorization": f"Token {settings.VELA_AUTH_TOKEN}"}

account_holder_uuid = uuid4()
now = int(datetime.utcnow().timestamp())
payload: dict = {
    "id": "BPL123456789",
    "transaction_total": 11.25,
    "datetime": str(now),
    "MID": "12345678",
    "loyalty_id": str(account_holder_uuid),
}


class RetrySessionMock:
    def __init__(self, response: Response) -> None:
        self.response = response

    def get(self, *args: Any, **kwargs: Any) -> Response:
        return self.response


def test_post_transaction_happy_path(setup: SetupType, mocker: MockerFixture) -> None:
    db_session, retailer, _ = setup
    response = MagicMock(spec=Response, json=lambda: {"status": "active"}, status_code=status.HTTP_200_OK)
    mocker.patch("app.internal_requests.retry_session", return_value=RetrySessionMock(response))

    resp = client.post(f"/bpl/rewards/{retailer.slug}/transaction", json=payload, headers=auth_headers)

    assert resp.status_code == status.HTTP_200_OK

    transaction = db_session.query(Transaction).filter_by(transaction_id=payload["id"], retailer_id=retailer.id).first()

    assert transaction is not None
    assert transaction.mid == payload["MID"]
    assert transaction.amount == int(payload["transaction_total"] * 100)
    assert transaction.datetime == now
    assert transaction.account_holder_uuid == account_holder_uuid


def test_post_transaction_existing_transaction(setup: SetupType, mocker: MockerFixture) -> None:
    retailer_slug = setup.retailer.slug
    response = MagicMock(spec=Response, json=lambda: {"status": "active"}, status_code=status.HTTP_200_OK)
    mocker.patch("app.internal_requests.retry_session", return_value=RetrySessionMock(response))

    resp = client.post(f"/bpl/rewards/{retailer_slug}/transaction", json=payload, headers=auth_headers)

    assert resp.status_code == status.HTTP_200_OK

    resp = client.post(f"/bpl/rewards/{retailer_slug}/transaction", json=payload, headers=auth_headers)

    assert resp.status_code == status.HTTP_409_CONFLICT
    assert resp.json() == {"display_message": "Duplicate Transaction.", "error": "DUPLICATE_TRANSACTION"}


def test_post_transaction_wrong_retailer() -> None:
    resp = client.post("/bpl/rewards/NOT_A_RETIALER/transaction", json=payload, headers=auth_headers)
    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert resp.json() == {"display_message": "Requested retailer is invalid.", "error": "INVALID_RETAILER"}


def test_post_transaction_account_holder_validation_errors(setup: SetupType, mocker: MockerFixture) -> None:
    retailer_slug = setup.retailer.slug

    mocked_session = mocker.patch("app.internal_requests.retry_session")
    mocked_session.return_value = RetrySessionMock(
        MagicMock(spec=Response, json=lambda: {"status": "pending"}, status_code=status.HTTP_200_OK)
    )

    resp = client.post(f"/bpl/rewards/{retailer_slug}/transaction", json=payload, headers=auth_headers)

    assert resp.status_code == status.HTTP_409_CONFLICT
    assert resp.json() == {"display_message": "User Account not Active", "error": "USER_NOT_ACTIVE"}

    response = MagicMock(spec=Response, status_code=status.HTTP_404_NOT_FOUND)
    response.raise_for_status = Mock(side_effect=requests.RequestException())
    mocked_session.return_value = RetrySessionMock(response)

    resp = client.post(f"/bpl/rewards/{retailer_slug}/transaction", json=payload, headers=auth_headers)

    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert resp.json() == {"display_message": "Unknown User.", "error": "USER_NOT_FOUND"}

    response = MagicMock(spec=Response, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    response.raise_for_status = Mock(side_effect=requests.RequestException())
    mocked_session.return_value = RetrySessionMock(response)

    resp = client.post(f"/bpl/rewards/{retailer_slug}/transaction", json=payload, headers=auth_headers)

    assert resp.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert resp.json() == {
        "display_message": "An unexpected system error occurred, please try again later.",
        "error": "INTERNAL_ERROR",
    }
