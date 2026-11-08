"""단위는 합성 비중·합성 가격이며 실제 계좌·보유 자료가 아니다."""
import pandas as pd
import pytest

from src.scenario import asset_shocks, compound, historical_2022, instrument_shocks, simulate_portfolio


def test_compound_not_sum():
    assert compound(-0.20, 0.10) == pytest.approx(-0.12)
    assert compound(0.10, 0.10) == pytest.approx(0.21)


def test_bond_duration_uses_percentage_points_and_half_year_carry():
    shocks = asset_shocks({"kr_rate": 0.50, "us_rate": 0.40, "usdkrw": 8})
    assert shocks["KR_SHORT_BOND"] == pytest.approx(0.036 * 0.5 - 2.8 * 0.005)
    assert shocks["KR_LONG_BOND"] == pytest.approx(0.035 * 0.5 - 28 * 0.005)
    assert shocks["LONG_KTB_DIRECT"] == pytest.approx(0.035 * 0.5 - 12 * 0.005)
    assert shocks["US_LONG_BOND_KRW"] == pytest.approx((1 + 0.053 * 0.5 - 16.3 * 0.004) * 1.08 - 1)


def test_currency_gold_equity_and_hedged_oil():
    shocks = asset_shocks({"usdkrw": 10, "gold": -3, "sp500": -20, "premium": 2, "wti": 30, "kospi": -25})
    assert shocks["GOLD_KRW"] == pytest.approx(0.97 * 1.1 - 1)
    assert shocks["KRX_GOLD_SPOT"] == pytest.approx(0.97 * 1.1 * 1.02 - 1)
    assert shocks["US_EQ_USD"] == pytest.approx(-0.12)
    assert shocks["USD_CASH"] == pytest.approx(1.0195 * 1.1 - 1)
    assert shocks["KR_EQ_DEF"] == pytest.approx(-0.15)
    assert shocks["OIL"] == pytest.approx(0.30)


def test_configurable_carry_duration_horizon():
    shocks = asset_shocks({"kr_rate": 1}, {"horizon": 1, "carry": {"KR_SHORT_BOND": 4}, "duration": {"KTB3": 2}})
    assert shocks["KR_SHORT_BOND"] == pytest.approx(0.02)


def _manual_rates():
    return {"manual": [{"id": "CMA", "asset_class": "KR_CASH", "rate": 2.85},
                       {"id": "NOTE_1Y", "asset_class": "DEPOSIT", "rate": 5.10},
                       {"id": "DEPOSIT", "asset_class": "DEPOSIT", "rate": 3.50},
                       {"id": "USD_NOTE", "asset_class": "USD_CASH", "rate": 3.75, "currency": "USD"}]}


def test_manual_rates_distinguish_products_in_same_class_and_compound_fx():
    shocks = instrument_shocks({"usdkrw": 10}, _manual_rates())
    assert shocks["CMA"] == pytest.approx(0.0285 * 0.5)
    assert shocks["NOTE_1Y"] == pytest.approx(0.051 * 0.5)
    assert shocks["DEPOSIT"] == pytest.approx(0.035 * 0.5)
    assert shocks["USD_NOTE"] == pytest.approx((1 + 0.0375 * 0.5) * 1.1 - 1)
    assert shocks["NOTE_1Y"] != shocks["DEPOSIT"]


def test_editing_item_rate_changes_only_that_instrument():
    universe = _manual_rates()
    before = instrument_shocks({}, universe)
    universe["manual"][1]["rate"] = 4.0
    after = instrument_shocks({}, universe)
    assert after["NOTE_1Y"] == pytest.approx(0.04 * 0.5)
    assert after["NOTE_1Y"] != before["NOTE_1Y"]
    for item in ("CMA", "DEPOSIT", "USD_NOTE"):
        assert after[item] == before[item]


def test_item_rates_propagate_through_account_and_total_contributions():
    # 개인정보가 아닌 정규화된 단위 명목액을 네 상품에 균등 배분한다.
    weights = {item["id"]: 25 for item in _manual_rates()["manual"]}
    plan = {"accounts": {"synthetic": {"P1": weights, "P2": weights}}}
    result = simulate_portfolio(plan, {"synthetic": 1}, _manual_rates(), {"usdkrw": 10})
    expected = (0.0285 * 0.5 + 0.051 * 0.5 + 0.035 * 0.5 + (1.01875 * 1.1 - 1)) / 4
    assert result["pnl"] == pytest.approx(expected)
    assert result["accounts"]["pnl"].sum() == pytest.approx(expected)
    assert result["contributions"]["pnl"].sum() == pytest.approx(expected)
    contributions = result["contributions"].set_index("id")
    assert contributions.loc["NOTE_1Y", "shock"] == pytest.approx(0.0255)
    assert contributions.loc["DEPOSIT", "shock"] == pytest.approx(0.0175)


