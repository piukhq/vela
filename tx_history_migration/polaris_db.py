from collections import namedtuple
from contextlib import contextmanager
from typing import Generator
from urllib.parse import urlparse

from sqlalchemy import create_engine
from sqlalchemy.ext.automap import AutomapBase, automap_base
from sqlalchemy.future import select
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.core.config import settings

PolarisTables = namedtuple("PolarisTables", "RetailerConfig AccountHolder AccountHolderTransactionHistory")


@contextmanager
def polaris_session_and_tables(polaris_db_name: str) -> Generator[tuple[Session, PolarisTables], None, None]:
    parsed_uri = urlparse(settings.SQLALCHEMY_DATABASE_URI)
    polaris_sqlalchemy_uri = parsed_uri._replace(path=f"/{polaris_db_name}").geturl()
    Base: AutomapBase = automap_base()
    try:
        engine = create_engine(polaris_sqlalchemy_uri, poolclass=NullPool, future=True, pool_pre_ping=True)
        Base.prepare(autoload_with=engine, reflect=True)

        with Session(bind=engine, future=True, expire_on_commit=False) as db_session:

            yield db_session, PolarisTables(
                Base.classes.retailer_config,
                Base.classes.account_holder,
                Base.classes.account_holder_transaction_history,
            )

    finally:
        engine.dispose(close=True)


def get_existing_history_txs_ids(polaris_db_name: str, retailer_slug: str) -> list[str]:

    with polaris_session_and_tables(polaris_db_name) as (db_session, tables):
        return (
            db_session.execute(
                select(tables.AccountHolderTransactionHistory.transaction_id)
                .select_from(tables.AccountHolderTransactionHistory)
                .join(tables.AccountHolder)
                .join(tables.RetailerConfig)
                .where(tables.RetailerConfig.slug == retailer_slug)
            )
            .scalars()
            .all()
        )
