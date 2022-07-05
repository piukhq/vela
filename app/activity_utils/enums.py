from enum import Enum

from app.core.config import settings


class ActivityType(Enum):
    TX_HISTORY = f"activity.{settings.PROJECT_NAME}.tx.processed"
