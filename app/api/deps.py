from typing import Generator

from app.db.session import SessionMaker


def get_session() -> Generator:
    with SessionMaker() as db_session:
        yield db_session
