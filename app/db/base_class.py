# mypy checks for sqlalchemy core 2.0 require sqlalchemy2-stubs
from sqlalchemy import Column, DateTime, Integer, text
from sqlalchemy.orm import as_declarative, declarative_mixin  # type: ignore


@as_declarative()
class Base:
    id = Column(Integer, primary_key=True, index=True)


utc_timestamp_sql = text("TIMEZONE('utc', CURRENT_TIMESTAMP)")


@declarative_mixin
class TimestampMixin:
    created_at = Column(DateTime, server_default=utc_timestamp_sql, nullable=False)
    updated_at = Column(
        DateTime,
        server_default=utc_timestamp_sql,
        onupdate=utc_timestamp_sql,
        nullable=False,
    )
