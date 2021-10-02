from fastapi.testclient import TestClient
from sqlalchemy.future import select  # type: ignore
from starlette import status as starlette_http_status

from app.core.config import settings
from app.enums import CampaignStatuses
from asgi import app
from tests.api.conftest import SetupType

client = TestClient(app)
auth_headers = {"Authorization": f"Token {settings.VELA_AUTH_TOKEN}", "Bpl-User-Channel": "channel"}


def test_update_campaign_active_status_to_ended(setup: SetupType) -> None:
    db_session, retailer, campaign = setup
    payload = {
        "action_type": "Ended",
        "campaign_slugs": [campaign.slug],
    }

    campaign.status = CampaignStatuses.ACTIVE
    db_session.commit()

    resp = client.post(
        f"{settings.API_PREFIX}/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    assert resp.status_code == starlette_http_status.HTTP_200_OK
    db_session.refresh(campaign)
    assert campaign.status == CampaignStatuses.ENDED
