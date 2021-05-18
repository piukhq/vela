from collections import namedtuple
from typing import TYPE_CHECKING, Any, Dict, Generator
from unittest.mock import ANY, MagicMock, call, patch

import pytest

from fastapi.testclient import TestClient
from starlette import status

from app.core.config import settings
from app.enums import CampaignStatuses, HttpErrors
from app.models import Campaign, RetailerRewards
from asgi import app

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

SetupType = namedtuple("SetupType", ["db_session", "retailer", "campaign"])

client = TestClient(app)
auth_headers = {"Authorization": f"Token {settings.AUTH_TOKEN}", "Bpl-User-Channel": "channel"}


@pytest.fixture(scope="function")
def setup(
    db_session: "Session", retailer: RetailerRewards, campaign: Campaign
) -> Generator[SetupType, None, None]:
    yield SetupType(db_session, retailer, campaign)


'''
def test_healthz_routes_no_channel_header() -> None:
    paths = ("/readyz", "/livez")
    for path in paths:
        resp = client.get(path, headers={})
        assert resp.status_code == 200


@patch("app.api.endpoints.account_holder.register_account_holder", mock_register_user)
@patch("app.api.endpoints.account_holder._create_initial_current_balances")
@patch("app.api.endpoints.account_holder._get_campaign_slugs", return_value=[])
@patch("app.core.middleware.signal", autospec=True)
def test_account_holder_enrol_success(
    mock_signal: MagicMock,
    mock_get_campaign_slugs: MagicMock,
    mock_create_initial_current_balances: MagicMock,
    mock_current_balances: Dict,
    setup: SetupType,
    test_account_holder_enrol: Dict,
) -> None:
    db_session, retailer, _ = setup
    mock_create_initial_current_balances.return_value = mock_current_balances
    email = test_account_holder_enrol["credentials"]["email"]
    endpoint = f"{settings.API_PREFIX}/%s/accounts/enrolment"
    expected_calls = [  # The expected call stack for signal, in order
        call(EventSignals.RECORD_HTTP_REQ),
        call().send(
            "app.core.middleware",
            endpoint=endpoint % "[retailer_slug]",
            retailer=retailer.slug,
            latency=ANY,
            response_code=status.HTTP_202_ACCEPTED,
            method="POST",
        ),
        call(EventSignals.INBOUND_HTTP_REQ),
        call().send(
            "app.core.middleware",
            endpoint=endpoint % "[retailer_slug]",
            retailer=retailer.slug,
            response_code=status.HTTP_202_ACCEPTED,
            method="POST",
        ),
    ]

    resp = client.post(
        endpoint % retailer.slug,
        json=test_account_holder_enrol,
        headers=auth_headers,
    )

    assert resp.status_code == status.HTTP_202_ACCEPTED
    assert resp.json() == {}
    mock_signal.assert_has_calls(expected_calls)

    account_holder = db_session.query(AccountHolder).filter_by(retailer_id=retailer.id, email=email).first()

    assert account_holder is not None
    assert account_holder.account_number is None
    assert account_holder.status == AccountHolderStatuses.ACTIVE
    assert account_holder.current_balances == mock_current_balances
'''


def test_active_campaign_slugs(setup: SetupType) -> None:
    _, retailer, campaign = setup

    resp = client.get(
        f"{settings.API_PREFIX}/{retailer.slug}/active-campaign-slugs",
        headers=auth_headers,
    )

    assert resp.status_code == 200
    # assert resp.json()["UUID"] == str(account_holder.id)
    # current_balances are transformed into a list for the JSON response


'''
def test_get_account_holder_status(setup: SetupType) -> None:
    # GIVEN
    _, retailer, account_holder = setup

    # WHEN
    resp = client.get(
        f"{settings.API_PREFIX}/{retailer.slug}/accounts/{account_holder.id}/status",
        headers=auth_headers,
    )

    # THEN
    assert resp.status_code == status.HTTP_200_OK
    assert len(resp.json().keys()) == 1
    assert resp.json()["status"] == account_holder.status.value


def test_get_account_holder_status_invalid_token(setup: SetupType) -> None:
    # GIVEN
    _, retailer, account_holder = setup

    # WHEN
    resp = client.get(
        f"{settings.API_PREFIX}/{retailer.slug}/accounts/{account_holder.id}/status",
        headers={"Authorization": "Token wrong token", "Bpl-User-Channel": "channel"},
    )

    # THEN
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert resp.json() == {
        "display_message": "Supplied token is invalid.",
        "error": "INVALID_TOKEN",
    }


def test_get_account_holder_status_invalid_retailer(setup: SetupType) -> None:
    # GIVEN
    _, retailer, account_holder = setup
    bad_retailer_slug = "wrong-merchant"

    # WHEN
    resp = client.get(
        f"{settings.API_PREFIX}/{bad_retailer_slug}/accounts/{account_holder.id}/status",
        headers=auth_headers,
    )

    # THEN
    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert resp.json() == {"display_message": "Requested retailer is invalid.", "error": "INVALID_RETAILER"}
'''
