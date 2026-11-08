"""L1 가정(%, %p) → L2 수익률(소수) → 계좌별 손익(만원)."""
from __future__ import annotations

import math
from collections.abc import Mapping

import pandas as pd

from src.config import load_config
from src.portfolio import target_rows, universe_map

L1_KEYS = ("kr_rate", "us_rate", "usdkrw", "kospi", "semi", "sp500", "gold", "wti", "premium")


def compound(*returns: float) -> float:
    """독립 요인의 소수 수익률을 곱셈 결합한다."""
    return math.prod(1 + float(value) for value in returns) - 1


def _number(value, message: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(message) from None
    if isinstance(value, bool) or not math.isfinite(result):
        raise ValueError(message)
    return result


def _scenario_config(config: Mapping | None) -> dict:
    """모델의 수치 기본값은 YAML에서 읽고 명시한 부분 설정만 덮어쓴다."""
    resolved = load_config("scenarios")
    if config is not None and not isinstance(config, Mapping):
        raise ValueError("시나리오 설정은 키·값 형식이어야 합니다.")
    for key, value in (config or {}).items():
        if key in {"carry", "duration", "equity_beta"}:
            if not isinstance(value, Mapping) or not isinstance(resolved.get(key), Mapping):
                raise ValueError("시나리오 금리·듀레이션·민감도 설정 형식을 확인해 주세요.")
            resolved[key] = {**resolved[key], **value}
        else:
            resolved[key] = value
    return resolved


def _inputs(l1: Mapping) -> dict[str, float]:
    return {key: _number(l1.get(key, l1.get({"usdkrw": "fx", "sp500": "spx"}.get(key, key), 0)),
                         "시나리오 입력은 유효한 숫자이어야 합니다.") / 100 for key in L1_KEYS}


def asset_shocks(l1: Mapping, config: Mapping | None = None) -> dict[str, float]:
    """자산군의 기본 충격. 개별 상품의 금리는 instrument_shocks에서 적용한다."""
    config = _scenario_config(config)
    carry = config["carry"]
    duration = {key: _number(value, "듀레이션은 유효한 숫자이어야 합니다.")
                for key, value in config["duration"].items()}
    h = _number(config["horizon"], "시나리오 기간은 유효한 양수이어야 합니다.")
    inputs = _inputs(l1)
    if h <= 0 or any(value < 0 for value in duration.values()):
        raise ValueError("시나리오 입력과 기간은 유효한 숫자이어야 합니다.")
    annual = {key: _number(value, "캐리 금리는 유효한 숫자이어야 합니다.") / 100
              for key, value in carry.items()}
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
        "KR_EQ_DEF": inputs["kospi"] * _number(config["equity_beta"]["KR_EQ_DEF"], "주식 민감도는 유효한 숫자이어야 합니다."),
        "KR_EQ_SEMI": inputs["semi"],
        "OIL": inputs["wti"],
    }


def instrument_shocks(l1: Mapping, universe: Mapping | list,
                      config: Mapping | None = None) -> dict[str, float]:
    """상품별 수익률. 같은 자산군이라도 universe의 rate(연율 %)를 우선한다."""
    config = _scenario_config(config)
    shocks = asset_shocks(l1, config)
    h = _number(config["horizon"], "시나리오 기간은 유효한 양수이어야 합니다.")
    fx = _inputs(l1)["usdkrw"]
    carry_classes = {"KR_CASH": "KR_CASH", "DEPOSIT": "DEPOSIT", "USD_CASH": "USD_CASH",
                     "KR_SHORT_BOND": "KR_SHORT_BOND", "KR_LONG_BOND": "KR_LONG_BOND",
                     "SHORT_KTB_DIRECT": "KR_SHORT_BOND", "LONG_KTB_DIRECT": "KR_LONG_BOND",
                     "US_LONG_BOND_KRW": "US_LONG_BOND_KRW"}
    result = {}
    for item_id, item in universe_map(universe).items():
        asset_class = item.get("asset_class")
        if asset_class not in shocks:
            raise ValueError("시나리오 자산군이 정의되지 않은 항목이 있습니다.")
        shock = shocks[asset_class]
        if "rate" in item:
            annual = _number(item["rate"], "상품별 금리는 유효한 숫자이어야 합니다.") / 100
            if asset_class not in carry_classes:
                raise ValueError("상품별 금리는 캐리 자산군에만 설정할 수 있습니다.")
            default = _number(config["carry"][carry_classes[asset_class]],
                              "캐리 금리는 유효한 숫자이어야 합니다.") / 100
            # 외화 수익률은 캐리와 환율을 곱셈 결합하므로 캐리 차이에도 환율을 적용한다.
            multiplier = 1 + fx if asset_class in {"USD_CASH", "US_LONG_BOND_KRW"} else 1
            shock += (annual - default) * h * multiplier
        result[item_id] = shock
    return result


def simulate_portfolio(plan: Mapping, amounts: Mapping, universe: Mapping | list, l1: Mapping,
                       config: Mapping | None = None, k: int = 0, mode: str = "자동(신호 기반)") -> dict:
    targets = target_rows(plan, amounts, k, mode, universe)
    shocks = instrument_shocks(l1, universe, config)
    targets["shock"] = targets["id"].map(shocks)
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
