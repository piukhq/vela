import asyncio
import logging

from typing import Any
from uuid import UUID

import aiohttp
import sentry_sdk

from fastapi import status
from tenacity import retry
from tenacity.retry import retry_if_exception_type, retry_if_result
from tenacity.stop import stop_after_attempt
from tenacity.wait import wait_fixed

from app.core.config import settings
from app.enums import HttpErrors

logger = logging.getLogger(__name__)
timeout = aiohttp.ClientTimeout(total=10, connect=3.03)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(0.1),
    reraise=True,
    retry_error_callback=lambda retry_state: retry_state.outcome.result(),
    retry=retry_if_result(lambda result: 501 <= result[0] <= 504)
    | retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
)  # pragma: no cover
async def send_async_request_with_retry(
    method: str,
    url: str,
    *,
    headers: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
) -> tuple[int, dict]:  # pragma: no cover

    async with aiohttp.ClientSession(raise_for_status=False) as session:
        async with session.request(method, url, headers=headers, json=json, timeout=timeout) as response:
            json_response = await response.json()
            return response.status, json_response


async def validate_account_holder_uuid(account_holder_uuid: UUID, retailer_slug: str) -> None:

    url = f"{settings.POLARIS_BASE_URL}/{retailer_slug}/accounts/{account_holder_uuid}/status"
    with sentry_sdk.start_span(op="http", description=f"GET {url}") as span:
        status_code, resp_json = await send_async_request_with_retry(
            "GET", url, headers={"Authorization": f"Token {settings.POLARIS_API_AUTH_TOKEN}"}
        )
        span.set_tag("http.status_code", status_code)

    if status_code == status.HTTP_404_NOT_FOUND:
        raise HttpErrors.USER_NOT_FOUND.value

    if not 200 <= status_code < 300:
        ex = aiohttp.ClientError(f"Response returned {status_code}")
        logger.exception("Failed to fetch account holder status from Polaris.", exc_info=ex)
        raise ex

    if resp_json["status"] != "active":
        raise HttpErrors.USER_NOT_ACTIVE.value
