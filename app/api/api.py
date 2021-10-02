from fastapi import APIRouter

from app.api.endpoints import campaign, retailer, transaction
from app.api.healthz import healthz_router
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(healthz_router, tags=["healthz, readyz"])

api_router.include_router(retailer.router, prefix=settings.API_PREFIX)
api_router.include_router(campaign.router, prefix=settings.API_PREFIX)
api_router.include_router(transaction.router, prefix=settings.API_PREFIX)
