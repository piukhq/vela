from enum import Enum

from vela.core.config import settings


class ActivityType(Enum):
    TX_HISTORY = f"activity.{settings.PROJECT_NAME}.tx.processed"
