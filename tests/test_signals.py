import pandas as pd

from src.signals import evaluate_signals, phase_from_signals

NOW = pd.Timestamp("2025-07-01")


def frame(item, values, dates=None):
    if dates is None:
        dates = pd.date_range(end=NOW, periods=len(values), freq="D")
    return pd.DataFrame({"date": dates, "id": item, "close": values, "source": "합성 테스트"})


def signal(data, index):
    return evaluate_signals(data, {}, as_of=NOW)[index]


def test_empty_input_is_unknown_not_false_green():
    result = evaluate_signals(pd.DataFrame(), {}, as_of=NOW)
    assert all(row["status"] == "데이터 없음" for row in result)
    assert phase_from_signals(result) == {"k": 0, "phase": "P1", "incomplete": True}


def test_t1_no_hikes_and_cut_strength():
    rates = pd.concat([frame("KR_BASE_RATE", [3.0] * 121), frame("DFEDTARU", [5.0] * 121)], ignore_index=True)
    assert signal(rates, 0)["status"] == "충족"
    rates.loc[rates.index[-1], "close"] = 4.75
    assert signal(rates, 0)["status"] == "강한 충족"


def test_t1_requires_both_rates_coverage_and_freshness():
    assert signal(frame("KR_BASE_RATE", [3.0] * 121), 0)["status"] == "데이터 없음"
    rates = pd.concat([frame("KR_BASE_RATE", [3.0] * 100), frame("DFEDTARU", [5.0] * 100)])
    assert signal(rates, 0)["status"] == "데이터 없음"
    two_points = pd.concat([frame(item, [3, 3], [NOW - pd.Timedelta(days=120), NOW])
                            for item in ("KR_BASE_RATE", "DFEDTARU")])
    assert signal(two_points, 0)["status"] == "데이터 없음"


def test_t1_recent_hike_is_red_and_96_days_is_near():
    for elapsed, expected in [(2, "미충족"), (100, "근접")]:
        values = [4.0] * (121 - elapsed) + [4.25] * elapsed
        rates = pd.concat([frame("KR_BASE_RATE", [3.0] * 121), frame("DFEDTARU", values)])
        assert signal(rates, 0)["status"] == expected


def test_oil_or_branch_suffices_and_threshold_is_configurable():
    oil = frame("WTI", [100] * 200 + [79])
    assert signal(oil, 1)["status"] == "충족"
    assert evaluate_signals(oil, {"T2": {"oil_drawdown_pct": -25}}, as_of=NOW)[1]["status"] == "근접"
    oil.loc[oil.index[-1], "close"] = 95
    assert signal(oil, 1)["status"] == "데이터 없음"  # CPI OR branch cannot be disproved.


def test_cpi_three_month_annualized_declines_with_consecutive_months():
    prices, value = [], 100.0
    for inflation in [0.012, 0.011, 0.01, 0.009, 0.008, 0.007, 0.006]:
        value *= 1 + inflation
        prices.append(value)
    dates = pd.date_range("2024-12-01", periods=7, freq="MS")
    cpi = frame("CPILFESL", prices, dates)
    assert signal(cpi, 1)["status"] == "충족"
    assert signal(cpi.drop(index=3), 1)["status"] == "데이터 없음"


def test_t3_requires_hy_range_and_retrace_together():
    spread = frame("BAMLH0A0HYM2", [3] * 190 + [5] * 10 + [4.4])
    assert signal(spread, 2)["status"] == "충족"
    spread.loc[spread.index[-1], "close"] = 5
    assert signal(spread, 2)["status"] == "데이터 없음"
    kospi = frame("KOSPI", [100] * 365 + [69])
    assert signal(kospi, 2)["status"] == "충족"


def test_stale_data_and_future_data_do_not_satisfy_signals():
    stale = frame("WTI", [100] * 199 + [50], pd.date_range(end=NOW - pd.Timedelta(days=30), periods=200))
    future = frame("WTI", [50], [NOW + pd.Timedelta(days=1)])
    assert signal(pd.concat([stale, future]), 1)["status"] == "데이터 없음"


def test_all_three_signals_map_to_p2():
    assert phase_from_signals([{"status": "강한 충족"}, {"status": "충족"}, {"status": "충족"}])["phase"] == "P2"


def test_configurable_lookbacks_hy_thresholds_and_exact_threshold():
    kospi = frame("KOSPI", [100] * 30 + [70])
    cfg = {"T3": {"kospi_lookback_days": 30, "kospi_drawdown_pct": -30}}
    assert evaluate_signals(kospi, cfg, as_of=NOW)[2]["status"] == "충족"
    oil = frame("WTI", [100] * 200 + [80])
    assert signal(oil, 1)["status"] == "충족"
    spread = frame("BAMLH0A0HYM2", [3] * 190 + [4] * 10 + [3.8])
    cfg = {"T3": {"spread_range_pp": 1.0, "spread_drop_pp": 0.2}}
    assert evaluate_signals(spread, cfg, as_of=NOW)[2]["status"] == "충족"
