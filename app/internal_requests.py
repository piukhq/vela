import logging

from typing import Any
from uuid import UUID

import httpx

from fastapi import status
from tenacity import retry
from tenacity.retry import retry_if_exception_type, retry_if_result
from tenacity.stop import stop_after_attempt
from tenacity.wait import wait_fixed

from app.core.config import settings
from app.enums import HttpErrors

logger = logging.getLogger(__name__)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(0.1),
    reraise=True,
    retry_error_callback=lambda retry_state: retry_state.outcome.result(),
    retry=retry_if_result(lambda resp: 501 <= resp.status_code <= 504) | retry_if_exception_type(httpx.RequestError),
)  # pragma: no cover
async def send_async_request_with_retry(
    method: str,
    url: str,
    *,
    headers: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
) -> httpx.Response:  # pragma: no cover

    async with httpx.AsyncClient() as client:  # pragma: no cover
        return await client.request(method, url, headers=headers, json=json)


async def validate_account_holder_uuid(account_holder_uuid: UUID, retailer_slug: str) -> None:
    resp = await send_async_request_with_retry(
        "GET",
        f"{settings.POLARIS_BASE_URL}/{retailer_slug}/accounts/{account_holder_uuid}/status",
        headers={"Authorization": f"Token {settings.POLARIS_API_AUTH_TOKEN}"},
    )
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as ex:
        if resp.status_code == status.HTTP_404_NOT_FOUND:
            raise HttpErrors.USER_NOT_FOUND.value
        else:
            logger.exception("Failed to fetch account holder status from Polaris.", exc_info=ex)
            raise

    else:
        if resp.json()["status"] != "active":
            raise HttpErrors.USER_NOT_ACTIVE.value
