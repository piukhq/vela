import logging

logger = logging.getLogger(__name__)


class BalanceAdjustmentEnqueueException(Exception):
    def __init__(self, retry_task_id: int, *args: object) -> None:
        super().__init__(*args)
        self.retry_task_id = retry_task_id
