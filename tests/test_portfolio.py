"""정규화 비중과 합성 가격만 사용하며 개인 금액·보유 내역을 포함하지 않는다."""
import pandas as pd
import pytest

from src.portfolio import blend_weights, price_statistics, risk_check, target_rows


def test_one_signal_blends_endpoints_and_preserves_total():
    account = {"P1": {"DEPOSIT": 100}, "P2": {"DEPOSIT": 10, "SPX": 90}}
    assert blend_weights(account, 1) == {"DEPOSIT": 70, "SPX": 30}
    assert sum(blend_weights(account, 2).values()) == pytest.approx(100)
    assert blend_weights(account, 2, "P1 고정") == account["P1"]
    assert blend_weights(account, 0, "P2 고정") == account["P2"]


def test_retirement_warning_is_strictly_over_70_and_sofr_is_risk():
    assert not risk_check({"DEPOSIT": 30, "SPX": 70})["exceeded"]
    result = risk_check({"DEPOSIT": 29, "SPX": 70, "SOFR": 1})
    assert result == {"risk_weight": 71, "cap": 70.0, "exceeded": True}
    assert not risk_check({"UST30": 50, "KTB30": 50})["exceeded"]


def test_invalid_weights_are_not_silently_normalized():
    with pytest.raises(ValueError):
        blend_weights({"P1": {"SPX": 90}, "P2": {"SPX": 100}}, 1)
    with pytest.raises(ValueError):
        blend_weights({"P1": {"SPX": 100}, "P2": {"SPX": 100}}, 4)


def test_no_default_personal_amounts_in_targets():
    plan = {"accounts": {"synthetic": {"label": "합성 계좌", "P1": {"X": 100}, "P2": {"X": 100}}}}
    frame = target_rows(plan, {}, 0, "P1", {"manual": [{"id": "X", "name": "합성", "asset_class": "DEPOSIT"}]})
    assert frame["amount"].sum() == 0


def test_price_statistics_calendar_periods_and_ytd():
    data = pd.read_csv("tests/fixtures/price_statistics_synthetic.csv", parse_dates=["date"])
    result = price_statistics(data.set_index("date")["close"])
    assert result["YTD"] == pytest.approx(20)
    assert result["1W"] == pytest.approx(120 / 115 * 100 - 100)
    assert result["drawdown"] == pytest.approx(-20)
    assert result["1D"] == pytest.approx(120 / 150 * 100 - 100)


def test_new_listing_has_no_invented_historical_returns():
    result = price_statistics(pd.Series([100], index=pd.to_datetime(["2025-06-01"])))
    assert result["1D"] is None and result["YTD"] is None
    assert price_statistics(pd.Series(dtype=float))["close"] is None
