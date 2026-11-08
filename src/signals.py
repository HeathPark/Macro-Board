"""관측 가능한 자료만으로 판정하는 국면 전환 신호."""
from __future__ import annotations

import pandas as pd


def _series(frame: pd.DataFrame, key: str, now: pd.Timestamp) -> pd.Series:
    if frame.empty or not {"date", "id", "close"}.issubset(frame.columns):
        return pd.Series(dtype=float)
    rows = frame.loc[frame["id"] == key, ["date", "close"]].copy()
    rows["date"] = pd.to_datetime(rows["date"], errors="coerce", utc=True).dt.tz_localize(None)
    rows["close"] = pd.to_numeric(rows["close"], errors="coerce")
    rows = rows.dropna().sort_values("date").drop_duplicates("date", keep="last")
    result = rows.set_index("date")["close"]
    return result.loc[result.index <= now]


def _fresh(series: pd.Series, now: pd.Timestamp, days: int) -> bool:
    return bool(len(series) and now - series.index[-1] <= pd.Timedelta(days=days))


def _covered(series: pd.Series, cutoff: pd.Timestamp, allowance=7) -> bool:
    return bool(len(series) >= 2 and series.index[0] <= cutoff + pd.Timedelta(days=allowance))


def _rate_covered(series: pd.Series, cutoff: pd.Timestamp, now: pd.Timestamp, max_gap: int) -> bool:
    before = series.loc[series.index <= cutoff]
    if before.empty:
        return False
    window_dates = series.loc[series.index >= before.index[-1]].index
    # 두 끝점을 포함한 관측 공백을 확인해 두 점만으로 120일 무변경을 추정하지 않는다.
    dates = pd.DatetimeIndex([cutoff, *window_dates[window_dates > cutoff], now]).sort_values()
    return bool(len(window_dates) >= 2 and (dates.to_series().diff().dropna() <= pd.Timedelta(days=max_gap)).all())


def _result(key, label, status, detail, value=None, threshold=None):
    return {"id": key, "label": label, "status": status, "detail": detail, "value": value, "threshold": threshold}


def _combine(parts: list[tuple[str, str]]) -> tuple[str, str]:
    statuses = [part[0] for part in parts]
    if "충족" in statuses:
        status = "충족"
    elif "근접" in statuses:
        status = "근접"
    elif "데이터 없음" in statuses:
        status = "데이터 없음"
    else:
        status = "미충족"
    return status, " · ".join(detail for _, detail in parts)


