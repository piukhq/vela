from enum import Enum

from fastapi import HTTPException, status


class CampaignStatuses(Enum):
    ACTIVE = "Active"
    DRAFT = "Draft"
    CANCELLED = "Cancelled"
    ENDED = "Ended"


class HttpErrors(Enum):
    NO_ACCOUNT_FOUND = HTTPException(
        detail={
            "display_message": "Account not found for provided credentials.",
            "error": "NO_ACCOUNT_FOUND",
        },
        status_code=status.HTTP_404_NOT_FOUND,
    )
    INVALID_RETAILER = HTTPException(
        detail={
            "display_message": "Requested retailer is invalid.",
            "error": "INVALID_RETAILER",
        },
        status_code=status.HTTP_403_FORBIDDEN,
    )
    ACCOUNT_EXISTS = HTTPException(
        detail={
            "display_message": "It appears this account already exists.",
            "error": "ACCOUNT_EXISTS",
            "fields": ["email"],
        },
        status_code=status.HTTP_409_CONFLICT,
    )
    INVALID_TOKEN = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "display_message": "Supplied token is invalid.",
            "error": "INVALID_TOKEN",
        },
    )
