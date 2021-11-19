from typing import List, Tuple, Union

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import UJSONResponse
from starlette.exceptions import HTTPException
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_422_UNPROCESSABLE_ENTITY, HTTP_500_INTERNAL_SERVER_ERROR


def _format_validation_errors(payload: List[dict]) -> Tuple[int, Union[List[dict], dict]]:  # pragma: no cover
    for error in payload:
        if error["type"] == "value_error.jsondecode":
            return (
                HTTP_400_BAD_REQUEST,
                {"display_message": "Malformed request.", "error": "MALFORMED_REQUEST"},
            )

    return (
        HTTP_422_UNPROCESSABLE_ENTITY,
        {"display_message": "BPL Schema not matched.", "error": "INVALID_CONTENT"},
    )


# customise Api RequestValidationError
async def request_validation_handler(request: Request, exc: RequestValidationError) -> Response:
    status_code, content = _format_validation_errors(exc.errors())
    return UJSONResponse(status_code=status_code, content=content)


# customise Api HTTPException to remove "details" and handle manually raised ValidationErrors
async def http_exception_handler(request: Request, exc: HTTPException) -> UJSONResponse:

    if exc.status_code == HTTP_422_UNPROCESSABLE_ENTITY and isinstance(exc.detail, list):
        status_code, content = _format_validation_errors(exc.detail)  # pragma: coverage bug 1012
    else:
        status_code, content = exc.status_code, exc.detail

    return UJSONResponse(content, status_code=status_code, headers=getattr(exc, "headers", None))


async def unexpected_exception_handler(request: Request, exc: Exception) -> UJSONResponse:

    return UJSONResponse(
        {"display_message": "An unexpected system error occurred, please try again later.", "error": "INTERNAL_ERROR"},
        status_code=HTTP_500_INTERNAL_SERVER_ERROR,
    )
