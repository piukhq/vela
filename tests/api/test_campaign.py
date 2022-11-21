# pylint: disable=too-many-arguments,too-many-locals,import-outside-toplevel,too-many-lines

from datetime import datetime, timedelta, timezone
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

from asgi import app
from tests.conftest import SetupType
from vela.core.config import settings
from vela.enums import CampaignStatuses, HttpErrors
from vela.models import Campaign, EarnRule, RetailerRewards, RewardRule

client = TestClient(app, raise_server_exceptions=False)
auth_headers = {"Authorization": f"Token {settings.VELA_API_AUTH_TOKEN}", "Bpl-User-Channel": "channel"}


@pytest.fixture(scope="function")
def activable_campaign(setup: SetupType) -> Campaign:
    db_session, retailer, _ = setup
    campaign = Campaign(
        name="activable campaign",
        slug="activable-campaign",
        start_date=datetime.now(tz=timezone.utc) - timedelta(days=-1),
        retailer_id=retailer.id,
    )
    db_session.add(campaign)
    db_session.flush()

    db_session.add(EarnRule(threshold=200, increment=100, increment_multiplier=1.5, campaign_id=campaign.id))
    db_session.add(RewardRule(reward_goal=150, reward_slug="test-reward-type", campaign_id=campaign.id))
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
    delete_campaign_balances_task_type: TaskType,
    mocker: MockerFixture,
) -> None:
    db_session, retailer, campaign = setup

    mock_datetime = mocker.patch("vela.api.endpoints.campaign.datetime")
    mock_put_carina_campaign = mocker.patch(
        "vela.api.endpoints.campaign.put_carina_campaign",
        return_value=(fastapi_http_status.HTTP_200_OK, "Carina responded with: 200"),
    )
    mock_enqueue_many_tasks = mocker.patch("vela.api.endpoints.campaign.enqueue_many_tasks")

    fake_now = datetime.now(tz=timezone.utc)
    mock_datetime.now.return_value = fake_now
    payload = {
        "requested_status": "ended",
        "campaign_slugs": [campaign.slug],
        "activity_metadata": {"sso_username": "Jane Doe"},
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

    # Check which tasks were created
    delete_campaign_balances_task_id = (
        db_session.execute(
            select(RetryTask.retry_task_id).where(
                TaskType.task_type_id == RetryTask.task_type_id,
                TaskType.name == settings.DELETE_CAMPAIGN_BALANCES_TASK_NAME,
            )
        )
        .unique()
        .scalar_one()
    )

    expected_status_code = fastapi_http_status.HTTP_200_OK
    assert resp.status_code == expected_status_code
    assert resp.json() == {}

    # PUT /campaign call to carina
    mock_put_carina_campaign.assert_called_once_with(
        retailer_slug=retailer.slug,
        campaign_slug=campaign.slug,
        reward_slug=reward_rule.reward_slug,
        requested_status=payload["requested_status"],
    )
    db_session.refresh(campaign)
    assert campaign.status == CampaignStatuses.ENDED
    assert campaign.end_date == fake_now.replace(tzinfo=None)
    mock_enqueue_many_tasks.assert_called_once_with(retry_tasks_ids=[delete_campaign_balances_task_id])


def test_update_multiple_campaigns_ok(
    setup: SetupType,
    create_mock_campaign: Callable,
    create_mock_reward_rule: Callable,
    reward_rule: RewardRule,
    create_campaign_balances_task_type: TaskType,
    delete_campaign_balances_task_type: TaskType,
    mocker: MockerFixture,
) -> None:
    """Test that multiple campaigns are handled, when they all transition to legal states"""
    db_session, retailer, campaign = setup

    mock_datetime = mocker.patch("vela.api.endpoints.campaign.datetime")
    mock_put_carina_campaign = mocker.patch(
        "vela.api.endpoints.campaign.put_carina_campaign",
        return_value=(fastapi_http_status.HTTP_200_OK, "Carina responded with: 200"),
    )
    mock_enqueue_many_tasks = mocker.patch("vela.api.endpoints.campaign.enqueue_many_tasks")

    fake_now = datetime.now(tz=timezone.utc)
    mock_datetime.now.return_value = fake_now
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
    create_mock_reward_rule(reward_slug="second-reward-type", campaign_id=second_campaign.id)
    third_campaign: Campaign = create_mock_campaign(
        **{
            "status": CampaignStatuses.ACTIVE,
            "name": "thirdtestcampaign",
            "slug": "third-test-campaign",
        }
    )
    create_mock_reward_rule(reward_slug="third-reward-type", campaign_id=third_campaign.id)
    campaigns_to_update = [campaign.slug, second_campaign.slug, third_campaign.slug]
    payload = {
        "requested_status": "ended",
        "campaign_slugs": campaigns_to_update,
        "activity_metadata": {"sso_username": "Jane Doe"},
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

    delete_campaign_balances_task_ids = (
        db_session.execute(
            select(RetryTask.retry_task_id).where(
                TaskType.task_type_id == RetryTask.task_type_id,
                TaskType.name == settings.DELETE_CAMPAIGN_BALANCES_TASK_NAME,
            )
        )
        .unique()
        .scalars()
        .all()
    )

    assert resp.status_code == fastapi_http_status.HTTP_200_OK
    db_session.refresh(campaign)
    assert campaign.status == CampaignStatuses.ENDED
    assert campaign.end_date == fake_now.replace(tzinfo=None)
    db_session.refresh(second_campaign)
    assert second_campaign.status == CampaignStatuses.ENDED
    assert second_campaign.end_date == fake_now.replace(tzinfo=None)
    db_session.refresh(third_campaign)
    assert third_campaign.status == CampaignStatuses.ENDED
    assert third_campaign.end_date == fake_now.replace(tzinfo=None)
    mock_enqueue_many_tasks.assert_called_once_with(retry_tasks_ids=delete_campaign_balances_task_ids)
    assert len(delete_campaign_balances_task_ids) == len(campaigns_to_update)

    assert mock_put_carina_campaign.call_count == len(campaigns_to_update)


def test_status_change_mangled_json(setup: SetupType) -> None:
    retailer = setup.retailer

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
    campaign = setup.campaign
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
    retailer = setup.retailer
    payload = {
        "requested_status": "ended",
        "campaign_slugs": ["WRONG_CAMPAIGN_SLUG_1", "WRONG_CAMPAIGN_SLUG_2"],
        "activity_metadata": {"sso_username": "Jane Doe"},
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
    db_session, _, campaign = setup
    campaign.status = CampaignStatuses.DRAFT  # Set to DRAFT just so the status transition requested won't trigger 409
    db_session.commit()
    payload = {
        "requested_status": "active",
        "campaign_slugs": [campaign.slug],  # legitimate slug
        "activity_metadata": {"sso_username": "Jane Doe"},
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
    retailer = setup.retailer
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
        "activity_metadata": {"sso_username": "Jane Doe"},
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


def test_mixed_status_changes_to_legal_and_illegal_states(
    setup: SetupType,
    create_mock_campaign: Callable,
    reward_rule: RewardRule,
    account_holder_cancel_reward_task_type: TaskType,
    delete_campaign_balances_task_type: TaskType,
    mocker: MockerFixture,
) -> None:
    """
    Test that, where there are multiple campaigns and some will change to an illegal state,
    Vela returns a 409 and an error message is displayed to advise of any illegal state changes.
    Test that the legal campaign state change(s) are applied and that the illegal campaign state change(s) are not made
    """
    db_session, retailer, campaign = setup

    mock_put_carina_campaign = mocker.patch(
        "vela.api.endpoints.campaign.put_carina_campaign",
        return_value=(fastapi_http_status.HTTP_200_OK, "Carina responded with: 200"),
    )
    mock_enqueue_many_tasks = mocker.patch("vela.api.endpoints.campaign.enqueue_many_tasks")

    campaign.status = CampaignStatuses.ACTIVE  # This should transition to CANCELLED ok
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
        "activity_metadata": {"sso_username": "Jane Doe"},
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

    reward_cancel_task_id = (
        db_session.execute(
            select(RetryTask.retry_task_id).where(
                TaskType.task_type_id == RetryTask.task_type_id,
                TaskType.name == settings.REWARD_CANCELLATION_TASK_NAME,
            )
        )
        .unique()
        .scalar_one_or_none()
    )

    deletion_task_id = (
        db_session.execute(
            select(RetryTask.retry_task_id).where(
                TaskType.task_type_id == RetryTask.task_type_id,
                TaskType.name == settings.DELETE_CAMPAIGN_BALANCES_TASK_NAME,
            )
        )
        .unique()
        .scalar_one()
    )

    assert resp.status_code == fastapi_http_status.HTTP_409_CONFLICT
    db_session.refresh(campaign)

    # Check that Campaign change for the first campaign was successful
    mock_put_carina_campaign.assert_called_once_with(
        retailer_slug=retailer.slug,
        campaign_slug=campaign.slug,
        reward_slug=reward_rule.reward_slug,
        requested_status=payload["requested_status"],
    )
    mock_enqueue_many_tasks.assert_called_once_with(retry_tasks_ids=[reward_cancel_task_id, deletion_task_id])
    assert campaign.status == CampaignStatuses.CANCELLED  # i.e. changed

    # Check that second and third failed validation and no status change
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
    setup: SetupType,
    create_mock_campaign: Callable,
    create_mock_retailer: Callable,
    reward_rule: RewardRule,
    account_holder_cancel_reward_task_type: TaskType,
    delete_campaign_balances_task_type: TaskType,
    mocker: MockerFixture,
) -> None:
    """
    Test that, where there are multiple campaigns and some will change to an illegal state,
    and some campaigns do not belong to the retailer (a 404 error),
    Vela returns a 409 and an error message is displayed to advise of any illegal state changes.
    Test that the legal campaign state change(s) are applied and that the illegal campaign state change(s) are not made
    """
    db_session, retailer, campaign = setup

    mock_put_carina_campaign = mocker.patch(
        "vela.api.endpoints.campaign.put_carina_campaign",
        return_value=(fastapi_http_status.HTTP_200_OK, "Carina responded with: 200"),
    )
    mock_enqueue_many_tasks = mocker.patch("vela.api.endpoints.campaign.enqueue_many_tasks")

    campaign.status = CampaignStatuses.ACTIVE  # This should transition to CANCELLED ok
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
        "activity_metadata": {"sso_username": "Jane Doe"},
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

    reward_cancel_task_id = (
        db_session.execute(
            select(RetryTask.retry_task_id).where(
                TaskType.task_type_id == RetryTask.task_type_id,
                TaskType.name == settings.REWARD_CANCELLATION_TASK_NAME,
            )
        )
        .unique()
        .scalar_one()
    )

    deletion_task_id = (
        db_session.execute(
            select(RetryTask.retry_task_id).where(
                TaskType.task_type_id == RetryTask.task_type_id,
                TaskType.name == settings.DELETE_CAMPAIGN_BALANCES_TASK_NAME,
            )
        )
        .unique()
        .scalar_one()
    )

    db_session.refresh(campaign)
    # Check that Campaign change for the first campaign was successful
    mock_put_carina_campaign.assert_called_once_with(
        retailer_slug=retailer.slug,
        campaign_slug=campaign.slug,
        reward_slug=reward_rule.reward_slug,
        requested_status=payload["requested_status"],
    )
    mock_enqueue_many_tasks.assert_called_once_with(retry_tasks_ids=[reward_cancel_task_id, deletion_task_id])
    assert campaign.status == CampaignStatuses.CANCELLED  # i.e. changed

    # Check that second and third failed validation and no status change
    db_session.refresh(second_campaign)
    assert second_campaign.status == CampaignStatuses.DRAFT  # i.e. no change
    db_session.refresh(third_campaign)
    assert third_campaign.status == CampaignStatuses.ENDED  # i.e. no change
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
    setup: SetupType,
    create_mock_campaign: Callable,
    reward_rule: RewardRule,
    account_holder_cancel_reward_task_type: TaskType,
    delete_campaign_balances_task_type: TaskType,
    mocker: MockerFixture,
) -> None:
    """
    Test that, where there are multiple campaigns and some will change to an illegal state,
    and some campaigns are not found,
    Vela returns a 409 and an error message is displayed to advise of any illegal state changes.
    Test that the legal campaign state change(s) are applied and that the illegal campaign state change(s) are not made
    """
    db_session, retailer, campaign = setup

    mock_put_carina_campaign = mocker.patch(
        "vela.api.endpoints.campaign.put_carina_campaign",
        return_value=(fastapi_http_status.HTTP_200_OK, "Carina responded with: 200"),
    )
    mock_enqueue_many_tasks = mocker.patch("vela.api.endpoints.campaign.enqueue_many_tasks")

    campaign.status = CampaignStatuses.ACTIVE  # This should transition to CANCELLED ok
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
        "activity_metadata": {"sso_username": "Jane Doe"},
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

    reward_cancel_task_id = (
        db_session.execute(
            select(RetryTask.retry_task_id).where(
                TaskType.task_type_id == RetryTask.task_type_id,
                TaskType.name == settings.REWARD_CANCELLATION_TASK_NAME,
            )
        )
        .unique()
        .scalar_one()
    )

    deletion_task_id = (
        db_session.execute(
            select(RetryTask.retry_task_id).where(
                TaskType.task_type_id == RetryTask.task_type_id,
                TaskType.name == settings.DELETE_CAMPAIGN_BALANCES_TASK_NAME,
            )
        )
        .unique()
        .scalar_one()
    )

    assert resp.status_code == fastapi_http_status.HTTP_409_CONFLICT
    # Check that Campaign change for the first campaign was successful
    mock_put_carina_campaign.assert_called_once_with(
        retailer_slug=retailer.slug,
        campaign_slug=campaign.slug,
        reward_slug=reward_rule.reward_slug,
        requested_status=payload["requested_status"],
    )
    mock_enqueue_many_tasks.assert_called_once_with(
        retry_tasks_ids=[
            reward_cancel_task_id,
            deletion_task_id,
        ],
    )
    db_session.refresh(campaign)
    assert campaign.status == CampaignStatuses.CANCELLED  # i.e. changed

    # Check that second and third failed validation and no status change
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


def test_leaving_no_active_campaigns_gives_error(
    setup: SetupType,
    create_mock_campaign: Callable,
) -> None:
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
        "activity_metadata": {"sso_username": "Jane Doe"},
    }

    resp = client.post(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    retry_tasks = db_session.execute(select(RetryTask)).unique().scalars().all()
    assert retry_tasks == []
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
        "activity_metadata": {"sso_username": "Jane Doe"},
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
    create_campaign_balances_task_type: TaskType,
    mocker: MockerFixture,
) -> None:
    now = datetime.now(tz=timezone.utc)
    db_session, retailer, _ = setup

    activable_campaign.start_date = None
    db_session.commit()

    mock_put_carina_campaign = mocker.patch(
        "vela.api.endpoints.campaign.put_carina_campaign",
        return_value=(fastapi_http_status.HTTP_200_OK, "Carina responded with: 200"),
    )
    mock_enqueue_many_tasks = mocker.patch("vela.api.endpoints.campaign.enqueue_many_tasks")
    mock_datetime = mocker.patch("vela.api.endpoints.campaign.datetime")
    mock_datetime.now.return_value = now

    payload = {
        "requested_status": "active",
        "campaign_slugs": [activable_campaign.slug],
        "activity_metadata": {"sso_username": "Jane Doe"},
    }

    resp = client.post(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    tasks_created = (
        db_session.execute(
            select(RetryTask).where(
                TaskType.task_type_id == RetryTask.task_type_id,
            )
        )
        .unique()
        .scalars()
        .all()
    )

    assert resp.status_code == fastapi_http_status.HTTP_200_OK
    assert resp.json() == {}

    # PUT /campaign call to carina
    mock_put_carina_campaign.assert_called_once_with(
        retailer_slug=retailer.slug,
        campaign_slug=activable_campaign.slug,
        reward_slug=activable_campaign.reward_rule.reward_slug,
        requested_status=payload["requested_status"],
    )

    assert len(tasks_created) == 1
    assert tasks_created[0].task_type.name == settings.CREATE_CAMPAIGN_BALANCES_TASK_NAME
    assert tasks_created[0].task_type.name != settings.PENDING_REWARDS_TASK_NAME
    mock_enqueue_many_tasks.assert_called_once_with(
        retry_tasks_ids=[
            tasks_created[0].retry_task_id,
        ],
    )

    db_session.refresh(activable_campaign)
    mock_datetime.now.assert_called_once()
    assert activable_campaign.status == CampaignStatuses.ACTIVE
    assert activable_campaign.end_date is None
    assert activable_campaign.start_date == now.replace(tzinfo=None)


def test_activating_a_campaign_carin_call_fails(
    setup: SetupType,
    activable_campaign: Campaign,
    create_campaign_balances_task_type: TaskType,
    mocker: MockerFixture,
) -> None:
    db_session, retailer, _ = setup

    mock_carina_resp_msg = "Carina responded with: 404 - Reward slug does not exist"
    mock_carina_resp_status_code = fastapi_http_status.HTTP_404_NOT_FOUND
    mock_put_carina_campaign = mocker.patch(
        "vela.api.endpoints.campaign.put_carina_campaign",
        return_value=(mock_carina_resp_status_code, mock_carina_resp_msg),
    )
    mock_enqueue_many_tasks = mocker.patch("vela.api.endpoints.campaign.enqueue_many_tasks")

    payload = {
        "requested_status": "active",
        "campaign_slugs": [activable_campaign.slug],
        "activity_metadata": {"sso_username": "Jane Doe"},
    }

    resp = client.post(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    assert resp.status_code == mock_carina_resp_status_code
    assert resp.json() == {
        "display_message": f"Unable to update campaign: {activable_campaign.slug} due to upstream errors. "
        f"Carina responses: {{'{activable_campaign.slug}': '{mock_carina_resp_msg}'}}. "
        "Successfully updated campaigns: [].",
        "code": "CARINA_RESPONSE_ERROR",
    }

    # PUT /campaign call to carina
    mock_put_carina_campaign.assert_called_once_with(
        retailer_slug=retailer.slug,
        campaign_slug=activable_campaign.slug,
        reward_slug=activable_campaign.reward_rule.reward_slug,
        requested_status=payload["requested_status"],
    )

    # No tasks were enqueued because the carina call failed
    all_tasks = db_session.execute(select(RetryTask)).scalars().all()
    assert len(all_tasks) == 0
    mock_enqueue_many_tasks.assert_not_called()

    db_session.refresh(activable_campaign)
    assert activable_campaign.status == CampaignStatuses.DRAFT  # not changed


def test_activating_a_campaign_with_no_earn_rules(setup: SetupType, activable_campaign: Campaign) -> None:
    db_session, retailer, _ = setup

    db_session.execute(delete(EarnRule).where(EarnRule.id.in_([rule.id for rule in activable_campaign.earn_rules])))
    db_session.commit()

    payload = {
        "requested_status": "active",
        "campaign_slugs": [activable_campaign.slug],
        "activity_metadata": {"sso_username": "Jane Doe"},
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
        "activity_metadata": {"sso_username": "Jane Doe"},
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
        "activity_metadata": {"sso_username": "Jane Doe"},
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


def test_ending_campaign_convert_pending_rewards(
    setup: SetupType,
    create_mock_campaign: Callable,
    create_mock_reward_rule: Callable,
    delete_campaign_balances_task_type: TaskType,
    convert_or_delete_pending_rewards_task_type: TaskType,
    mocker: MockerFixture,
) -> None:

    mock_put_carina_campaign = mocker.patch(
        "vela.api.endpoints.campaign.put_carina_campaign",
        return_value=(fastapi_http_status.HTTP_200_OK, "Carina responded with: 200"),
    )
    mock_enqueue_many_tasks = mocker.patch("vela.api.endpoints.campaign.enqueue_many_tasks")
    mock_datetime = mocker.patch("vela.api.endpoints.campaign.datetime")

    fake_now = datetime.now(tz=timezone.utc)
    mock_datetime.now.return_value = fake_now
    db_session, retailer, campaign = setup
    campaign.status = CampaignStatuses.ACTIVE

    # Set up a second ACTIVE campaign just so we don't end up with no current ACTIVE campaigns (would produce 409 error)
    second_campaign = create_mock_campaign(
        **{
            "status": CampaignStatuses.ACTIVE,
            "name": "secondtestcampaign",
            "slug": "second-test-campaign",
        }
    )
    second_reward_rule = create_mock_reward_rule(
        reward_slug="second-reward-type", campaign_id=second_campaign.id, allocation_window=5
    )
    db_session.commit()

    payload = {
        "requested_status": "ended",
        "campaign_slugs": [second_campaign.slug],
        "issue_pending_rewards": True,
        "activity_metadata": {"sso_username": "Jane Doe"},
    }
    resp = client.post(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    deletion_task = (
        db_session.execute(
            select(RetryTask).where(
                TaskType.task_type_id == RetryTask.task_type_id,
                TaskType.name == settings.DELETE_CAMPAIGN_BALANCES_TASK_NAME,
            )
        )
        .unique()
        .scalar_one()
    )

    pending_reward_task = (
        db_session.execute(
            select(RetryTask).where(
                TaskType.task_type_id == RetryTask.task_type_id,
                TaskType.name == settings.PENDING_REWARDS_TASK_NAME,
            )
        )
        .unique()
        .scalar_one()
    )

    assert resp.status_code == fastapi_http_status.HTTP_200_OK

    # PUT /campaign call to carina
    mock_put_carina_campaign.assert_called_once_with(
        retailer_slug=retailer.slug,
        campaign_slug=second_campaign.slug,
        reward_slug=second_reward_rule.reward_slug,
        requested_status=payload["requested_status"],
    )

    db_session.refresh(second_campaign)
    assert second_campaign.status == CampaignStatuses.ENDED
    assert second_campaign.end_date == fake_now.replace(tzinfo=None)
    mock_enqueue_many_tasks.assert_called_once_with(
        retry_tasks_ids=[
            pending_reward_task.retry_task_id,
            deletion_task.retry_task_id,
        ],
    )
    assert deletion_task.status == RetryTaskStatuses.PENDING
    assert pending_reward_task.status == RetryTaskStatuses.PENDING


def test_cancelling_campaign_delete_pending_rewards(
    setup: SetupType,
    create_mock_campaign: Callable,
    create_mock_reward_rule: Callable,
    account_holder_cancel_reward_task_type: TaskType,
    delete_campaign_balances_task_type: TaskType,
    convert_or_delete_pending_rewards_task_type: TaskType,
    mocker: MockerFixture,
) -> None:

    mock_put_carina_campaign = mocker.patch(
        "vela.api.endpoints.campaign.put_carina_campaign",
        return_value=(fastapi_http_status.HTTP_200_OK, "Carina responded with: 200"),
    )
    mock_enqueue_many_tasks = mocker.patch("vela.api.endpoints.campaign.enqueue_many_tasks")
    mock_datetime = mocker.patch("vela.api.endpoints.campaign.datetime")

    db_session, retailer, campaign = setup
    campaign.status = CampaignStatuses.ACTIVE
    fake_now = datetime.now(tz=timezone.utc)
    mock_datetime.now.return_value = fake_now
    # Set up a second ACTIVE campaign just so we don't end up with no
    # current ACTIVE campaigns (would produce 409 error)
    second_campaign = create_mock_campaign(
        **{
            "status": CampaignStatuses.ACTIVE,
            "name": "secondtestcampaign",
            "slug": "second-test-campaign",
        }
    )
    create_mock_reward_rule(reward_slug="second-reward-type", campaign_id=second_campaign.id, allocation_window=5)
    db_session.commit()

    payload = {
        "requested_status": "cancelled",
        "campaign_slugs": [second_campaign.slug],
        "activity_metadata": {"sso_username": "Jane Doe"},
    }
    resp = client.post(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    deletion_task = (
        db_session.execute(
            select(RetryTask)
            .where(
                TaskType.task_type_id == RetryTask.task_type_id,
                TaskType.name == settings.DELETE_CAMPAIGN_BALANCES_TASK_NAME,
            )
            .order_by(RetryTask.created_at.desc())
        )
        .scalars()
        .first()
    )

    pending_reward_task = (
        db_session.execute(
            select(RetryTask)
            .where(
                TaskType.task_type_id == RetryTask.task_type_id,
                TaskType.name == settings.PENDING_REWARDS_TASK_NAME,
            )
            .order_by(RetryTask.created_at.desc())
        )
        .scalars()
        .first()
    )

    reward_cancel_task = (
        db_session.execute(
            select(RetryTask)
            .where(
                TaskType.task_type_id == RetryTask.task_type_id,
                TaskType.name == settings.REWARD_CANCELLATION_TASK_NAME,
            )
            .order_by(RetryTask.created_at.desc())
        )
        .scalars()
        .first()
    )

    assert resp.status_code == fastapi_http_status.HTTP_200_OK
    db_session.refresh(second_campaign)
    assert second_campaign.status.value == payload["requested_status"]
    assert second_campaign.end_date == fake_now.replace(tzinfo=None)

    # PUT /campaign call to carina
    mock_put_carina_campaign.assert_called_once_with(
        retailer_slug=retailer.slug,
        campaign_slug=second_campaign.slug,
        reward_slug=second_campaign.reward_rule.reward_slug,
        requested_status=payload["requested_status"],
    )
    mock_enqueue_many_tasks.assert_called_once_with(
        retry_tasks_ids=[
            pending_reward_task.retry_task_id,
            reward_cancel_task.retry_task_id,
            deletion_task.retry_task_id,
        ],
    )
    assert deletion_task.status == RetryTaskStatuses.PENDING
    assert pending_reward_task.status == RetryTaskStatuses.PENDING
    assert reward_cancel_task.status == RetryTaskStatuses.PENDING


def test_ending_campaign_delete_pending_rewards(
    setup: SetupType,
    create_mock_campaign: Callable,
    create_mock_reward_rule: Callable,
    delete_campaign_balances_task_type: TaskType,
    convert_or_delete_pending_rewards_task_type: TaskType,
    mocker: MockerFixture,
) -> None:

    mock_put_carina_campaign = mocker.patch(
        "vela.api.endpoints.campaign.put_carina_campaign",
        return_value=(fastapi_http_status.HTTP_200_OK, "Carina responded with: 200"),
    )
    mock_enqueue_many_tasks = mocker.patch("vela.api.endpoints.campaign.enqueue_many_tasks")
    mock_datetime = mocker.patch("vela.api.endpoints.campaign.datetime")

    db_session, retailer, campaign = setup
    campaign.status = CampaignStatuses.ACTIVE
    fake_now = datetime.now(tz=timezone.utc)
    mock_datetime.now.return_value = fake_now
    # Set up a second ACTIVE campaign just so we don't end up with no
    # current ACTIVE campaigns (would produce 409 error)
    second_campaign = create_mock_campaign(
        **{
            "status": CampaignStatuses.ACTIVE,
            "name": "secondtestcampaign",
            "slug": "second-test-campaign",
        }
    )
    create_mock_reward_rule(reward_slug="second-reward-type", campaign_id=second_campaign.id, allocation_window=5)
    db_session.commit()

    payload = {
        "requested_status": "ended",
        "campaign_slugs": [second_campaign.slug],
        "activity_metadata": {"sso_username": "Jane Doe"},
    }
    resp = client.post(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    deletion_task = (
        db_session.execute(
            select(RetryTask)
            .where(
                TaskType.task_type_id == RetryTask.task_type_id,
                TaskType.name == settings.DELETE_CAMPAIGN_BALANCES_TASK_NAME,
            )
            .order_by(RetryTask.created_at.desc())
        )
        .scalars()
        .first()
    )

    pending_reward_task = (
        db_session.execute(
            select(RetryTask)
            .where(
                TaskType.task_type_id == RetryTask.task_type_id,
                TaskType.name == settings.PENDING_REWARDS_TASK_NAME,
            )
            .order_by(RetryTask.created_at.desc())
        )
        .scalars()
        .first()
    )

    assert resp.status_code == fastapi_http_status.HTTP_200_OK
    db_session.refresh(second_campaign)
    assert second_campaign.status.value == payload["requested_status"]
    assert second_campaign.end_date == fake_now.replace(tzinfo=None)

    # PUT /campaign call to carina
    mock_put_carina_campaign.assert_called_once_with(
        retailer_slug=retailer.slug,
        campaign_slug=second_campaign.slug,
        reward_slug=second_campaign.reward_rule.reward_slug,
        requested_status=payload["requested_status"],
    )
    mock_enqueue_many_tasks.assert_called_once_with(
        retry_tasks_ids=[
            pending_reward_task.retry_task_id,
            deletion_task.retry_task_id,
        ],
    )
    assert deletion_task.status == RetryTaskStatuses.PENDING
    assert pending_reward_task.status == RetryTaskStatuses.PENDING


def test_ending_campaign_convert_pending_rewards_without_refund_window(
    setup: SetupType,
    create_mock_campaign: Callable,
    create_mock_reward_rule: Callable,
    delete_campaign_balances_task_type: TaskType,
    convert_or_delete_pending_rewards_task_type: TaskType,
    mocker: MockerFixture,
) -> None:

    mock_put_carina_campaign = mocker.patch(
        "vela.api.endpoints.campaign.put_carina_campaign",
        return_value=(fastapi_http_status.HTTP_200_OK, "Carina responded with: 200"),
    )
    mock_enqueue_many_tasks = mocker.patch("vela.api.endpoints.campaign.enqueue_many_tasks")
    mock_datetime = mocker.patch("vela.api.endpoints.campaign.datetime")

    fake_now = datetime.now(tz=timezone.utc)
    mock_datetime.now.return_value = fake_now
    db_session, retailer, campaign = setup
    campaign.status = CampaignStatuses.ACTIVE

    # Set up a second ACTIVE campaign just so we don't end up with no current ACTIVE campaigns (would produce 409 error)
    second_campaign = create_mock_campaign(
        **{
            "status": CampaignStatuses.ACTIVE,
            "name": "secondtestcampaign",
            "slug": "second-test-campaign",
        }
    )
    create_mock_reward_rule(reward_slug="second-reward-type", campaign_id=second_campaign.id)
    db_session.commit()

    payload = {
        "requested_status": "ended",
        "campaign_slugs": [second_campaign.slug],
        "issue_pending_rewards": True,
        "activity_metadata": {"sso_username": "Jane Doe"},
    }
    resp = client.post(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    deletion_task = (
        db_session.execute(
            select(RetryTask).where(
                TaskType.task_type_id == RetryTask.task_type_id,
                TaskType.name == settings.DELETE_CAMPAIGN_BALANCES_TASK_NAME,
            )
        )
        .unique()
        .scalar_one()
    )

    all_tasks = db_session.execute(select(RetryTask)).unique().scalars().all()
    task_names = [task.task_type.name for task in all_tasks]

    assert resp.status_code == fastapi_http_status.HTTP_200_OK
    db_session.refresh(second_campaign)
    assert second_campaign.status == CampaignStatuses.ENDED
    assert second_campaign.end_date == fake_now.replace(tzinfo=None)
    assert settings.PENDING_REWARDS_TASK_NAME not in task_names

    # PUT /campaign call to carina
    mock_put_carina_campaign.assert_called_once_with(
        retailer_slug=retailer.slug,
        campaign_slug=second_campaign.slug,
        reward_slug=second_campaign.reward_rule.reward_slug,
        requested_status=payload["requested_status"],
    )
    mock_enqueue_many_tasks.assert_called_once_with(
        retry_tasks_ids=[
            deletion_task.retry_task_id,
        ],
    )
    assert deletion_task.status == RetryTaskStatuses.PENDING


def test_delete_draft_campaign(
    setup: SetupType,
    create_mock_campaign: Callable,
) -> None:
    db_session, retailer, campaign = setup
    campaign.status = CampaignStatuses.ACTIVE

    # Create second campaign
    second_campaign: Campaign = create_mock_campaign(
        **{
            "status": CampaignStatuses.DRAFT,
            "name": "secondtestcampaign",
            "slug": "second-test-campaign",
        }
    )
    db_session.commit()

    resp = client.delete(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/{second_campaign.slug}",
        headers=auth_headers,
    )

    campaigns = (
        db_session.execute(
            select(Campaign).where(
                Campaign.slug == second_campaign.slug,
            )
        )
        .scalars()
        .all()
    )

    assert resp.status_code == fastapi_http_status.HTTP_200_OK
    assert len(campaigns) == 0


def test_404_campaign_not_found_for_delete_draft_campaign(
    setup: SetupType,
    create_mock_campaign: Callable,
) -> None:
    db_session, retailer, campaign = setup
    campaign.status = CampaignStatuses.ACTIVE

    # Create second campaign
    second_campaign: Campaign = create_mock_campaign(
        **{
            "status": CampaignStatuses.DRAFT,
            "name": "secondtestcampaign",
            "slug": "second-test-campaign",
        }
    )
    db_session.commit()

    resp = client.delete(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/wrong-campaign-slug",
        headers=auth_headers,
    )

    campaigns = (
        db_session.execute(
            select(Campaign).where(
                Campaign.slug == second_campaign.slug,
            )
        )
        .scalars()
        .all()
    )

    assert resp.status_code == fastapi_http_status.HTTP_404_NOT_FOUND
    assert len(campaigns) == 1


def test_409_delete_failed_for_delete_draft_campaign(
    setup: SetupType,
    create_mock_campaign: Callable,
) -> None:
    db_session, retailer, campaign = setup
    campaign.status = CampaignStatuses.ACTIVE

    # Create second campaign
    second_campaign: Campaign = create_mock_campaign(
        **{
            "status": CampaignStatuses.ACTIVE,
            "name": "secondtestcampaign",
            "slug": "second-test-campaign",
        }
    )
    db_session.commit()

    resp = client.delete(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/{second_campaign.slug}",
        headers=auth_headers,
    )

    campaigns = (
        db_session.execute(
            select(Campaign).where(
                Campaign.slug == second_campaign.slug,
            )
        )
        .scalars()
        .all()
    )

    assert resp.status_code == fastapi_http_status.HTTP_409_CONFLICT
    assert len(campaigns) == 1