@pytest.mark.parametrize("rate", [float("nan"), float("inf"), "SYNTHETIC_INVALID_RATE", True])
def test_invalid_manual_rate_uses_fixed_error_without_value(rate):
    universe = {"manual": [{"id": "SYNTHETIC", "asset_class": "DEPOSIT", "rate": rate}]}
    with pytest.raises(ValueError) as exc:
        instrument_shocks({}, universe)
    assert str(exc.value) == "상품별 금리는 유효한 숫자이어야 합니다."


def test_model_defaults_are_loaded_from_yaml(monkeypatch):
    from src.config import load_config
    model = load_config("scenarios")
    model["carry"]["DEPOSIT"] = 4.0
    model["duration"]["KTB3"] = 1.0
    model["equity_beta"]["KR_EQ_DEF"] = 0.5
    monkeypatch.setattr("src.scenario.load_config", lambda name: model)
    shocks = asset_shocks({"kr_rate": 1, "kospi": -20})
    assert shocks["DEPOSIT"] == pytest.approx(0.04 * model["horizon"])
    assert shocks["KR_SHORT_BOND"] == pytest.approx(0.036 * model["horizon"] - 0.01)
    assert shocks["KR_EQ_DEF"] == pytest.approx(-0.10)


def test_zero_amounts_do_not_require_personal_defaults():
    plan = {"accounts": {"synthetic": {"P1": {"X": 100}, "P2": {"X": 100}}}}
    universe = {"manual": [{"id": "X", "asset_class": "DEPOSIT"}]}
    result = simulate_portfolio(plan, {}, universe, {}, {})
    assert result["total_amount"] == 0 and result["pnl"] == 0 and result["return_pct"] == 0


def test_unit_notional_contributions_match_account_and_total():
    # 개인정보가 아닌 정규화된 단위 명목액으로 합산 불변식을 확인한다.
    plan = {"accounts": {"synthetic": {"P1": {"CASH": 50, "EQUITY": 50},
                                        "P2": {"EQUITY": 100}}}}
    universe = {"manual": [{"id": "CASH", "asset_class": "DEPOSIT"},
                            {"id": "EQUITY", "asset_class": "US_EQ_USD"}]}
    result = simulate_portfolio(plan, {"synthetic": 1}, universe,
                                {"sp500": -20, "usdkrw": 10}, k=0)
    expected = 0.5 * 0.035 * 0.5 + 0.5 * (0.8 * 1.1 - 1)
    assert result["pnl"] == pytest.approx(expected)
    assert result["return_pct"] == pytest.approx(expected * 100)
    assert result["contributions"]["pnl"].sum() == pytest.approx(expected)
    assert result["accounts"]["pnl"].sum() == pytest.approx(expected)


def test_2022_reconstruction_excludes_demo_and_requires_every_input():
    rows = []
    for item in ["KR3Y", "US10Y", "USDKRW", "KOSPI", "SP500", "GOLD_USD", "WTI"]:
        for date, close in [("2022-01-03", 100), ("2022-06-30", 110)]:
            rows.append({"date": date, "id": item, "close": close, "source": "합성 테스트"})
    prices = pd.DataFrame([{"date": date, "id": item, "close": close, "source": "합성 테스트"}
                           for item in ["SEC", "HYNIX"] for date, close in [("2022-01-03", 100), ("2022-06-30", 90)]])
    result = historical_2022(pd.DataFrame(rows), prices)
    assert result["missing"] == []
    assert result["inputs"]["kr_rate"] == 10
    assert result["inputs"]["kospi"] == pytest.approx(10)
    assert result["inputs"]["semi"] == pytest.approx(-10)
    prices["source"] = "DEMO"
    result = historical_2022(pd.DataFrame(rows), prices)
    assert result["inputs"] is None
    assert result["missing"] == ["SEC", "HYNIX"]
