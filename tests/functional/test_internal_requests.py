from uuid import uuid4

import pytest

from aioresponses import aioresponses

from vela import settings
from vela.internal_requests import send_async_request_with_retry


@pytest.mark.asyncio
async def test_send_async_request_with_retry() -> None:
    mock_retailer_slug = "test-retailer"
    mock_account_holder_uuid = uuid4()
    mock_payload = {"status": "active"}

    mock_url = f"{settings.POLARIS_BASE_URL}/test-retailer/accounts/{mock_account_holder_uuid}/status"
    with aioresponses() as mocked_clientreq:
        mocked_clientreq.get(mock_url, payload=mock_payload)

        status_code, resp_json = await send_async_request_with_retry(
            method="GET",
            url=mock_url,
            url_template="{base_url}/{retailer_slug}/accounts/{account_holder_uuid}/status",
            url_kwargs={
                "base_url": settings.POLARIS_BASE_URL,
                "retailer_slug": mock_retailer_slug,
                "account_holder_uuid": mock_account_holder_uuid,
            },
            exclude_from_label_url=["retailer_slug", "account_holder_uuid"],
            headers={"Authorization": f"Token {settings.POLARIS_API_AUTH_TOKEN}"},
        )

        assert status_code == 200
        assert resp_json == mock_payload
