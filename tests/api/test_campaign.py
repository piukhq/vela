from datetime import datetime, timedelta
from typing import Callable, cast

import pytest

from fastapi import status as fastapi_http_status
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture
from requests import Response
from retry_tasks_lib.db.models import RetryTask, TaskType
from retry_tasks_lib.enums import RetryTaskStatuses
from sqlalchemy import delete
from sqlalchemy.future import select

from app.core.config import settings
from app.enums import CampaignStatuses, HttpErrors
from app.models import Campaign, EarnRule, RetailerRewards, RewardRule
from asgi import app
from tests.conftest import SetupType

client = TestClient(app, raise_server_exceptions=False)
auth_headers = {"Authorization": f"Token {settings.VELA_AUTH_TOKEN}", "Bpl-User-Channel": "channel"}


@pytest.fixture(scope="function")
def activable_campaign(setup: SetupType) -> Campaign:
    db_session, retailer, _ = setup
    campaign = Campaign(
        name="activable campaign",
        slug="activable-campaign",
        start_date=datetime.utcnow() - timedelta(days=-1),
        retailer_id=retailer.id,
    )
    db_session.add(campaign)
    db_session.flush()

    db_session.add(EarnRule(threshold=200, increment=100, increment_multiplier=1.5, campaign_id=campaign.id))
    db_session.add(RewardRule(reward_goal=150, voucher_type_slug="test-voucher-type", campaign_id=campaign.id))
    db_session.commit()
    return campaign


def validate_error_response(response: Response, error: HttpErrors) -> None:
    resp_json: dict = response.json()
    error_detail = cast(dict, error.value.detail)
    assert response.status_code == error.value.status_code
    assert resp_json["display_message"] == error_detail["display_message"]
    assert resp_json["code"] == error_detail["code"]


def validate_composite_error_response(response: Response, exptected_errors: list[dict]) -> None:
    for error, expected_error in zip(response.json(), exptected_errors):
        assert error["code"] == expected_error["code"]
        assert error["display_message"] == expected_error["display_message"]
        assert sorted(error["campaigns"]) == sorted(expected_error["campaigns"])


