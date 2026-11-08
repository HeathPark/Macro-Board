"""목표 비중과 계좌별 평가. 모든 금액의 단위는 만원이다."""
from __future__ import annotations

import math
from collections.abc import Mapping

import pandas as pd

SAFE_ASSETS = frozenset({"DEPOSIT", "USDST", "USTB3M", "KTB3", "KTB30", "UST30", "MMF", "CD"})


def blend_weights(account: Mapping, k: int, mode: str = "자동(신호 기반)") -> dict[str, float]:
    """P1/P2의 백분율 비중을 신호 개수에 따라 보간한다."""
    if not isinstance(k, (int, float)) or not math.isfinite(k) or not 0 <= k <= 3:
        raise ValueError("충족 신호 개수는 0~3이어야 합니다.")
    if mode in ("P1", "P1 고정"):
        fraction = 0.0
    elif mode in ("P2", "P2 고정"):
        fraction = 1.0
    elif mode in ("자동", "자동(신호 기반)", "블렌딩"):
        fraction = k / 3
    else:
        raise ValueError("알 수 없는 국면 선택입니다.")
    p1, p2 = account.get("P1", {}), account.get("P2", {})
    for weights in (p1, p2):
        if not weights or any(not math.isfinite(float(x)) or float(x) < 0 for x in weights.values()):
            raise ValueError("목표 비중은 유한한 0 이상 값이어야 합니다.")
        if not math.isclose(sum(float(x) for x in weights.values()), 100, abs_tol=1e-6):
            raise ValueError("계좌의 목표 비중 합은 100%이어야 합니다.")
    return {key: float(p1.get(key, 0)) + (float(p2.get(key, 0)) - float(p1.get(key, 0))) * fraction
            for key in sorted(set(p1) | set(p2))
            if float(p1.get(key, 0)) + (float(p2.get(key, 0)) - float(p1.get(key, 0))) * fraction > 1e-12}


def risk_check(weights: Mapping[str, float], cap: float = 70) -> dict:
    risk = sum(float(value) for key, value in weights.items() if key not in SAFE_ASSETS)
    return {"risk_weight": risk, "cap": float(cap), "exceeded": risk > float(cap) + 1e-9}


def universe_map(universe: Mapping | list) -> dict:
    entries = universe if isinstance(universe, list) else universe.get("universe", []) + universe.get("manual", [])
    return {entry["id"]: entry for entry in entries}


def target_rows(plan: Mapping, amounts: Mapping, k: int, mode: str, universe: Mapping | list) -> pd.DataFrame:
    lookup = universe_map(universe)
    rows = []
    for account_id, account in plan.get("accounts", plan).items():
        amount = float(amounts.get(account_id, account.get("amount", 0)) or 0)
        if not math.isfinite(amount) or amount < 0:
            raise ValueError("계좌 금액은 유한한 0 이상 값이어야 합니다.")
        for asset_id, weight in blend_weights(account, k, mode).items():
            info = lookup.get(asset_id, {})
            rows.append({"account": account_id, "label": account.get("label", account_id), "id": asset_id,
                         "name": info.get("name", asset_id), "asset_class": info.get("asset_class", "미분류"),
                         "weight": weight, "amount": amount * weight / 100})
    return pd.DataFrame(rows, columns=["account", "label", "id", "name", "asset_class", "weight", "amount"])


def price_statistics(series: pd.Series, as_of=None) -> dict:
    """관측일 이하 가격으로 수익률 계산. 달력 기준 1W/1M/3M과 직전 연말 YTD."""
    clean = pd.to_numeric(series, errors="coerce").dropna().sort_index()
    if clean.empty:
        return {"close": None, "1D": None, "1W": None, "1M": None, "3M": None, "YTD": None,
                "drawdown": None, "sparkline": []}
    clean.index = pd.to_datetime(clean.index).tz_localize(None)
    date = pd.Timestamp(as_of).tz_localize(None) if as_of is not None else clean.index[-1]
    clean = clean.loc[clean.index <= date]
    if clean.empty:
        return price_statistics(pd.Series(dtype=float))
    latest = float(clean.iloc[-1])
    date = clean.index[-1]
    result = {"close": latest, "date": date.date().isoformat(), "sparkline": clean.tail(20).tolist()}
    result["1D"] = (latest / clean.iloc[-2] - 1) * 100 if len(clean) > 1 and clean.iloc[-2] > 0 else None
    for key, cutoff in {"1W": date - pd.Timedelta(days=7), "1M": date - pd.DateOffset(months=1),
                        "3M": date - pd.DateOffset(months=3),
                        "YTD": pd.Timestamp(year=date.year, month=1, day=1) - pd.Timedelta(days=1)}.items():
        prior = clean.loc[clean.index <= cutoff]
        result[key] = (latest / prior.iloc[-1] - 1) * 100 if len(prior) and prior.iloc[-1] > 0 else None
    high = clean.loc[clean.index >= date - pd.Timedelta(days=365)].max()
    result["drawdown"] = (latest / high - 1) * 100 if high > 0 else None
    return result
