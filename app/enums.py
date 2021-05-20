from enum import Enum

from fastapi import HTTPException, status


class CampaignStatuses(Enum):
    ACTIVE = "Active"
    DRAFT = "Draft"
    CANCELLED = "Cancelled"
    ENDED = "Ended"


class HttpErrors(Enum):
    NO_ACTIVE_CAMPAIGNS = HTTPException(
        detail={"display_message": "No active campaigns found for retailer.", "error": "NO_ACTIVE_CAMPAIGNS"},
        status_code=status.HTTP_404_NOT_FOUND,
    )
    INVALID_RETAILER = HTTPException(
        detail={
            "display_message": "Requested retailer is invalid.",
            "error": "INVALID_RETAILER",
        },
        status_code=status.HTTP_403_FORBIDDEN,
    )
    INVALID_TOKEN = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "display_message": "Supplied token is invalid.",
            "error": "INVALID_TOKEN",
        },
    )
    DUPLICATE_TRANSACTION = HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"display_message": "Duplicate Transaction.", "error": "DUPLICATE_TRANSACTION"},
    )