def test_update_campaign_active_status_to_ended(
    setup: SetupType,
    create_mock_campaign: Callable,
    reward_rule: RewardRule,
    voucher_status_adjustment_task_type: TaskType,
    delete_campaign_balances_task_type: TaskType,
    mocker: MockerFixture,
) -> None:
    db_session, retailer, campaign = setup
    payload = {
        "requested_status": "ended",
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

    import app.api.endpoints.campaign as endpoints_campaign

    spy = mocker.spy(endpoints_campaign, "enqueue_many_tasks")

    resp = client.post(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    activation_task = (
        db_session.execute(
            select(RetryTask).where(
                TaskType.task_type_id == RetryTask.task_type_id,
                TaskType.name == settings.VOUCHER_STATUS_ADJUSTMENT_TASK_NAME,
            )
        )
        .unique()
        .scalar_one()
    )

    assert resp.status_code == fastapi_http_status.HTTP_200_OK
    db_session.refresh(campaign)
    assert campaign.status == CampaignStatuses.ENDED
    spy.assert_called_once()
    assert activation_task.status == RetryTaskStatuses.PENDING


def test_update_multiple_campaigns_ok(
    setup: SetupType,
    create_mock_campaign: Callable,
    create_mock_reward_rule: Callable,
    reward_rule: RewardRule,
    voucher_status_adjustment_task_type: TaskType,
    create_campaign_balances_task_type: TaskType,
    delete_campaign_balances_task_type: TaskType,
    mocker: MockerFixture,
) -> None:
    """Test that multiple campaigns are handled, when they all transition to legal states"""
    db_session, retailer, campaign = setup
    # Set the first campaign to ACTIVE, this should transition to ENDED ok
    campaign.status = CampaignStatuses.ACTIVE
    db_session.commit()
    # Create second and third campaigns, along with reward rules
    second_campaign: Campaign = create_mock_campaign(
        **{
            "status": CampaignStatuses.ACTIVE,
            "name": "secondtestcampaign",
            "slug": "second-test-campaign",
        }
    )
    create_mock_reward_rule(voucher_type_slug="second-voucher-type", campaign_id=second_campaign.id)
    third_campaign: Campaign = create_mock_campaign(
        **{
            "status": CampaignStatuses.ACTIVE,
            "name": "thirdtestcampaign",
            "slug": "third-test-campaign",
        }
    )
    create_mock_reward_rule(voucher_type_slug="third-voucher-type", campaign_id=third_campaign.id)
    payload = {
        "requested_status": "ended",
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
    import app.api.endpoints.campaign as endpoints_campaign

    spy = mocker.spy(endpoints_campaign, "enqueue_many_tasks")
    resp = client.post(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    activation_tasks = (
        db_session.execute(
            select(RetryTask).where(
                TaskType.task_type_id == RetryTask.task_type_id,
                TaskType.name == settings.VOUCHER_STATUS_ADJUSTMENT_TASK_NAME,
            )
        )
        .unique()
        .scalars()
        .all()
    )

    assert resp.status_code == fastapi_http_status.HTTP_200_OK
    db_session.refresh(campaign)
    assert campaign.status == CampaignStatuses.ENDED
    db_session.refresh(second_campaign)
    assert second_campaign.status == CampaignStatuses.ENDED
    db_session.refresh(third_campaign)
    assert third_campaign.status == CampaignStatuses.ENDED
    spy.assert_called_once()
    assert len(activation_tasks) == 3
    for activation_task in activation_tasks:
        assert activation_task.status == RetryTaskStatuses.PENDING


def test_status_change_mangled_json(setup: SetupType) -> None:
    _, retailer, _ = setup

    resp = client.post(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/status_change",
        data=b"{",
        headers=auth_headers,
    )

    assert resp.status_code == fastapi_http_status.HTTP_400_BAD_REQUEST
    assert resp.json() == {
        "display_message": "Malformed request.",
        "code": "MALFORMED_REQUEST",
    }


def test_status_change_invalid_token(setup: SetupType) -> None:
    _, retailer, campaign = setup
    payload = {
        "requested_status": "ended",
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
        "requested_status": "ended",
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
        "requested_status": "ended",
        "campaign_slugs": ["WRONG_CAMPAIGN_SLUG_1", "WRONG_CAMPAIGN_SLUG_2"],
    }

    resp = client.post(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    assert resp.status_code == fastapi_http_status.HTTP_404_NOT_FOUND
    validate_composite_error_response(
        resp,
        [
            {
                "display_message": "Campaign not found for provided slug.",
                "code": "NO_CAMPAIGN_FOUND",
                "campaigns": payload["campaign_slugs"],
            }
        ],
    )


def test_status_change_campaign_does_not_belong_to_retailer(setup: SetupType, create_mock_retailer: Callable) -> None:
    db_session, retailer, campaign = setup
    campaign.status = CampaignStatuses.DRAFT  # Set to DRAFT just so the status transition requested won't trigger 409
    db_session.commit()
    payload = {
        "requested_status": "active",
        "campaign_slugs": [campaign.slug],  # legitimate slug
    }
    # Create a second retailer who should not be able to change status of the campaign above
    second_retailer: RetailerRewards = create_mock_retailer(
        **{
            "slug": "second-retailer",
        }
    )

    resp = client.post(
        f"{settings.API_PREFIX}/{second_retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    assert resp.status_code == fastapi_http_status.HTTP_404_NOT_FOUND
    validate_composite_error_response(
        resp,
        [
            {
                "display_message": "Campaign not found for provided slug.",
                "code": "NO_CAMPAIGN_FOUND",
                "campaigns": payload["campaign_slugs"],
            }
        ],
    )


@pytest.mark.parametrize("campaign_slugs", [["    ", " "], ["\t\t\t\r"], ["\t\t\t\n"], ["\t\n", "  "], [""]])
def test_status_change_whitespace_validation_fail_is_422(campaign_slugs: list, setup: SetupType) -> None:
    _, retailer, _ = setup
    payload = {
        "requested_status": "ended",
        "campaign_slugs": campaign_slugs,
    }

    resp = client.post(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    assert resp.status_code == fastapi_http_status.HTTP_422_UNPROCESSABLE_ENTITY
    assert resp.json() == {
        "display_message": "BPL Schema not matched.",
        "code": "INVALID_CONTENT",
    }


def test_status_change_empty_strings_and_legit_campaign(setup: SetupType) -> None:
    db_session, retailer, campaign = setup
    campaign.status = CampaignStatuses.ACTIVE
    db_session.commit()

    payload = {
        "requested_status": "ended",
        "campaign_slugs": [campaign.slug, "  "],
    }

    resp = client.post(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    assert resp.status_code == fastapi_http_status.HTTP_422_UNPROCESSABLE_ENTITY
    assert resp.json() == {
        "display_message": "BPL Schema not matched.",
        "code": "INVALID_CONTENT",
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

    assert resp.status_code == fastapi_http_status.HTTP_422_UNPROCESSABLE_ENTITY
    assert resp.json() == {
        "display_message": "BPL Schema not matched.",
        "code": "INVALID_CONTENT",
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
        "requested_status": "ended",
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

    assert resp.status_code == fastapi_http_status.HTTP_409_CONFLICT
    validate_composite_error_response(
        resp,
        [
            {
                "display_message": "The requested status change could not be performed.",
                "code": "INVALID_STATUS_REQUESTED",
                "campaigns": payload["campaign_slugs"],
            }
        ],
    )

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
        "requested_status": "cancelled",
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

    assert resp.status_code == fastapi_http_status.HTTP_409_CONFLICT
    db_session.refresh(campaign)
    assert campaign.status == CampaignStatuses.CANCELLED  # i.e. changed
    db_session.refresh(second_campaign)
    assert second_campaign.status == CampaignStatuses.DRAFT  # i.e. no change
    db_session.refresh(third_campaign)
    assert third_campaign.status == CampaignStatuses.ENDED  # i.e. no change

    validate_composite_error_response(
        resp,
        [
            {
                "display_message": "The requested status change could not be performed.",
                "code": "INVALID_STATUS_REQUESTED",
                "campaigns": [second_campaign.slug, third_campaign.slug],
            }
        ],
    )


def test_mixed_status_changes_with_illegal_states_and_campaign_slugs_not_belonging_to_retailer(
    setup: SetupType, create_mock_campaign: Callable, create_mock_retailer: Callable
) -> None:
    """
    Test that, where there are multiple campaigns and some will change to an illegal state,
    and some campaigns do not belong to the retailer (a 404 error),
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
        "requested_status": "cancelled",
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
    # Create a second retailer who will own a campaign_slug which will also be passed in
    second_retailer: RetailerRewards = create_mock_retailer(
        **{
            "slug": "second-retailer",
        }
    )
    # Set up an additional campaign owned by the second retailer, which on its own would give a 404 response
    second_retailer_owned_campaign = create_mock_campaign(
        **{
            "status": CampaignStatuses.ACTIVE,
            "name": "secondretailerownedcampaign",
            "slug": "second-retailer-owned-campaign",
            "retailer_id": second_retailer.id,
        }
    )
    # Add to the payload
    payload["campaign_slugs"].append(second_retailer_owned_campaign.slug)  # type: ignore [attr-defined]

    resp = client.post(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    assert resp.status_code == fastapi_http_status.HTTP_409_CONFLICT
    validate_composite_error_response(
        resp,
        [
            {
                "display_message": "Campaign not found for provided slug.",
                "code": "NO_CAMPAIGN_FOUND",
                "campaigns": [
                    "NON_EXISTENT_CAMPAIGN_1",
                    "NON_EXISTENT_CAMPAIGN_2",
                    second_retailer_owned_campaign.slug,
                ],
            },
            {
                "display_message": "The requested status change could not be performed.",
                "code": "INVALID_STATUS_REQUESTED",
                "campaigns": [second_campaign.slug, third_campaign.slug],
            },
        ],
    )


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
        "requested_status": "cancelled",
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

    assert resp.status_code == fastapi_http_status.HTTP_409_CONFLICT
    db_session.refresh(campaign)
    assert campaign.status == CampaignStatuses.CANCELLED  # i.e. changed
    db_session.refresh(second_campaign)
    assert second_campaign.status == CampaignStatuses.DRAFT  # i.e. no change
    db_session.refresh(third_campaign)
    assert third_campaign.status == CampaignStatuses.ENDED  # i.e. no change

    validate_composite_error_response(
        resp,
        [
            {
                "display_message": "Campaign not found for provided slug.",
                "code": "NO_CAMPAIGN_FOUND",
                "campaigns": ["NON_EXISTENT_CAMPAIGN_1", "NON_EXISTENT_CAMPAIGN_2"],
            },
            {
                "display_message": "The requested status change could not be performed.",
                "code": "INVALID_STATUS_REQUESTED",
                "campaigns": [second_campaign.slug, third_campaign.slug],
            },
        ],
    )


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
        "requested_status": "ended",
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
        "requested_status": "ended",
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


def test_activating_a_campaign(
    setup: SetupType,
    activable_campaign: Campaign,
    create_mock_reward_rule: Callable,
    voucher_status_adjustment_task_type: TaskType,
    create_campaign_balances_task_type: TaskType,
    mocker: MockerFixture,
) -> None:
    db_session, retailer, _ = setup

    import app.api.endpoints.campaign as endpoints_campaign

    spy = mocker.spy(endpoints_campaign, "enqueue_many_tasks")

    create_mock_reward_rule(voucher_type_slug="activable-voucher-type", campaign_id=activable_campaign.id)
    payload = {
        "requested_status": "active",
        "campaign_slugs": [activable_campaign.slug],
    }

    resp = client.post(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    activation_task = (
        db_session.execute(
            select(RetryTask).where(
                TaskType.task_type_id == RetryTask.task_type_id,
                TaskType.name == settings.VOUCHER_STATUS_ADJUSTMENT_TASK_NAME,
            )
        )
        .unique()
        .scalar_one()
    )
    assert resp.status_code == fastapi_http_status.HTTP_200_OK
    db_session.refresh(activable_campaign)
    assert activable_campaign.status == CampaignStatuses.ACTIVE
    spy.assert_called_once()
    assert activation_task.status == RetryTaskStatuses.PENDING


def test_activating_a_campaign_with_no_earn_rules(setup: SetupType, activable_campaign: Campaign) -> None:
    db_session, retailer, _ = setup

    db_session.execute(delete(EarnRule).where(EarnRule.id.in_([rule.id for rule in activable_campaign.earn_rules])))
    db_session.commit()

    payload = {
        "requested_status": "active",
        "campaign_slugs": [activable_campaign.slug],
    }

    resp = client.post(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    assert resp.status_code == fastapi_http_status.HTTP_409_CONFLICT
    validate_composite_error_response(
        resp,
        [
            {
                "display_message": "the provided campaign(s) could not be made active",
                "code": "MISSING_CAMPAIGN_COMPONENTS",
                "campaigns": payload["campaign_slugs"],
            },
        ],
    )

    db_session.refresh(activable_campaign)
    assert activable_campaign.status == CampaignStatuses.DRAFT


def test_activating_a_campaign_with_no_reward_rule(setup: SetupType, activable_campaign: Campaign) -> None:
    db_session, retailer, _ = setup

    db_session.execute(delete(RewardRule).where(RewardRule.id.in_([rule.id for rule in activable_campaign.earn_rules])))
    db_session.commit()

    payload = {
        "requested_status": "active",
        "campaign_slugs": [activable_campaign.slug],
    }

    resp = client.post(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    assert resp.status_code == fastapi_http_status.HTTP_409_CONFLICT
    validate_composite_error_response(
        resp,
        [
            {
                "display_message": "the provided campaign(s) could not be made active",
                "code": "MISSING_CAMPAIGN_COMPONENTS",
                "campaigns": payload["campaign_slugs"],
            },
        ],
    )

    db_session.refresh(activable_campaign)
    assert activable_campaign.status == CampaignStatuses.DRAFT


def test_activating_a_campaign_with_no_reward_rule_multiple_errors(
    setup: SetupType, activable_campaign: Campaign
) -> None:
    db_session, retailer, campaign = setup

    campaign.status = CampaignStatuses.CANCELLED
    db_session.execute(delete(RewardRule).where(RewardRule.id.in_([rule.id for rule in activable_campaign.earn_rules])))
    db_session.commit()

    payload = {
        "requested_status": "active",
        "campaign_slugs": [campaign.slug, activable_campaign.slug],
    }

    resp = client.post(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    assert resp.status_code == fastapi_http_status.HTTP_409_CONFLICT
    validate_composite_error_response(
        resp,
        [
            {
                "display_message": "The requested status change could not be performed.",
                "code": "INVALID_STATUS_REQUESTED",
                "campaigns": [campaign.slug],
            },
            {
                "display_message": "the provided campaign(s) could not be made active",
                "code": "MISSING_CAMPAIGN_COMPONENTS",
                "campaigns": [activable_campaign.slug],
            },
        ],
    )

    db_session.refresh(activable_campaign)
    assert activable_campaign.status == CampaignStatuses.DRAFT
