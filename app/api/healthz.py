from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.sql import text
from starlette import status

from app.api.deps import get_session

healthz_router = APIRouter()


@healthz_router.get(path="/livez")
def livez() -> Any:
    return {}


@healthz_router.get(path="/readyz")
def readyz(db_session: Session = Depends(get_session)) -> Any:
    try:
        db_session.execute(text("SELECT 1"))
    except Exception as e:
        raise HTTPException(
            detail={"postgres": f"failed to connect to postgres due to error: {repr(e)}"},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return {}
