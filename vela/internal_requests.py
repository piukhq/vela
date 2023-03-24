import asyncio
import logging

from types import SimpleNamespace
from typing import Any
from uuid import UUID

import aiohttp
import sentry_sdk

from fastapi import status
from tenacity import retry
from tenacity.retry import retry_if_exception_type, retry_if_result
from tenacity.stop import stop_after_attempt
from tenacity.wait import wait_fixed

from vela.core.config import settings
from vela.enums import HttpErrors
from vela.tasks.prometheus.asynchronous import on_request_end, on_request_exception

logger = logging.getLogger(__name__)
timeout = aiohttp.ClientTimeout(total=10, connect=3.03)


# pylint: disable=too-many-locals
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
    url_template: str,
    url_kwargs: dict,
    *,
    exclude_from_label_url: list[str],
    headers: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
) -> tuple[int, dict]:  # pragma: no cover
    """
    url_template: the url before any dynamic value is formatted into it.
    ex:
    ```python
    "{base_url}/{retailer_slug}/sample/url"
    ```

    url_kwargs: the values to be substituted into the template.
    ex:
    ```python
    {"base_url": "http://polaris-api/", "retailer_slug": "asos"}
    ```

    exclude_from_label_url: the url_kwargs' keys that we do not want to be substitued in the label url.
    ex:
    ```python
    ["retailer_slug"]
    ```

    **IMPORTANT**

    It is important that we exclude from the label url any unique field like account_holder_uuids.
    Not doing this leads to a build up of unique metrics that will lead to resource exhaustion,
    application failure, apocalypse, dragons (not the cool ones), and death.

    DO:
    ```python
    url_template="{base_url}/{account_holder_uuid}/sample/url"
    url_kwargs={"base_url": "http://polaris-api/", "account_holder_uuid": "e3ae1323-8587-4609-b32b-bd3343d42395"}
    exclude_from_label_url=["account_holder_uuid"]
    ```

    DO NOT DO:
    ```python
    url_template="{base_url}/{account_holder_uuid}/sample/url"
    url_kwargs={"base_url": "http://polaris-api/", "account_holder_uuid": "e3ae1323-8587-4609-b32b-bd3343d42395"}
    exclude_from_label_url=["base_url"] | []
    ```

    """

    label_kwargs: dict = {}
    for k, v in url_kwargs.items():
        if k in exclude_from_label_url:
            label_kwargs[k] = f"[{k}]"
        else:
            label_kwargs[k] = v

    label_url = url_template.format(**label_kwargs)

    def _trace_config_ctx_factory(trace_request_ctx: SimpleNamespace | None) -> SimpleNamespace:
        return SimpleNamespace(label_url=label_url, trace_request_ctx=trace_request_ctx)

    trace_config = aiohttp.TraceConfig(trace_config_ctx_factory=_trace_config_ctx_factory)  # type: ignore [arg-type]
    trace_config.on_request_end.append(on_request_end)
    trace_config.on_request_exception.append(on_request_exception)

    async with aiohttp.ClientSession(raise_for_status=False, trace_configs=[trace_config]) as session:
        async with session.request(method, url, headers=headers, json=json, timeout=timeout) as response:
            json_response = await response.json()
            return response.status, json_response


async def validate_account_holder_uuid(account_holder_uuid: UUID, retailer_slug: str) -> None:

    url = f"{settings.POLARIS_BASE_URL}/{retailer_slug}/accounts/{account_holder_uuid}/status"
    with sentry_sdk.start_span(op="http.client", description=f"GET {url}") as span:
        try:
            status_code, resp_json = await send_async_request_with_retry(
                method="GET",
                url=url,
                url_template="{base_url}/{retailer_slug}/accounts/{account_holder_uuid}/status",
                url_kwargs={
                    "base_url": settings.POLARIS_BASE_URL,
                    "retailer_slug": retailer_slug,
                    "account_holder_uuid": account_holder_uuid,
                },
                exclude_from_label_url=["retailer_slug", "account_holder_uuid"],
                headers={"Authorization": f"Token {settings.POLARIS_API_AUTH_TOKEN}"},
            )
            span.set_tag("http.status_code", status_code)
        except aiohttp.ClientError as ex:
            logger.exception("Failed to fetch account holder status from Polaris.", exc_info=ex)
            raise HttpErrors.GENERIC_HANDLED_ERROR.value

    if status_code == status.HTTP_404_NOT_FOUND:
        raise HttpErrors.USER_NOT_FOUND.value

    if not 200 <= status_code < 300:
        msg = aiohttp.ClientError(f"Response returned {status_code}")
        logger.exception("Failed to fetch account holder status from Polaris.", exc_info=msg)
        raise HttpErrors.GENERIC_HANDLED_ERROR.value

    if resp_json["status"] != "active":
        raise HttpErrors.USER_NOT_ACTIVE.value


async def put_carina_campaign(
    retailer_slug: str, campaign_slug: str, reward_slug: str, requested_status: str
) -> tuple[int, str]:
    http_method = "PUT"
    endpoint_url = f"{settings.CARINA_BASE_URL}/{retailer_slug}/{reward_slug}/campaign"
    request_payload = {"campaign_slug": campaign_slug, "status": requested_status}

    with sentry_sdk.start_span(op="http.client", description=f"{http_method} {endpoint_url}") as span:
        status_code, resp_json = await send_async_request_with_retry(
            method=http_method,
            url=endpoint_url,
            json=request_payload,
            url_template="{base_url}/{retailer_slug}/{reward_slug}/campaign",
            url_kwargs={
                "base_url": settings.CARINA_BASE_URL,
                "retailer_slug": retailer_slug,
                "reward_slug": reward_slug,
            },
            exclude_from_label_url=["retailer_slug", "reward_slug"],
            headers={"Authorization": f"Token {settings.CARINA_API_AUTH_TOKEN}"},
        )

        msg_prefix = "Carina responded with: "
        msg = (
            f"{msg_prefix}{status_code} - {resp_json['display_message']}" if resp_json else f"{msg_prefix}{status_code}"
        )

        span.set_tag("http.status_code", status_code)

        if not 200 <= status_code <= 300:
            ex = aiohttp.ClientError(f"Carina response returned: {status_code}")
            logger.exception(msg, exc_info=ex)

        return status_code, msg
