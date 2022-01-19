from typing import TYPE_CHECKING, Any

from prometheus_client import Counter, Gauge

from app.core.config import settings

if TYPE_CHECKING:  # pragma: no cover
    from requests import RequestException, Response  # pragma: no cover

outgoing_http_requests_total = Counter(
    name="bpl_outgoing_http_requests_total",
    documentation="Total outgoing http requests by response status.",
    labelnames=("app", "method", "response", "exception", "url"),
)

tasks_run_total = Counter(
    name="bpl_tasks_run_total",
    documentation="Counter for tasks run.",
    labelnames=("app", "task_name"),
)

task_statuses = Gauge(
    name="bpl_task_anomalies",
    documentation="The current number of tasks in an unusual state",
    labelnames=("app", "task_name", "status"),
)


def update_metrics_hook(resp: "Response", *args: Any, **kwargs: Any) -> None:  # pragma: no cover
    outgoing_http_requests_total.labels(
        app=settings.PROJECT_NAME,
        method=resp.request.method,
        response=f"HTTP_{resp.status_code}",
        exception=None,
        url=resp.request.url,
    ).inc()


def update_metrics_exception_handler(ex: "RequestException", method: str, url: str) -> None:  # pragma: no cover
    outgoing_http_requests_total.labels(
        app=settings.PROJECT_NAME,
        method=method,
        response=None,
        exception=ex.__class__.__name__,
        url=url,
    ).inc()