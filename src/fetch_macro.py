"""시장·ECOS·FRED 지표. API 키가 없으면 해당 지표만 건너뛴다."""
from __future__ import annotations

import os
from urllib.parse import quote

import pandas as pd

from src.fetch_prices import COLUMNS, ProviderError, fetch_yahoo

YAHOO_SERIES = {
    "KOSPI": "^KS11", "KOSDAQ": "^KQ11", "SP500": "^GSPC",
    "NASDAQ": "^IXIC", "SOX": "^SOX", "USDKRW": "KRW=X",
    "DXY": "DX-Y.NYB", "GOLD_USD": "GC=F", "WTI": "CL=F",
    "COPPER": "HG=F", "US10Y": "^TNX", "VIX": "^VIX",
}
FRED_SERIES = {key: key for key in ["DFEDTARU", "CPILFESL", "BAMLH0A0HYM2"]}
# Candidate identifiers are checked through StatisticItemList before use.
# They are not treated as live-verified until a successful keyed response.
ECOS_SERIES = {
    "KR_BASE_RATE": {"stat": "722Y001", "item": "0101000", "name": "한국은행 기준금리", "cycle": "D"},
    "KR3Y": {"stat": "817Y002", "item": "010200000", "name": "국고채(3년)", "cycle": "D"},
    "KR10Y": {"stat": "817Y002", "item": "010210000", "name": "국고채(10년)", "cycle": "D"},
}


class MissingAPIKey(ProviderError):
    pass


def _safe_json(url: str, *, params: dict | None = None) -> dict:
    import requests
    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        return response.json()
    except Exception:
        raise ProviderError("macro_endpoint_unavailable") from None


def _rows_frame(rows: list[dict], item_id: str, source: str, date_key: str, value_key: str) -> pd.DataFrame:
    if not rows:
        raise ProviderError("empty_macro_response")
    raw = pd.DataFrame(rows)
    if date_key not in raw or value_key not in raw:
        raise ProviderError("invalid_macro_schema")
    result = pd.DataFrame({
        "date": pd.to_datetime(raw[date_key], errors="coerce").dt.strftime("%Y-%m-%d"),
        "id": item_id,
        "close": pd.to_numeric(raw[value_key].astype(str).str.replace(",", "", regex=False), errors="coerce"),
        "source": source,
    }).dropna(subset=["date", "close"])
    if result.empty:
        raise ProviderError("empty_valid_macro")
    return result[COLUMNS].drop_duplicates(["date", "id"]).sort_values("date").reset_index(drop=True)


def fetch_fred(series: str, start: str, end: str | None = None) -> pd.DataFrame:
    key = os.getenv("FRED_API_KEY")
    if not key:
        raise MissingAPIKey("missing_FRED_API_KEY")
    params = {"series_id": series, "api_key": key, "file_type": "json", "observation_start": start}
    if end:
        params["observation_end"] = end
    payload = _safe_json("https://api.stlouisfed.org/fred/series/observations", params=params)
    return _rows_frame(payload.get("observations", []), series, "FRED", "date", "value")


def _ecos_rows(service: str, key: str, suffix: str) -> list[dict]:
    # Never return or log this URL: the ECOS API key is part of its path.
    payload = _safe_json(f"https://ecos.bok.or.kr/api/{service}/{quote(key, safe='')}/json/kr/{suffix}")
    block = payload.get(service, {})
    if not isinstance(block, dict) or not isinstance(block.get("row"), list):
        raise ProviderError("ecos_invalid_or_denied_response")
    return block["row"]


def fetch_ecos(item_id: str, start: str, end: str | None = None) -> pd.DataFrame:
    key = os.getenv("ECOS_API_KEY")
    if not key:
        raise MissingAPIKey("missing_ECOS_API_KEY")
    spec = ECOS_SERIES[item_id]
    items = _ecos_rows("StatisticItemList", key, f"1/1000/{spec['stat']}")
    matches = [row for row in items if str(row.get("ITEM_CODE")) == spec["item"] and row.get("CYCLE") == spec["cycle"] and row.get("ITEM_NAME") == spec["name"]]
    if not matches:
        # Discover renamed item codes by exact documented label, not by a guessed number.
        matches = [row for row in items if row.get("ITEM_NAME") == spec["name"] and row.get("CYCLE") == spec["cycle"]]
    if len(matches) != 1:
        raise ProviderError("ecos_item_not_verified")
    item = str(matches[0]["ITEM_CODE"])
    start_compact = start.replace("-", "")
    end_compact = (end or pd.Timestamp.today().strftime("%Y-%m-%d")).replace("-", "")
    rows: list[dict] = []
    for first in range(1, 100_001, 1000):
        chunk = _ecos_rows("StatisticSearch", key, f"{first}/{first + 999}/{spec['stat']}/{spec['cycle']}/{start_compact}/{end_compact}/{item}")
        rows.extend(chunk)
        if len(chunk) < 1000:
            break
    result = _rows_frame(rows, item_id, "ECOS", "TIME", "DATA_VALUE")
    # Rates are percentage levels. Negative bond yields are valid, unlike prices.
    return result


def fetch_macro_series(item_id: str, start: str, end: str | None = None) -> pd.DataFrame:
    if item_id in YAHOO_SERIES:
        # Yahoo ^TNX uses percentage yield levels (e.g. 4.3), not basis points.
        # Keep values unchanged; live validation is recorded separately.
        return fetch_yahoo(YAHOO_SERIES[item_id], start, end, item_id)
    if item_id in FRED_SERIES:
        return fetch_fred(item_id, start, end)
    if item_id in ECOS_SERIES:
        return fetch_ecos(item_id, start, end)
    raise ProviderError("unknown_macro_id")


def macro_ids() -> list[str]:
    return [*YAHOO_SERIES, *ECOS_SERIES, *FRED_SERIES]
