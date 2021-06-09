# mypy checks for sqlalchemy core 2.0 require sqlalchemy2-stubs
import logging

from contextlib import contextmanager
from typing import Generator, Union

import sentry_sdk

from sqlalchemy import Column, DateTime, Integer, exc, text
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore # pylance cant find the ext.asyncio package
from sqlalchemy.orm import declarative_base  # type: ignore
from sqlalchemy.orm import Session, declarative_mixin  # type: ignore

from app.core.config import settings
from app.version import __version__


class ModelBase:
    id = Column(Integer, primary_key=True, index=True)


Base = declarative_base(cls=ModelBase)

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
def retry_query(session: Union[Session, AsyncSession], attempts: int = settings.DB_CONNECTION_RETRY_TIMES) -> Generator:
    """Retry any queries (transactions) that are interrupted by a connection error"""

    while attempts > 0:
        attempts -= 1
        try:
            yield
            break
        except exc.DBAPIError as e:
            if attempts > 0 and e.connection_invalidated:
                logger.warning(f"Interrupted transaction, attempts remaining:{attempts}")
                session.rollback()
            else:
                sentry_sdk.capture_message(f"Max db connection attempts reached: {e}")
                raise
