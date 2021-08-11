import logging

logger = logging.getLogger(__name__)


class BalanceAdjustmentEnqueueException(Exception):
    def __init__(self, reward_adjustment_id: int, *args: object) -> None:
        super().__init__(*args)
        self.reward_adjustment_id = reward_adjustment_id
