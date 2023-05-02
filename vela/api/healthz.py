from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import text
from starlette import status

from vela.api.deps import get_session

healthz_router = APIRouter()


@healthz_router.get(path="/livez")
async def livez() -> Any:
    return {}


@healthz_router.get(path="/readyz")
async def readyz(db_session: AsyncSession = Depends(get_session)) -> Any:
    try:
        await db_session.execute(text("SELECT 1"))
    except Exception as ex:
        raise HTTPException(
            detail={"postgres": f"failed to connect to postgres due to error: {ex!r}"},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        ) from None

    return {}
