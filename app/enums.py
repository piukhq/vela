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
    USER_NOT_FOUND = HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"display_message": "Unknown User.", "error": "USER_NOT_FOUND"},
    )

    USER_NOT_ACTIVE = HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"display_message": "User Account not Active", "error": "USER_NOT_ACTIVE"},
    )
    GENERIC_HANDLED_ERROR = HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={
            "display_message": "An unexpected system error occurred, please try again later.",
            "error": "INTERNAL_ERROR",
        },
    )


class RewardAdjustmentStatuses(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    FAILED = "failed"
    SUCCESS = "success"
    ACCOUNT_HOLDER_DELETED = "account_holder_deleted"
