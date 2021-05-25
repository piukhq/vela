import logging

from uuid import UUID

import requests

from fastapi import status
from urllib3 import Retry

from app.core.config import settings
from app.enums import HttpErrors

logger = logging.getLogger(__name__)


def retry_session() -> requests.Session:  # pragma: no cover
    session = requests.Session()
    retry = Retry(total=3, allowed_methods=False, status_forcelist=[501, 502, 503, 504], backoff_factor=0.1)
    adapter = requests.adapters.HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def validate_account_holder_uuid(account_holder_uuid: UUID, retailer_slug: str) -> None:
    try:
        resp = retry_session().get(
            f"{settings.POLARIS_URL}/bpl/loyalty/{retailer_slug}/accounts/{account_holder_uuid}/status",
            headers={"Authorization": f"Token {settings.POLARIS_AUTH_TOKEN}"},
        )
        resp.raise_for_status()
    except requests.RequestException as ex:
        if resp.status_code == status.HTTP_404_NOT_FOUND:
            raise HttpErrors.USER_NOT_FOUND.value

        logger.exception("Failed to fetch account holder status from Polaris.", exc_info=ex)
        raise HttpErrors.GENERIC_HANDLED_ERROR.value

    else:
        if resp.json()["status"] != "active":
            raise HttpErrors.USER_NOT_ACTIVE.value