def evaluate_signals(macro_df: pd.DataFrame, config: dict, as_of=None) -> list[dict]:
    """오래된 값과 부족한 관측 기간은 미충족 대신 '데이터 없음'으로 표시한다."""
    now = (pd.Timestamp(as_of) if as_of is not None else pd.Timestamp.now(tz="Asia/Seoul")).tz_localize(None).normalize()
    cfg = config.get("signals", config)
    near = float(cfg.get("near_ratio", 0.8))
    fresh_days = int(cfg.get("daily_max_stale_days", 14))
    t1 = cfg.get("T1", {})
    days = int(t1.get("lookback_days", 120))
    cutoff = now - pd.Timedelta(days=days)
    rates = [_series(macro_df, key, now) for key in ("KR_BASE_RATE", "DFEDTARU")]
    rate_parts, no_hikes, has_cut, enough = [], True, False, True
    progress = []
    for name, series in zip(("한은", "연준"), rates):
        if not _fresh(series, now, int(t1.get("max_stale_days", 14))) or not _rate_covered(series, cutoff, now, int(t1.get("max_gap_days", 14))):
            enough = False
            rate_parts.append(f"{name}: 데이터 없음(최근 값 또는 {days}일 관측 부족)")
            continue
        differences = series.diff()
        window = differences.loc[differences.index > cutoff]
        increases = differences.loc[differences > 1e-8]
        raises = window.loc[window > 1e-8]
        has_cut |= bool((window < -1e-8).any())
        no_hikes &= raises.empty
        elapsed = min(days, (now - increases.index[-1]).days) if len(increases) else days
        progress.append(elapsed)
        rate_parts.append(f"{name}: {float(series.iloc[-1]):.2f}%, 최근 인상 없는 기간 {elapsed}일 / {days}일")
    status = "데이터 없음" if not enough else ("강한 충족" if no_hikes and has_cut else "충족" if no_hikes else
                                                       "근접" if min(progress) >= days * near else "미충족")
    first = _result("T1", "긴축 종료", status, " · ".join(rate_parts), min(progress) if enough else None, days)

    t2 = cfg.get("T2", {})
    cpi = _series(macro_df, "CPILFESL", now)
    periods = int(t2.get("cpi_declining_months", 3))
    cpi_part = ("데이터 없음", "미 근원 CPI: 데이터 없음(연속 월 관측 부족 또는 지연)")
    if _fresh(cpi, now, int(cfg.get("cpi_max_stale_days", 75))):
        monthly = cpi.resample("MS").last()
        # 빈 월을 채우지 않아 실제로 누락된 관측값이 연속 하락으로 오인되지 않는다.
        annual = ((monthly / monthly.shift(3)) ** 4 - 1) * 100
        recent = annual.tail(periods + 1)
        if len(recent) == periods + 1 and recent.notna().all():
            drops = (recent.diff().dropna() < 0).tolist()
            consecutive = 0
            for drop in reversed(drops):
                if not drop:
                    break
                consecutive += 1
            cpi_status = "충족" if consecutive >= periods else "근접" if consecutive >= periods * near else "미충족"
            cpi_part = (cpi_status, f"미 근원 CPI 3개월 연율 {float(recent.iloc[-1]):.2f}%, 연속 하락 {consecutive}개월 / {periods}개월")
    oil = _series(macro_df, "WTI", now)
    oil_cutoff = now - pd.DateOffset(months=int(t2.get("lookback_months", 6)))
    oil_part, oil_value = ("데이터 없음", "WTI: 데이터 없음(6개월 관측 부족 또는 지연)"), None
    oil_threshold = abs(float(t2.get("oil_drawdown_pct", -20)))
    if _fresh(oil, now, fresh_days) and _covered(oil, oil_cutoff):
        high = oil.loc[oil.index >= oil_cutoff].max()
        if high > 0:
            oil_value = (1 - oil.iloc[-1] / high) * 100
            oil_part = ("충족" if oil_value + 1e-9 >= oil_threshold else "근접" if oil_value + 1e-9 >= oil_threshold * near else "미충족",
                        f"WTI 6개월 고점 대비 {-oil_value:.2f}% / 임계값 {-oil_threshold:.1f}%")
    status, detail = _combine([cpi_part, oil_part])
    second = _result("T2", "물가·유가 진정", status, detail, -oil_value if oil_value is not None else None, -oil_threshold)

    t3 = cfg.get("T3", {})
    kospi = _series(macro_df, "KOSPI", now)
    equity_cutoff = now - pd.Timedelta(days=int(t3.get("kospi_lookback_days", 365)))
    equity_part, equity_value = ("데이터 없음", "코스피: 데이터 없음(1년 관측 부족 또는 지연)"), None
    equity_threshold = abs(float(t3.get("kospi_drawdown_pct", -30)))
    if _fresh(kospi, now, fresh_days) and _covered(kospi, equity_cutoff):
        high = kospi.loc[kospi.index >= equity_cutoff].max()
        if high > 0:
            equity_value = (1 - kospi.iloc[-1] / high) * 100
            equity_part = ("충족" if equity_value + 1e-9 >= equity_threshold else "근접" if equity_value + 1e-9 >= equity_threshold * near else "미충족",
                           f"코스피 1년 고점 대비 {-equity_value:.2f}% / 임계값 {-equity_threshold:.1f}%")
    spread = _series(macro_df, "BAMLH0A0HYM2", now)
    spread_cutoff = now - pd.DateOffset(months=int(t3.get("lookback_months", 6)))
    spread_part = ("데이터 없음", "하이일드 스프레드: 데이터 없음(6개월 관측 부족 또는 지연)")
    range_limit = float(t3.get("spread_range_pp", 1.5))
    drop_limit = float(t3.get("spread_drop_pp", 0.5))
    if _fresh(spread, now, fresh_days) and _covered(spread, spread_cutoff):
        window = spread.loc[spread.index >= spread_cutoff]
        width, drop = float(window.max() - window.min()), float(window.max() - window.iloc[-1])
        spread_status = "충족" if width + 1e-9 >= range_limit and drop + 1e-9 >= drop_limit else (
            "근접" if width + 1e-9 >= range_limit * near and drop + 1e-9 >= drop_limit * near else "미충족")
        spread_part = (spread_status, f"하이일드 범위 {width:.2f}%p / {range_limit:.2f}%p, 고점 대비 하락 {drop:.2f}%p / {drop_limit:.2f}%p")
    status, detail = _combine([equity_part, spread_part])
    third = _result("T3", "시장 스트레스 정점", status, detail, -equity_value if equity_value is not None else None, -equity_threshold)
    return [first, second, third]


def phase_from_signals(signals: list[dict]) -> dict:
    k = sum(signal.get("status") in {"충족", "강한 충족"} for signal in signals)
    return {"k": k, "phase": "P1" if k == 0 else "P2" if k == 3 else f"전환 {k}/3",
            "incomplete": len(signals) != 3 or any(signal.get("status") == "데이터 없음" for signal in signals)}
