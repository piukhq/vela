import logging

import typer

from prometheus_client import CollectorRegistry
from prometheus_client import start_http_server as start_prometheus_server
from prometheus_client.multiprocess import MultiProcessCollector
from retry_tasks_lib.reporting import report_anomalous_tasks
from retry_tasks_lib.utils.error_handler import job_meta_handler
from rq import Worker

from app.core.config import redis_raw, settings
from app.db.session import SyncSessionMaker
from app.scheduled_tasks.scheduler import cron_scheduler as vela_cron_scheduler
from app.tasks.prometheus import task_statuses

cli = typer.Typer()
logger = logging.getLogger(__name__)


@cli.command()
def task_worker(burst: bool = False) -> None:  # pragma: no cover
    if settings.ACTIVATE_TASKS_METRICS:
        registry = CollectorRegistry()
        MultiProcessCollector(registry)
        logger.info("Starting prometheus metrics server...")
        start_prometheus_server(settings.PROMETHEUS_HTTP_SERVER_PORT, registry=registry)

    worker = Worker(
        queues=settings.TASK_QUEUES,
        connection=redis_raw,
        log_job_description=True,
        exception_handlers=[job_meta_handler],
    )
    logger.info("Starting task worker...")
    worker.work(burst=burst, with_scheduler=True)


@cli.command()
def cron_scheduler(report_tasks: bool = True) -> None:  # pragma: no cover

    logger.info("Initialising scheduler...")

    if report_tasks:
        registry = CollectorRegistry()
        MultiProcessCollector(registry)
        logger.info("Starting prometheus metrics server...")
        start_prometheus_server(settings.PROMETHEUS_HTTP_SERVER_PORT, registry=registry)

        vela_cron_scheduler.add_job(
            report_anomalous_tasks,
            kwargs={"session_maker": SyncSessionMaker, "project_name": settings.PROJECT_NAME, "gauge": task_statuses},
            schedule_fn=lambda: settings.REPORT_ANOMALOUS_TASKS_SCHEDULE,
            coalesce_jobs=True,
        )

    logger.info(f"Starting scheduler {vela_cron_scheduler}...")
    vela_cron_scheduler.run()


@cli.callback()
def callback() -> None:
    """
    vela command line interface
    """


if __name__ == "__main__":
    cli()
