from typing import List, Tuple, Union

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import UJSONResponse
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_422_UNPROCESSABLE_ENTITY


def _format_validation_errors(payload: List[dict]) -> Tuple[int, Union[List[dict], dict]]:
    invalid, missing = [], []
    for error in payload:
        if error["type"] == "value_error.jsondecode":
            return (
                HTTP_400_BAD_REQUEST,
                {"display_message": "Malformed request.", "error": "MALFORMED_REQUEST"},
            )

        if "missing" in error["type"]:
            missing.append(error["loc"][-1])
        else:
            invalid.append(error["loc"][-1])

    content = []
    if invalid:
        content.append(
            {
                "display_message": "Submitted credentials did not pass validation.",
                "error": "VALIDATION_FAILED",
                "fields": invalid,
            }
        )
    if missing:
        content.append(
            {
                "display_message": "Missing credentials from request.",
                "error": "MISSING_FIELDS",
                "fields": missing,
            }
        )

    return HTTP_422_UNPROCESSABLE_ENTITY, content


# customise Api RequestValidationError
async def request_validation_handler(request: Request, exc: RequestValidationError) -> Response:
    status_code, content = _format_validation_errors(exc.errors())
    return UJSONResponse(status_code=status_code, content=content)


# customise Api HTTPException to remove "details" and handle manually raised ValidationErrors
async def http_exception_handler(request: Request, exc: HTTPException) -> UJSONResponse:

    if exc.status_code == HTTP_422_UNPROCESSABLE_ENTITY and isinstance(exc.detail, list):
        status_code, content = _format_validation_errors(exc.detail)
    else:
        status_code, content = exc.status_code, exc.detail

    headers = getattr(exc, "headers", None)
    return UJSONResponse(content, status_code=status_code, headers=headers)
