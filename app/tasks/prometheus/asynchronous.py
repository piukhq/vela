import logging

from types import SimpleNamespace

from aiohttp import TraceRequestEndParams, TraceRequestExceptionParams
from aiohttp.client import ClientSession

from app.core.config import settings
from app.tasks.prometheus.metrics import outgoing_http_requests_total

logger = logging.getLogger(__name__)


async def on_request_end(
    session: ClientSession, trace_config_ctx: SimpleNamespace, params: TraceRequestEndParams
) -> None:
    if settings.ACTIVATE_TASKS_METRICS:
        outgoing_http_requests_total.labels(
            app=settings.PROJECT_NAME,
            method=params.method,
            response=f"HTTP_{params.response.status}",
            exception=None,
            url=trace_config_ctx.label_url,
        ).inc()


async def on_request_exception(
    session: ClientSession, trace_config_ctx: SimpleNamespace, params: TraceRequestExceptionParams
) -> None:
    if settings.ACTIVATE_TASKS_METRICS:
        outgoing_http_requests_total.labels(
            app=settings.PROJECT_NAME,
            method=params.method,
            response=None,
            exception=params.exception.strerror,  # type: ignore [attr-defined]
            url=trace_config_ctx.label_url,
        ).inc()
