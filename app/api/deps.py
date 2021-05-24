from typing import Generator

from fastapi import Depends, Header

from app.core.config import settings
from app.db.session import SessionMaker
from app.enums import HttpErrors


def get_session() -> Generator:
    with SessionMaker() as db_session:
        yield db_session


def get_authorization_token(authorization: str = Header(None)) -> str:
    try:
        token_type, token_value = authorization.split(" ")
        if token_type.lower() == "token":
            return token_value
    except (ValueError, AttributeError):
        pass

    raise HttpErrors.INVALID_TOKEN.value


# user as in user of our api, not an account holder.
def user_is_authorised(token: str = Depends(get_authorization_token)) -> None:
    if not token == settings.AUTH_TOKEN:
        raise HttpErrors.INVALID_TOKEN.value
