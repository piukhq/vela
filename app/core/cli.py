import logging

import typer

from prometheus_client import CollectorRegistry
from prometheus_client import start_http_server as start_prometheus_server
from prometheus_client.multiprocess import MultiProcessCollector
from retry_tasks_lib.utils.error_handler import job_meta_handler

from app.core.config import redis, settings
from app.tasks.worker import RetryTaskWorker

cli = typer.Typer()
logger = logging.getLogger(__name__)


@cli.command()
def task_worker(burst: bool = False) -> None:  # pragma: no cover
    registry = CollectorRegistry()
    MultiProcessCollector(registry)
    logger.info("Starting prometheus metrics server...")
    start_prometheus_server(settings.PROMETHEUS_HTTP_SERVER_PORT, registry=registry)
    worker = RetryTaskWorker(
        queues=settings.TASK_QUEUES,
        connection=redis,
        log_job_description=True,
        exception_handlers=[job_meta_handler],
    )
    logger.info("Starting task worker...")
    worker.work(burst=burst, with_scheduler=True)


@cli.callback()
def callback() -> None:
    """
    vela command line interface
    """


if __name__ == "__main__":
    cli()
