# mypy checks for sqlalchemy core 2.0 require sqlalchemy2-stubs
import logging

from contextlib import contextmanager
from typing import Any, Callable, Generator, Union

import sentry_sdk

from retry_tasks_lib.db.models import load_models_to_metadata
from sqlalchemy import Column, DateTime, Integer, exc, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, declarative_base, declarative_mixin

from app.core.config import settings
from app.version import __version__


class ModelBase:
    id = Column(Integer, primary_key=True, index=True)


Base = declarative_base(cls=ModelBase)
load_models_to_metadata(Base.metadata)

utc_timestamp_sql = text("TIMEZONE('utc', CURRENT_TIMESTAMP)")

logger = logging.getLogger("db-base-class")

if settings.SENTRY_DSN:  # pragma: no cover
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.SENTRY_ENV,
        release=__version__,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
    )


@declarative_mixin
class TimestampMixin:
    created_at = Column(DateTime, server_default=utc_timestamp_sql, nullable=False)
    updated_at = Column(
        DateTime,
        server_default=utc_timestamp_sql,
        onupdate=utc_timestamp_sql,
        nullable=False,
    )


@contextmanager
def retry_query(
    session: Union[Session, AsyncSession], attempts: int = settings.DB_CONNECTION_RETRY_TIMES
) -> Generator:  # pragma: no cover
    """Retry any queries (transactions) that are interrupted by a connection error"""

    while attempts > 0:
        attempts -= 1
        try:
            yield
            break
        except exc.DBAPIError as e:
            if attempts > 0 and e.connection_invalidated:
                logger.warning(f"Interrupted transaction: {repr(e)}, attempts remaining:{attempts}")
            else:
                sentry_sdk.capture_message(f"Max db connection attempts reached: {repr(e)}")
                raise


# based on the following stackoverflow answer:
# https://stackoverflow.com/a/30004941
def sync_run_query(
    fn: Callable,
    session: Session,
    *,
    attempts: int = settings.DB_CONNECTION_RETRY_TIMES,
    rollback_on_exc: bool = True,
    **fn_kwargs: Any,
) -> Any:  # pragma: no cover

    while attempts > 0:
        attempts -= 1
        try:
            return fn(**fn_kwargs)
        except exc.DBAPIError as ex:
            logger.debug(f"Attempt failed: {type(ex).__name__} {ex}")
            if rollback_on_exc:
                session.rollback()

            if attempts > 0 and ex.connection_invalidated:
                logger.warning(f"Interrupted transaction: {repr(ex)}, attempts remaining:{attempts}")
            else:
                sentry_sdk.capture_message(f"Max db connection attempts reached: {repr(ex)}")
                raise


async def async_run_query(
    fn: Callable,
    session: AsyncSession,
    *,
    attempts: int = settings.DB_CONNECTION_RETRY_TIMES,
    rollback_on_exc: bool = True,
    **fn_kwargs: Any,
) -> Any:  # pragma: no cover
    while attempts > 0:
        attempts -= 1
        try:
            return await fn(**fn_kwargs)
        except exc.DBAPIError as ex:
            logger.debug(f"Attempt failed: {type(ex).__name__} {ex}")
            if rollback_on_exc:
                await session.rollback()

            if attempts > 0 and ex.connection_invalidated:
                logger.warning(f"Interrupted transaction: {repr(ex)}, attempts remaining:{attempts}")
            else:
                sentry_sdk.capture_message(f"Max db connection attempts reached: {repr(ex)}")
                raise
        except Exception as e:
            pass
