from dataclasses import dataclass

from vela.core.utils import calculate_adjustment_amount_for_earn_rule
from vela.enums import LoyaltyTypes
from vela.models.retailer import EarnRule


@dataclass
class AdjustmentAmountTestData:
    loyalty_type: LoyaltyTypes
    earn_rule: EarnRule
    reward_rule_allocation_window: int
    tx_amount: int
    expected_accepted: bool
    expected_adjustment_amount: int


def test_calculate_adjustment_amount_for_earn_rule() -> None:
    test_data: list[tuple] = [
        (
            "Default Adjustment",
            AdjustmentAmountTestData(
                loyalty_type=LoyaltyTypes.ACCUMULATOR,
                earn_rule=EarnRule(
                    threshold=0,
                    increment=None,
                    increment_multiplier=1,
                    max_amount=0,
                ),
                reward_rule_allocation_window=0,
                tx_amount=600,
                expected_accepted=True,
                expected_adjustment_amount=600,
            ),
        ),
        (
            "Adjustment with tx_amount < threshold",
            AdjustmentAmountTestData(
                loyalty_type=LoyaltyTypes.ACCUMULATOR,
                earn_rule=EarnRule(
                    threshold=500,
                    increment=None,
                    increment_multiplier=1,
                    max_amount=0,
                ),
                reward_rule_allocation_window=0,
                tx_amount=400,
                expected_accepted=False,
                expected_adjustment_amount=0,
            ),
        ),
        (
            "Adjustment with tx_amount > max amount",
            AdjustmentAmountTestData(
                loyalty_type=LoyaltyTypes.ACCUMULATOR,
                earn_rule=EarnRule(
                    threshold=500,
                    increment=None,
                    increment_multiplier=1,
                    max_amount=1000,
                ),
                reward_rule_allocation_window=0,
                tx_amount=1200,
                expected_accepted=True,
                expected_adjustment_amount=1000,
            ),
        ),
        (
            "tx_amount < max amount but adjusment + increment multiplier > max_amount",
            AdjustmentAmountTestData(
                loyalty_type=LoyaltyTypes.ACCUMULATOR,
                earn_rule=EarnRule(
                    threshold=500,
                    increment=None,
                    increment_multiplier=1.5,
                    max_amount=1000,
                ),
                reward_rule_allocation_window=0,
                tx_amount=800,
                expected_accepted=True,
                expected_adjustment_amount=1200,
            ),
        ),
        (
            "Default Refund Adjustment",
            AdjustmentAmountTestData(
                loyalty_type=LoyaltyTypes.ACCUMULATOR,
                earn_rule=EarnRule(
                    threshold=500,
                    increment=None,
                    increment_multiplier=1,
                    max_amount=0,
                ),
                reward_rule_allocation_window=2,
                tx_amount=-600,
                expected_accepted=True,
                expected_adjustment_amount=-600,
            ),
        ),
        (
            "Refund Adjustment with increment multiplier",
            AdjustmentAmountTestData(
                loyalty_type=LoyaltyTypes.ACCUMULATOR,
                earn_rule=EarnRule(
                    threshold=500,
                    increment=None,
                    increment_multiplier=1.5,
                    max_amount=0,
                ),
                reward_rule_allocation_window=2,
                tx_amount=-600,
                expected_accepted=True,
                expected_adjustment_amount=-900,
            ),
        ),
        (
            "Refund adjustment with abs(tx_amount) > max_amount",
            AdjustmentAmountTestData(
                loyalty_type=LoyaltyTypes.ACCUMULATOR,
                earn_rule=EarnRule(
                    threshold=500,
                    increment=None,
                    increment_multiplier=1,
                    max_amount=1000,
                ),
                reward_rule_allocation_window=2,
                tx_amount=-1200,
                expected_accepted=True,
                expected_adjustment_amount=-1000,
            ),
        ),
        (
            "Default adjustment for STAMPS",
            AdjustmentAmountTestData(
                loyalty_type=LoyaltyTypes.STAMPS,
                earn_rule=EarnRule(
                    threshold=500,
                    increment=200,
                    increment_multiplier=1,
                    max_amount=0,
                ),
                reward_rule_allocation_window=0,
                tx_amount=600,
                expected_accepted=True,
                expected_adjustment_amount=200,
            ),
        ),
        (
            "Refund not accepted for STAMPS",
            AdjustmentAmountTestData(
                loyalty_type=LoyaltyTypes.STAMPS,
                earn_rule=EarnRule(
                    threshold=500,
                    increment=200,
                    increment_multiplier=1,
                    max_amount=0,
                ),
                reward_rule_allocation_window=0,
                tx_amount=-600,
                expected_accepted=False,
                expected_adjustment_amount=0,
            ),
        ),
    ]

    for data in test_data:
        adjustment_data = data[1]
        accepted, adjustment = calculate_adjustment_amount_for_earn_rule(
            adjustment_data.tx_amount,
            adjustment_data.loyalty_type,
            adjustment_data.earn_rule,
            adjustment_data.reward_rule_allocation_window,
        )

        assert (accepted, adjustment) == (
            adjustment_data.expected_accepted,
            adjustment_data.expected_adjustment_amount,
        ), f"Test case: {data[0]} ({data[1].loyalty_type.name})"
