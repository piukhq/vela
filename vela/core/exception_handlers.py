import logging

from typing import TYPE_CHECKING

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import UJSONResponse
from starlette.exceptions import HTTPException
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_422_UNPROCESSABLE_ENTITY, HTTP_500_INTERNAL_SERVER_ERROR

if TYPE_CHECKING:
    from pydantic.error_wrappers import ErrorDict


logger = logging.getLogger(__name__)


def _format_validation_errors(
    url_path: str, payload: list["ErrorDict"]
) -> tuple[int, list[dict] | dict]:  # pragma: no cover
    fields = []
    for error in payload:
        if error["type"] == "value_error.jsondecode":
            return (
                HTTP_400_BAD_REQUEST,
                {"display_message": "Malformed request.", "code": "MALFORMED_REQUEST"},
            )

        fields.append(error["loc"][-1])

    if "/transaction" in url_path:
        content = {
            "display_message": "Submitted fields are missing or invalid.",
            "code": "FIELD_VALIDATION_ERROR",
            "fields": fields,
        }
    else:
        content = {"display_message": "BPL Schema not matched.", "code": "INVALID_CONTENT"}

    return HTTP_422_UNPROCESSABLE_ENTITY, content


# customise Api RequestValidationError
async def request_validation_handler(
    request: Request, exc: RequestValidationError  # pylint: disable=unused-argument
) -> Response:
    status_code, content = _format_validation_errors(request.url.path, exc.errors())
    return UJSONResponse(status_code=status_code, content=content)


# customise Api HTTPException to remove "details" and handle manually raised ValidationErrors
async def http_exception_handler(
    request: Request, exc: HTTPException  # pylint: disable=unused-argument
) -> UJSONResponse:

    if exc.status_code == HTTP_422_UNPROCESSABLE_ENTITY and isinstance(exc.detail, list):
        status_code, content = _format_validation_errors(request.url.path, exc.detail)
    else:
        status_code, content = exc.status_code, exc.detail

    return UJSONResponse(content, status_code=status_code, headers=getattr(exc, "headers", None))


async def unexpected_exception_handler(
    request: Request, exc: Exception  # pylint: disable=unused-argument
) -> UJSONResponse:
    try:
        return UJSONResponse(
            {
                "display_message": "An unexpected system error occurred, please try again later.",
                "code": "INTERNAL_ERROR",
            },
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
        )
    finally:
        logger.exception("Unexpected System Error", exc_info=exc)
