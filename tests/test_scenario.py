"""단위는 합성 비중·합성 가격이며 실제 계좌·보유 자료가 아니다."""
import pandas as pd
import pytest

from src.scenario import asset_shocks, compound, historical_2022, simulate_portfolio


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
