from typing import Callable

import pytest

from fastapi.testclient import TestClient
from requests import Response
from starlette import status as starlette_http_status

from app.core.config import settings
from app.enums import CampaignStatuses, HttpErrors
from app.models import Campaign
from asgi import app
from tests.api.conftest import SetupType

client = TestClient(app)
auth_headers = {"Authorization": f"Token {settings.VELA_AUTH_TOKEN}", "Bpl-User-Channel": "channel"}


def validate_error_response(response: Response, error: HttpErrors) -> None:
    assert response.status_code == error.value.status_code
    assert response.json()["display_message"] == error.value.detail["display_message"]
    assert response.json()["error"] == error.value.detail["error"]


def test_update_campaign_active_status_to_ended(setup: SetupType, create_mock_campaign: Callable) -> None:
    db_session, retailer, campaign = setup
    payload = {
        "requested_status": "Ended",
        "campaign_slugs": [campaign.slug],
    }
    campaign.status = CampaignStatuses.ACTIVE
    db_session.commit()

    # Set up a second ACTIVE campaign just so we don't end up with no current ACTIVE campaigns (would produce 409 error)
    create_mock_campaign(
        **{
            "status": CampaignStatuses.ACTIVE,
            "name": "secondtestcampaign",
            "slug": "second-test-campaign",
        }
    )

    resp = client.post(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    assert resp.status_code == starlette_http_status.HTTP_200_OK
    db_session.refresh(campaign)
    assert campaign.status == CampaignStatuses.ENDED


def test_update_multiple_campaigns_ok(setup: SetupType, create_mock_campaign: Callable) -> None:
    """Test that multiple campaigns are handled, when they all transition to legal states"""
    db_session, retailer, campaign = setup
    # Set the first campaign to ACTIVE, this should transition to ENDED ok
    campaign.status = CampaignStatuses.ACTIVE
    db_session.commit()
    # Create second and third campaigns
    second_campaign: Campaign = create_mock_campaign(
        **{
            "status": CampaignStatuses.ACTIVE,
            "name": "secondtestcampaign",
            "slug": "second-test-campaign",
        }
    )
    third_campaign: Campaign = create_mock_campaign(
        **{
            "status": CampaignStatuses.ACTIVE,
            "name": "thirdtestcampaign",
            "slug": "third-test-campaign",
        }
    )
    payload = {
        "requested_status": "Ended",
        "campaign_slugs": [campaign.slug, second_campaign.slug, third_campaign.slug],
    }
    # Set up a fourth ACTIVE campaign just so we don't end up with no current ACTIVE campaigns (would produce 409 error)
    create_mock_campaign(
        **{
            "status": CampaignStatuses.ACTIVE,
            "name": "fourthtestcampaign",
            "slug": "fourth-test-campaign",
        }
    )

    resp = client.post(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    assert resp.status_code == starlette_http_status.HTTP_200_OK
    db_session.refresh(campaign)
    assert campaign.status == CampaignStatuses.ENDED
    db_session.refresh(second_campaign)
    assert second_campaign.status == CampaignStatuses.ENDED
    db_session.refresh(third_campaign)
    assert third_campaign.status == CampaignStatuses.ENDED


def test_status_change_mangled_json(setup: SetupType) -> None:
    _, retailer, _ = setup

    resp = client.post(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/status_change",
        data=b"{",
        headers=auth_headers,
    )

    assert resp.status_code == starlette_http_status.HTTP_400_BAD_REQUEST
    assert resp.json() == {
        "display_message": "Malformed request.",
        "error": "MALFORMED_REQUEST",
    }


def test_status_change_invalid_token(setup: SetupType) -> None:
    _, retailer, campaign = setup
    payload = {
        "requested_status": "Ended",
        "campaign_slugs": [campaign.slug],
    }

    resp = client.post(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers={"Authorization": "Token wrong token"},
    )

    validate_error_response(resp, HttpErrors.INVALID_TOKEN)


def test_status_change_invalid_retailer(setup: SetupType) -> None:
    _, _, campaign = setup
    payload = {
        "requested_status": "Ended",
        "campaign_slugs": [campaign.slug],
    }
    bad_retailer = "WRONG_RETAILER"

    resp = client.post(
        f"{settings.API_PREFIX}/{bad_retailer}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    validate_error_response(resp, HttpErrors.INVALID_RETAILER)


def test_status_change_none_of_the_campaigns_are_found(setup: SetupType) -> None:
    _, retailer, _ = setup
    payload = {
        "requested_status": "Ended",
        "campaign_slugs": ["WRONG_CAMPAIGN_SLUG_1", "WRONG_CAMPAIGN_SLUG_2"],
    }

    resp = client.post(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    validate_error_response(resp, HttpErrors.NO_CAMPAIGN_FOUND)


@pytest.mark.parametrize("campaign_slugs", [["    ", " "], ["\t\t\t\r"], ["\t\t\t\n"], ["\t\n", "  "]])
def test_status_change_whitespace_validation_fail_is_422(campaign_slugs: list, setup: SetupType) -> None:
    _, retailer, _ = setup
    payload = {
        "requested_status": "Ended",
        "campaign_slugs": campaign_slugs,
    }

    resp = client.post(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    assert resp.status_code == starlette_http_status.HTTP_422_UNPROCESSABLE_ENTITY
    assert resp.json() == {
        "display_message": "BPL Schema not matched.",
        "error": "INVALID_CONTENT",
    }


def test_status_change_empty_strings_and_legit_campaign(setup: SetupType) -> None:
    db_session, retailer, campaign = setup
    campaign.status = CampaignStatuses.ACTIVE
    db_session.commit()

    payload = {
        "requested_status": "Ended",
        "campaign_slugs": [campaign.slug, "  "],
    }

    resp = client.post(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    assert resp.status_code == starlette_http_status.HTTP_422_UNPROCESSABLE_ENTITY
    assert resp.json() == {
        "display_message": "BPL Schema not matched.",
        "error": "INVALID_CONTENT",
    }
    db_session.refresh(campaign)
    assert campaign.status == CampaignStatuses.ACTIVE  # i.e. not changed


def test_status_change_fields_fail_validation(setup: SetupType) -> None:
    db_session, retailer, campaign = setup
    payload = {
        "requested_status": "BAD_ACTION_TYPE",
        "campaign_slugs": [campaign.slug],
    }

    campaign.status = CampaignStatuses.ACTIVE
    db_session.commit()

    resp = client.post(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    assert resp.status_code == starlette_http_status.HTTP_422_UNPROCESSABLE_ENTITY
    assert resp.json() == {
        "display_message": "BPL Schema not matched.",
        "error": "INVALID_CONTENT",
    }


def test_status_change_all_are_illegal_states(setup: SetupType, create_mock_campaign: Callable) -> None:
    db_session, retailer, campaign = setup
    campaign.status = CampaignStatuses.DRAFT
    db_session.commit()
    # Create second campaign
    second_campaign: Campaign = create_mock_campaign(
        **{
            "status": CampaignStatuses.DRAFT,
            "name": "secondtestcampaign",
            "slug": "second-test-campaign",
        }
    )
    payload = {
        "requested_status": "Ended",
        "campaign_slugs": [campaign.slug, second_campaign.slug],
    }
    # Set up an additional ACTIVE campaign just so we don't end up with no current ACTIVE campaigns
    # (would produce an unrelated 409 error)
    create_mock_campaign(
        **{
            "status": CampaignStatuses.ACTIVE,
            "name": "thirdtestcampaign",
            "slug": "third-test-campaign",
        }
    )

    resp = client.post(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    validate_error_response(resp, HttpErrors.INVALID_STATUS_REQUESTED)
    db_session.refresh(campaign)
    assert campaign.status == CampaignStatuses.DRAFT


def test_mixed_status_changes_to_legal_and_illegal_states(setup: SetupType, create_mock_campaign: Callable) -> None:
    """
    Test that, where there are multiple campaigns and some will change to an illegal state,
    Vela returns a 409 and an error message is displayed to advise of any illegal state changes.
    Test that the legal campaign state change(s) are applied and that the illegal campaign state change(s) are not made
    """
    db_session, retailer, campaign = setup
    campaign.status = CampaignStatuses.ACTIVE  # This should transition to ENDED ok
    db_session.commit()
    # Create second and third campaigns
    second_campaign: Campaign = create_mock_campaign(
        **{
            "status": CampaignStatuses.DRAFT,  # This should fail validation, can't go from DRAFT to CANCELLED
            "name": "secondtestcampaign",
            "slug": "second-test-campaign",
        }
    )
    third_campaign: Campaign = create_mock_campaign(
        **{
            "status": CampaignStatuses.ENDED,  # This should fail validation, can't go from ENDED to CANCELLED
            "name": "thirdtestcampaign",
            "slug": "third-test-campaign",
        }
    )
    payload = {
        "requested_status": "Cancelled",
        "campaign_slugs": [campaign.slug, second_campaign.slug, third_campaign.slug],
    }
    # Set up an additional ACTIVE campaign just so we don't end up with no current ACTIVE campaigns
    # (would produce 409 error)
    create_mock_campaign(
        **{
            "status": CampaignStatuses.ACTIVE,
            "name": "fourthtestcampaign",
            "slug": "fourth-test-campaign",
        }
    )

    resp = client.post(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    assert resp.status_code == starlette_http_status.HTTP_409_CONFLICT
    db_session.refresh(campaign)
    assert campaign.status == CampaignStatuses.CANCELLED  # i.e. changed
    db_session.refresh(second_campaign)
    assert second_campaign.status == CampaignStatuses.DRAFT  # i.e. no change
    db_session.refresh(third_campaign)
    assert third_campaign.status == CampaignStatuses.ENDED  # i.e. no change
    assert resp.json()["display_message"] == "Not all campaigns were updated as requested."
    assert resp.json()["error"] == "INCOMPLETE_STATUS_UPDATE"
    failed_campaigns: list[str] = resp.json()["failed_campaigns"]
    assert len(failed_campaigns) == 2
    assert second_campaign.slug in failed_campaigns
    assert third_campaign.slug in failed_campaigns


def test_mixed_status_changes_with_illegal_states_and_no_campaign_found(
    setup: SetupType, create_mock_campaign: Callable
) -> None:
    """
    Test that, where there are multiple campaigns and some will change to an illegal state,
    and some campaigns are not found,
    Vela returns a 409 and an error message is displayed to advise of any illegal state changes.
    Test that the legal campaign state change(s) are applied and that the illegal campaign state change(s) are not made
    """
    db_session, retailer, campaign = setup
    campaign.status = CampaignStatuses.ACTIVE  # This should transition to ENDED ok
    db_session.commit()
    # Create second and third campaigns
    second_campaign: Campaign = create_mock_campaign(
        **{
            "status": CampaignStatuses.DRAFT,  # This should fail validation, can't go from DRAFT to CANCELLED
            "name": "secondtestcampaign",
            "slug": "second-test-campaign",
        }
    )
    third_campaign: Campaign = create_mock_campaign(
        **{
            "status": CampaignStatuses.ENDED,  # This should fail validation, can't go from ENDED to CANCELLED
            "name": "thirdtestcampaign",
            "slug": "third-test-campaign",
        }
    )
    payload = {
        "requested_status": "Cancelled",
        "campaign_slugs": [
            campaign.slug,
            second_campaign.slug,
            third_campaign.slug,
            "NON_EXISTENT_CAMPAIGN_1",
            "NON_EXISTENT_CAMPAIGN_2",
        ],
    }
    # Set up an additional ACTIVE campaign just so we don't end up with no current ACTIVE campaigns
    # (would produce 409 error)
    create_mock_campaign(
        **{
            "status": CampaignStatuses.ACTIVE,
            "name": "fourthtestcampaign",
            "slug": "fourth-test-campaign",
        }
    )

    resp = client.post(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    assert resp.status_code == starlette_http_status.HTTP_409_CONFLICT
    db_session.refresh(campaign)
    assert campaign.status == CampaignStatuses.CANCELLED  # i.e. changed
    db_session.refresh(second_campaign)
    assert second_campaign.status == CampaignStatuses.DRAFT  # i.e. no change
    db_session.refresh(third_campaign)
    assert third_campaign.status == CampaignStatuses.ENDED  # i.e. no change
    assert resp.json()["display_message"] == "Not all campaigns were updated as requested."
    assert resp.json()["error"] == "INCOMPLETE_STATUS_UPDATE"
    failed_campaigns: list[str] = resp.json()["failed_campaigns"]
    assert len(failed_campaigns) == 4
    assert second_campaign.slug in failed_campaigns
    assert third_campaign.slug in failed_campaigns
    assert "NON_EXISTENT_CAMPAIGN_1" in failed_campaigns
    assert "NON_EXISTENT_CAMPAIGN_2" in failed_campaigns


def test_leaving_no_active_campaigns_gives_error(setup: SetupType, create_mock_campaign: Callable) -> None:
    """Test that a request to end all ACTIVE campaigns results in a 409 error"""
    db_session, retailer, campaign = setup
    # Set the first campaign to ACTIVE, this should transition to ENDED ok
    campaign.status = CampaignStatuses.ACTIVE
    db_session.commit()
    # Create second and third campaigns
    second_campaign: Campaign = create_mock_campaign(
        **{
            "status": CampaignStatuses.ACTIVE,
            "name": "secondtestcampaign",
            "slug": "second-test-campaign",
        }
    )
    third_campaign: Campaign = create_mock_campaign(
        **{
            "status": CampaignStatuses.ACTIVE,
            "name": "thirdtestcampaign",
            "slug": "third-test-campaign",
        }
    )
    payload = {
        "requested_status": "Ended",
        "campaign_slugs": [campaign.slug, second_campaign.slug, third_campaign.slug],
    }

    resp = client.post(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    validate_error_response(resp, HttpErrors.INVALID_STATUS_REQUESTED)
    db_session.refresh(campaign)
    assert campaign.status == CampaignStatuses.ACTIVE
    db_session.refresh(second_campaign)
    assert second_campaign.status == CampaignStatuses.ACTIVE
    db_session.refresh(third_campaign)
    assert third_campaign.status == CampaignStatuses.ACTIVE


def test_having_no_active_campaigns_gives_invalid_status_error(
    setup: SetupType, create_mock_campaign: Callable
) -> None:
    """From this endpoint, you should get an invalid status requested error if you currently have no active campaigns"""
    db_session, retailer, campaign = setup
    campaign.status = CampaignStatuses.DRAFT
    db_session.commit()
    # Create second campaign
    second_campaign: Campaign = create_mock_campaign(
        **{
            "status": CampaignStatuses.DRAFT,
            "name": "secondtestcampaign",
            "slug": "second-test-campaign",
        }
    )
    payload = {
        "requested_status": "Ended",
        "campaign_slugs": [campaign.slug, second_campaign.slug],
    }

    resp = client.post(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    validate_error_response(resp, HttpErrors.INVALID_STATUS_REQUESTED)
    db_session.refresh(campaign)
    assert campaign.status == CampaignStatuses.DRAFT
    db_session.refresh(second_campaign)
    assert second_campaign.status == CampaignStatuses.DRAFT
