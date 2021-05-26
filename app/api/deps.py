from typing import Generator

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionMaker
from app.enums import HttpErrors
from app.models import RetailerRewards


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
    if not token == settings.VELA_AUTH_TOKEN:
        raise HttpErrors.INVALID_TOKEN.value


def retailer_is_valid(retailer_slug: str, db_session: Session = Depends(get_session)) -> RetailerRewards:
    retailer = db_session.query(RetailerRewards).filter_by(slug=retailer_slug).first()
    if not retailer:
        raise HttpErrors.INVALID_RETAILER.value

    return retailer
