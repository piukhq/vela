import logging

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from vela.core.config import settings
from vela.tasks.prometheus.metrics import outgoing_http_requests_total, tasks_processing_time_histogram

if TYPE_CHECKING:  # pragma: no cover
    from requests import RequestException, Response  # pragma: no cover

logger = logging.getLogger(__name__)


def update_metrics_hook(url_label: str) -> Callable:  # pragma: no cover
    def update_metrics(resp: "Response", *args: Any, **kwargs: Any) -> None:
        outgoing_http_requests_total.labels(
            app=settings.PROJECT_NAME,
            method=resp.request.method,
            response=f"HTTP_{resp.status_code}",
            exception=None,
            url=url_label,
        ).inc()

    return update_metrics


def update_metrics_exception_handler(ex: "RequestException", method: str, url: str) -> None:  # pragma: no cover
    outgoing_http_requests_total.labels(
        app=settings.PROJECT_NAME,
        method=method,
        response=None,
        exception=ex.__class__.__name__,
        url=url,
    ).inc()


def task_processing_time_callback_fn(task_processing_time: float, task_name: str) -> None:
    logger.info(f"Updating {tasks_processing_time_histogram} metrics...")
    tasks_processing_time_histogram.labels(app=settings.PROJECT_NAME, task_name=task_name).observe(task_processing_time)
