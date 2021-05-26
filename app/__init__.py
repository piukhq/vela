import sentry_sdk

from fastapi import FastAPI, status
from fastapi.exceptions import RequestValidationError
from sentry_sdk.integrations.asgi import SentryAsgiMiddleware
from starlette.exceptions import HTTPException

from app.api.api import api_router
from app.core.config import settings
from app.core.exception_handlers import http_exception_handler, request_validation_handler, unexpected_exception_handler
from app.version import __version__


def create_app() -> FastAPI:
    app = FastAPI(title=settings.PROJECT_NAME, openapi_url=f"{settings.API_PREFIX}/openapi.json")
    app.include_router(api_router)

    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(status.HTTP_500_INTERNAL_SERVER_ERROR, unexpected_exception_handler)

    if settings.SENTRY_DSN:
        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            environment=settings.SENTRY_ENV,
            traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
            release=__version__,
        )
        app.add_middleware(SentryAsgiMiddleware)

    return app
