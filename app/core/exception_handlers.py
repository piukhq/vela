import logging

from typing import Union, cast

import sentry_sdk

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import UJSONResponse
from starlette.exceptions import HTTPException
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_422_UNPROCESSABLE_ENTITY, HTTP_500_INTERNAL_SERVER_ERROR

logger = logging.getLogger(__name__)


def _format_validation_errors(payload: list[dict]) -> tuple[int, Union[list[dict], dict]]:  # pragma: no cover
    for error in payload:
        if error["type"] == "value_error.jsondecode":
            return (
                HTTP_400_BAD_REQUEST,
                {"display_message": "Malformed request.", "code": "MALFORMED_REQUEST"},
            )

    return (
        HTTP_422_UNPROCESSABLE_ENTITY,
        {"display_message": "BPL Schema not matched.", "code": "INVALID_CONTENT"},
    )


# customise Api RequestValidationError
async def request_validation_handler(request: Request, exc: RequestValidationError) -> Response:
    status_code, content = _format_validation_errors(cast(list[dict], exc.errors()))
    return UJSONResponse(status_code=status_code, content=content)


# customise Api HTTPException to remove "details" and handle manually raised ValidationErrors
async def http_exception_handler(request: Request, exc: HTTPException) -> UJSONResponse:

    if exc.status_code == HTTP_422_UNPROCESSABLE_ENTITY and isinstance(exc.detail, list):
        status_code, content = _format_validation_errors(exc.detail)
    else:
        status_code, content = exc.status_code, exc.detail

    return UJSONResponse(content, status_code=status_code, headers=getattr(exc, "headers", None))


async def unexpected_exception_handler(request: Request, exc: Exception) -> UJSONResponse:
    try:
        return UJSONResponse(
            {
                "display_message": "An unexpected system error occurred, please try again later.",
                "code": "INTERNAL_ERROR",
            },
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
        )
    finally:
        logger.exception(exc)
        sentry_sdk.capture_exception(exc)
