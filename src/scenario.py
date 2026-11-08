"""L1 가정(%, %p) → L2 수익률(소수) → 계좌별 손익(만원)."""
from __future__ import annotations

import math
from collections.abc import Mapping

import pandas as pd

from src.portfolio import target_rows

DEFAULT_CARRY = {"KR_CASH": 3.0, "DEPOSIT": 3.5, "USD_CASH": 3.9,
                 "KR_SHORT_BOND": 3.6, "KR_LONG_BOND": 3.5, "US_LONG_BOND_KRW": 5.3}
DEFAULT_DURATION = {"KTB3": 2.8, "KTB30": 28.0, "UST30": 16.3,
                    "LONG_KTB_DIRECT": 12.0, "SHORT_KTB_DIRECT": 0.8}
L1_KEYS = ("kr_rate", "us_rate", "usdkrw", "kospi", "semi", "sp500", "gold", "wti", "premium")


def compound(*returns: float) -> float:
    """독립 요인의 소수 수익률을 곱셈 결합한다."""
    return math.prod(1 + float(value) for value in returns) - 1


def asset_shocks(l1: Mapping, config: Mapping | None = None) -> dict[str, float]:
    config = config or {}
    carry = {**DEFAULT_CARRY, **config.get("carry", {})}
    duration = {**DEFAULT_DURATION, **config.get("duration", {})}
    h = float(config.get("horizon", 0.5))
    inputs = {key: float(l1.get(key, l1.get({"usdkrw": "fx", "sp500": "spx"}.get(key, key), 0))) / 100 for key in L1_KEYS}
    if not all(math.isfinite(value) for value in inputs.values()) or not math.isfinite(h) or h <= 0:
        raise ValueError("시나리오 입력과 기간은 유효한 숫자이어야 합니다.")
    annual = {key: float(value) / 100 for key, value in carry.items()}
    kr, us, fx = inputs["kr_rate"], inputs["us_rate"], inputs["usdkrw"]
    gold = compound(inputs["gold"], fx)
    equity = compound(inputs["sp500"], fx)
    return {
        "KR_CASH": annual["KR_CASH"] * h,
        "DEPOSIT": annual["DEPOSIT"] * h,
        "KR_SHORT_BOND": annual["KR_SHORT_BOND"] * h - float(duration["KTB3"]) * kr,
        "KR_LONG_BOND": annual["KR_LONG_BOND"] * h - float(duration["KTB30"]) * kr,
        "SHORT_KTB_DIRECT": annual["KR_SHORT_BOND"] * h - float(duration["SHORT_KTB_DIRECT"]) * kr,
        "LONG_KTB_DIRECT": annual["KR_LONG_BOND"] * h - float(duration["LONG_KTB_DIRECT"]) * kr,
        "US_LONG_BOND_KRW": compound(annual["US_LONG_BOND_KRW"] * h - float(duration["UST30"]) * us, fx),
        "USD_CASH": compound(annual["USD_CASH"] * h, fx),
        "GOLD_KRW": gold,
        "KRX_GOLD_SPOT": compound(gold, inputs["premium"]),
        "US_EQ_KRW": equity,
        "US_EQ_USD": equity,
        "KR_EQ": inputs["kospi"],
        "KR_EQ_DEF": inputs["kospi"] * 0.6,
        "KR_EQ_SEMI": inputs["semi"],
        "OIL": inputs["wti"],
    }


def simulate_portfolio(plan: Mapping, amounts: Mapping, universe: Mapping | list, l1: Mapping,
                       config: Mapping | None = None, k: int = 0, mode: str = "자동(신호 기반)") -> dict:
    targets = target_rows(plan, amounts, k, mode, universe)
    shocks = asset_shocks(l1, config)
    targets["shock"] = targets["asset_class"].map(shocks)
    if targets["shock"].isna().any():
        raise ValueError("시나리오 자산군이 정의되지 않은 항목이 있습니다.")
    targets["pnl"] = targets["amount"] * targets["shock"]
    accounts = targets.groupby(["account", "label"], sort=False, as_index=False).agg(amount=("amount", "sum"), pnl=("pnl", "sum"))
    accounts["return_pct"] = accounts.apply(lambda row: row.pnl / row.amount * 100 if row.amount else 0.0, axis=1)
    total = float(accounts["amount"].sum())
    pnl = float(accounts["pnl"].sum())
    return {"accounts": accounts, "contributions": targets, "total_amount": total,
            "pnl": pnl, "return_pct": pnl / total * 100 if total else 0.0}


def historical_2022(macro: pd.DataFrame, prices: pd.DataFrame) -> dict:
    """2022-01-03~06-30의 실데이터만 사용. 하나라도 부족하면 재현을 비활성화한다."""
    start, end = pd.Timestamp("2022-01-03"), pd.Timestamp("2022-06-30")
    missing, inputs, used_dates = [], {}, {}

    def endpoints(frame, item):
        required = {"date", "id", "close", "source"}
        if frame.empty or not required.issubset(frame.columns):
            missing.append(item)
            return None
        mask = (frame["id"] == item) & ~frame["source"].fillna("").astype(str).str.contains("DEMO|데모", case=False, regex=True)
        values = frame.loc[mask, ["date", "close"]].copy()
        values["date"] = pd.to_datetime(values["date"], errors="coerce", utc=True).dt.tz_localize(None)
        values["close"] = pd.to_numeric(values["close"], errors="coerce")
        values = values.dropna().sort_values("date").drop_duplicates("date", keep="last")
        first = values.loc[(values["date"] >= start) & (values["date"] <= start + pd.Timedelta(days=7))]
        last = values.loc[(values["date"] <= end) & (values["date"] >= end - pd.Timedelta(days=7))]
        if first.empty or last.empty or first.iloc[0]["close"] <= 0:
            missing.append(item)
            return None
        used_dates[item] = [first.iloc[0]["date"].date().isoformat(), last.iloc[-1]["date"].date().isoformat()]
        return float(first.iloc[0]["close"]), float(last.iloc[-1]["close"])

    for key, item in {"kr_rate": "KR3Y", "us_rate": "US10Y", "usdkrw": "USDKRW", "kospi": "KOSPI",
                      "sp500": "SP500", "gold": "GOLD_USD", "wti": "WTI"}.items():
        pair = endpoints(macro, item)
        if pair:
            inputs[key] = pair[1] - pair[0] if key in {"kr_rate", "us_rate"} else (pair[1] / pair[0] - 1) * 100
    semis = [endpoints(prices, item) for item in ("SEC", "HYNIX")]
    if all(pair is not None for pair in semis):
        inputs["semi"] = sum((pair[1] / pair[0] - 1) * 100 for pair in semis) / 2
    inputs["premium"] = 0.0
    return {"inputs": None if missing else inputs, "missing": missing, "dates": used_dates,
            "note": "2022년 관측일의 가격 수익률이며 배당·분배금·세금은 제외합니다. 김프 변화는 0%p로 가정합니다."}
