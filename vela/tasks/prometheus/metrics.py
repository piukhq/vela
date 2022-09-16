import logging

from prometheus_client import Counter, Gauge, Histogram

logger = logging.getLogger(__name__)

METRIC_NAME_PREFIX = "bpl_"

outgoing_http_requests_total = Counter(
    name=f"{METRIC_NAME_PREFIX}outgoing_http_requests_total",
    documentation="Total outgoing http requests by response status.",
    labelnames=("app", "method", "response", "exception", "url"),
)

tasks_run_total = Counter(
    name=f"{METRIC_NAME_PREFIX}tasks_run_total",
    documentation="Counter for tasks run.",
    labelnames=("app", "task_name"),
)

task_statuses = Gauge(
    name=f"{METRIC_NAME_PREFIX}task_anomalies",
    documentation="The current number of tasks in an unusual state",
    labelnames=("app", "task_name", "status"),
)

tasks_summary = Gauge(
    name=f"{METRIC_NAME_PREFIX}task_summary",
    documentation="The current number of tasks and their status",
    labelnames=("app", "task_name", "status"),
)

job_queue_summary = Gauge(
    name=f"{METRIC_NAME_PREFIX}job_queue_length",
    documentation="The current number of jobs in each RQ queue",
    labelnames=("app", "queue_name"),
)


tasks_processing_time_histogram = Histogram(
    name=f"{METRIC_NAME_PREFIX}tasks_processing_time",
    documentation="Total time taken by a task to process",
    labelnames=("app", "task_name"),
)
