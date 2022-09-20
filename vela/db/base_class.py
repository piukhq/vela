# mypy checks for sqlalchemy core 2.0 require sqlalchemy2-stubs
import logging

from typing import Any, Callable

import sentry_sdk

from retry_tasks_lib.db.models import load_models_to_metadata
from sqlalchemy import Column, DateTime, Integer, exc, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, declarative_base, declarative_mixin

from vela.core.config import settings


class ModelBase:
    id = Column(Integer, primary_key=True)


Base = declarative_base(cls=ModelBase)
load_models_to_metadata(Base.metadata)

utc_timestamp_sql = text("TIMEZONE('utc', CURRENT_TIMESTAMP)")

logger = logging.getLogger("db-base-class")


@declarative_mixin
class TimestampMixin:
    created_at = Column(DateTime, server_default=utc_timestamp_sql, nullable=False)
    updated_at = Column(
        DateTime,
        server_default=utc_timestamp_sql,
        onupdate=utc_timestamp_sql,
        nullable=False,
    )


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
