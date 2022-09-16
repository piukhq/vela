from babel.numbers import format_currency

from vela.enums import LoyaltyTypes


def build_tx_history_reasons(tx_amount: int, adjustments: dict, is_refund: bool, currency: str) -> list[str]:
    reasons = []
    for v in adjustments.values():

        amount = pence_integer_to_currency_string(abs(tx_amount), currency)
        threshold = pence_integer_to_currency_string(v["threshold"], currency)

        if v["accepted"]:
            if is_refund:
                reasons.append(f"refund of {amount} accepted")
            else:
                reasons.append(f"transaction amount {amount} meets the required threshold {threshold}")
        else:
            if is_refund:
                reasons.append(f"refund of {amount} not accepted")
            else:
                reasons.append(f"transaction amount {amount} does no meet the required threshold {threshold}")

    return reasons


def build_tx_history_earns(adjustments: dict, currency: str) -> list[dict[str, str]]:
    earns = []
    for v in adjustments.values():
        if v["type"] == LoyaltyTypes.ACCUMULATOR:
            amount = pence_integer_to_currency_string(v["amount"], currency)
        else:
            amount = str(int(v["amount"] / 100))

        earns.append({"value": amount, "type": v["type"]})

    return earns


def pence_integer_to_currency_string(value: int, currency: str, currency_sign: bool = True) -> str:
    extras: dict = {}
    if not currency_sign:
        extras = {"format": "#,##0.##"}

    return format_currency(value / 100, currency, locale="en_GB", **extras)
