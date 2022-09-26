from fastapi import APIRouter

from vela.api.endpoints import campaign, retailer, transaction
from vela.api.healthz import healthz_router
from vela.core.config import settings

api_router = APIRouter()
api_router.include_router(healthz_router, tags=["healthz, readyz"])

api_router.include_router(retailer.router, prefix=settings.API_PREFIX)
api_router.include_router(campaign.router, prefix=settings.API_PREFIX)
api_router.include_router(transaction.router, prefix=settings.API_PREFIX)
