from collections import namedtuple
from typing import TYPE_CHECKING, Generator

import pytest

from fastapi.testclient import TestClient
from starlette import status

from app.core.config import settings
from app.models import Campaign, RetailerRewards
from asgi import app

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

SetupType = namedtuple("SetupType", ["db_session", "retailer", "campaign"])

client = TestClient(app)
auth_headers = {"Authorization": f"Token {settings.AUTH_TOKEN}", "Bpl-User-Channel": "channel"}


@pytest.fixture(scope="function")
def setup(db_session: "Session", retailer: RetailerRewards, campaign: Campaign) -> Generator[SetupType, None, None]:
    yield SetupType(db_session, retailer, campaign)


def test_healthz_routes_no_channel_header() -> None:
    paths = ("/readyz", "/livez")
    for path in paths:
        resp = client.get(path, headers={})
        assert resp.status_code == 200


def test_active_campaign_slugs(setup: SetupType) -> None:
    # GIVEN
    _, retailer, campaign = setup
    expected_campaign_slugs = [campaign.slug]

    # WHEN
    resp = client.get(
        f"{settings.API_PREFIX}/{retailer.slug}/active-campaign-slugs",
        headers=auth_headers,
    )

    # THEN
    assert resp.status_code == status.HTTP_200_OK
    campaign_slugs = resp.json()
    assert len(campaign_slugs)
    assert campaign_slugs == expected_campaign_slugs


def test_active_campaign_slugs_invalid_token(setup: SetupType) -> None:
    # GIVEN
    _, retailer, campaign = setup

    # WHEN
    resp = client.get(
        f"{settings.API_PREFIX}/{retailer.slug}/active-campaign-slugs",
        headers={"Authorization": "Token wrong token", "Bpl-User-Channel": "channel"},
    )

    # THEN
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert resp.json() == {
        "display_message": "Supplied token is invalid.",
        "error": "INVALID_TOKEN",
    }


def test_active_campaign_slugs_invalid_retailer(setup: SetupType) -> None:
    # GIVEN
    _, retailer, campaign = setup
    bad_retailer_slug = "wrong-merchant"

    # WHEN
    resp = client.get(
        f"{settings.API_PREFIX}/{bad_retailer_slug}/active-campaign-slugs",
        headers=auth_headers,
    )

    # THEN
    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert resp.json() == {"display_message": "Requested retailer is invalid.", "error": "INVALID_RETAILER"}


def test_active_campaign_slugs_no_active_campaigns(retailer: RetailerRewards) -> None:
    # WHEN
    resp = client.get(
        f"{settings.API_PREFIX}/{retailer.slug}/active-campaign-slugs",
        headers=auth_headers,
    )

    # THEN
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert resp.json() == {"display_message": "No active campaigns found for retailer.", "error": "NO_ACTIVE_CAMPAIGNS"}
