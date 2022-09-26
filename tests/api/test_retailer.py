from collections import namedtuple
from typing import TYPE_CHECKING, Any, Generator

import pytest

from fastapi.testclient import TestClient
from sqlalchemy.exc import StatementError
from sqlalchemy.future import select
from starlette import status

from asgi import app
from vela.core.config import settings
from vela.enums import RewardCap
from vela.models import Campaign, RetailerRewards
from vela.models.retailer import RewardRule

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

SetupType = namedtuple("SetupType", ["db_session", "retailer", "campaign"])

client = TestClient(app)
auth_headers = {"Authorization": f"Token {settings.VELA_API_AUTH_TOKEN}", "Bpl-User-Channel": "channel"}


@pytest.fixture(scope="function")
def setup(db_session: "Session", retailer: RetailerRewards, campaign: Campaign) -> Generator[SetupType, None, None]:
    yield SetupType(db_session, retailer, campaign)


def test_healthz_routes_no_channel_header() -> None:
    paths = ("/readyz", "/livez")
    headers: dict[str, Any] = {}
    for path in paths:
        resp = client.get(path, headers=headers)
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
    retailer = setup.retailer

    # WHEN
    resp = client.get(
        f"{settings.API_PREFIX}/{retailer.slug}/active-campaign-slugs",
        headers={"Authorization": "Token wrong token", "Bpl-User-Channel": "channel"},
    )

    # THEN
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert resp.json() == {
        "display_message": "Supplied token is invalid.",
        "code": "INVALID_TOKEN",
    }


def test_active_campaign_slugs_invalid_retailer(setup: SetupType) -> None:
    # GIVEN
    bad_retailer_slug = "wrong-merchant"

    # WHEN
    resp = client.get(
        f"{settings.API_PREFIX}/{bad_retailer_slug}/active-campaign-slugs",
        headers=auth_headers,
    )

    # THEN
    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert resp.json() == {"display_message": "Requested retailer is invalid.", "code": "INVALID_RETAILER"}


def test_active_campaign_slugs_no_active_campaigns(retailer: RetailerRewards) -> None:
    # WHEN
    resp = client.get(
        f"{settings.API_PREFIX}/{retailer.slug}/active-campaign-slugs",
        headers=auth_headers,
    )

    # THEN
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert resp.json() == {"display_message": "No active campaigns found for retailer.", "code": "NO_ACTIVE_CAMPAIGNS"}


def test_reward_cap_enum(setup: SetupType, reward_rule: RewardRule) -> None:
    db_session = setup.db_session
    reward_rule.reward_cap = RewardCap.FIVE
    db_session.commit()

    reward_cap_from_db = db_session.execute(select(RewardRule.reward_cap)).scalar_one_or_none()

    assert reward_cap_from_db == RewardCap.FIVE
    assert reward_cap_from_db.value == 5


def test_reward_cap_enum_invalid(setup: SetupType, reward_rule: RewardRule) -> None:
    db_session = setup.db_session
    invalid_reward_cap = 11

    with pytest.raises(StatementError) as exc_info:
        reward_rule.reward_cap = invalid_reward_cap
        db_session.commit()

    assert (
        exc_info.value.orig.args[0]
        == f"'{invalid_reward_cap}' is not among the defined enum values. Enum name: rewardcap."
        " Possible values: 1, 2, 3, ..., 10"
    )
