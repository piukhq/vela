from app.models.retailer import Campaign, EarnRule, LoyaltyTypes


def calculate_adjustment_amounts(campaigns: list[Campaign], tx_amount: int) -> dict:
    adjustment_amounts: dict[str, dict] = {}

    # pylint: disable=chained-comparison
    for campaign in campaigns:
        adjustment_amounts[campaign.slug] = {
            "type": campaign.loyalty_type,
            "amount": 0,
            "threshold": None,
            "accepted": False,
        }

        for earn_rule in campaign.earn_rules:
            # NOTE: Business logic mandates that the earn rules of a campaign must have the same threshold.
            # in case of discrepacies we set the threshold to the lowest of all thresholds.
            if adjustment_amounts[campaign.slug]["threshold"]:
                adjustment_amounts[campaign.slug]["threshold"] = min(
                    adjustment_amounts[campaign.slug]["threshold"], earn_rule.threshold
                )
            else:
                adjustment_amounts[campaign.slug]["threshold"] = earn_rule.threshold

            accepted, adjustment = calculate_adjustment_amount_for_earn_rule(
                tx_amount, campaign.loyalty_type, earn_rule, campaign.reward_rule.allocation_window
            )

            adjustment_amounts[campaign.slug]["amount"] = adjustment
            adjustment_amounts[campaign.slug]["accepted"] = accepted

    return adjustment_amounts


def calculate_adjustment_amount_for_earn_rule(
    tx_amount: int, loyalty_type: LoyaltyTypes, earn_rule: EarnRule, allocation_window: int
) -> tuple[bool, int]:
    accepted: bool = False
    adjustment_amount: int = 0

    if loyalty_type == LoyaltyTypes.ACCUMULATOR:
        accepted, adjustment_amount = calculate_amount_for_accumulator(
            adjustment_amount, tx_amount, earn_rule, allocation_window
        )

    elif loyalty_type == LoyaltyTypes.STAMPS and tx_amount >= earn_rule.threshold:
        adjustment_amount = earn_rule.increment * earn_rule.increment_multiplier
        accepted = True

    return accepted, adjustment_amount


def calculate_amount_for_accumulator(
    adjustment_amount: int, tx_amount: int, earn_rule: EarnRule, allocation_window: int
) -> tuple[bool, int]:
    accepted: bool = False
    accepted_refund = bool(tx_amount < 0 and allocation_window)

    if earn_rule.max_amount and abs(tx_amount) > earn_rule.max_amount:
        if accepted_refund:
            adjustment_amount = -(earn_rule.max_amount)
            accepted = True
        elif tx_amount > 0:
            adjustment_amount = earn_rule.max_amount
            accepted = True
    elif accepted_refund or tx_amount >= earn_rule.threshold:
        adjustment_amount = tx_amount * earn_rule.increment_multiplier
        accepted = True

    return accepted, adjustment_amount
