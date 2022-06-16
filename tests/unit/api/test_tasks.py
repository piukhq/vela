from app.activity_utils.utils import build_tx_history_earns, build_tx_history_reasons
from app.enums import LoyaltyTypes


def test_build_tx_history_reasons() -> None:
    res_eur = build_tx_history_reasons(
        1188,
        {
            1: {"accepted": True, "threshold": 1},
            2: {"accepted": False, "threshold": 2000},
        },
        False,
        "EUR",
    )
    assert res_eur == [
        "transaction amount €11.88 meets the required threshold €0.01",
        "transaction amount €11.88 does no meet the required threshold €20.00",
    ]

    refund_res_gbp = build_tx_history_reasons(
        1188,
        {
            1: {"accepted": True, "threshold": 1},
            2: {"accepted": False, "threshold": 2000},
        },
        True,
        "GBP",
    )
    assert refund_res_gbp == ["refund of £11.88 accepted", "refund of £11.88 not accepted"]


def test_build_tx_history_earns() -> None:
    res = build_tx_history_earns(
        {
            1: {"type": LoyaltyTypes.ACCUMULATOR, "amount": 1199},
            2: {"type": LoyaltyTypes.STAMPS, "amount": 5},
        },
        "GBP",
    )
    assert res == [
        {"value": "£11.99", "type": LoyaltyTypes.ACCUMULATOR},
        {"value": "5", "type": LoyaltyTypes.STAMPS},
    ]
