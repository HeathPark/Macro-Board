"""공개 시세 수집. 공급자 오류에 비밀값/전체 URL을 포함하지 않는다."""
from __future__ import annotations

from contextlib import contextmanager
import logging
from typing import Callable

import pandas as pd

COLUMNS = ["date", "id", "close", "source"]


class ProviderError(RuntimeError):
    """화면/수집 로그에 저장할 수 있는 제한된 오류 코드."""


def empty_prices() -> pd.DataFrame:
    return pd.DataFrame(columns=COLUMNS)


def normalize_history(raw: pd.DataFrame, item_id: str, source: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        raise ProviderError("empty_response")
    frame = raw.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    close_column = next((name for name in ["Close", "close", "종가", "현재가"] if name in frame), None)
    if close_column is None:
        raise ProviderError("invalid_price_schema")
    date_column = next((name for name in ["date", "Date", "날짜", "일자"] if name in frame), None)
    dates = frame[date_column] if date_column else frame.index
    parsed = pd.to_datetime(dates, errors="coerce")
    # Strip timezone without converting a local market date to another day.
    if getattr(parsed, "tz", None) is not None:
        parsed = parsed.tz_localize(None)
    elif isinstance(parsed, pd.Series) and isinstance(parsed.dtype, pd.DatetimeTZDtype):
        parsed = parsed.dt.tz_localize(None)
    result = pd.DataFrame({
        "date": pd.DatetimeIndex(parsed).strftime("%Y-%m-%d"),
        "id": item_id,
        "close": pd.to_numeric(frame[close_column].astype(str).str.replace(",", "", regex=False), errors="coerce").to_numpy(),
        "source": source,
    })
    result = result.dropna(subset=["date", "close"])
    result = result[result["close"] > 0].drop_duplicates(["date", "id"], keep="last")
    if result.empty:
        raise ProviderError("empty_valid_prices")
    return result.sort_values("date").reset_index(drop=True)[COLUMNS]


@contextmanager
def bounded_http(timeout: int = 12):
    """FDR/pykrx의 requests 호출에도 연결/응답 제한을 적용한다.

    수집은 단일 스레드에서 진행한다. 함수 종료 시 원래 requests 동작을 복구한다.
    """
    import requests
    original = requests.sessions.Session.request

    def request(session, method, url, **kwargs):
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = timeout
        return original(session, method, url, **kwargs)

    requests.sessions.Session.request = request
    try:
        yield
    finally:
        requests.sessions.Session.request = original


def fetch_yahoo(symbol: str, start: str, end: str | None = None, item_id: str | None = None) -> pd.DataFrame:
    import yfinance as yf
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    # Yahoo end is exclusive; the public function accepts an inclusive end.
    exclusive = (pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d") if end else None
    try:
        raw = yf.Ticker(symbol).history(start=start, end=exclusive, auto_adjust=False, timeout=12, raise_errors=True)
        return normalize_history(raw, item_id or symbol, "yfinance")
    except ProviderError:
        raise
    except Exception:
        raise ProviderError("yahoo_unavailable") from None


def _fetch_fdr(code: str, start: str, end: str | None, item_id: str) -> pd.DataFrame:
    import FinanceDataReader as fdr
    with bounded_http():
        raw = fdr.DataReader(code, start, end)
    return normalize_history(raw, item_id, "FinanceDataReader")


def _fetch_pykrx(code: str, start: str, end: str | None, item_id: str) -> pd.DataFrame:
    from pykrx import stock
    end = end or pd.Timestamp.today().strftime("%Y-%m-%d")
    with bounded_http():
        # ETF first (also supports newer alphanumeric ticker strings); stocks second.
        try:
            raw = stock.get_etf_ohlcv_by_date(start.replace("-", ""), end.replace("-", ""), code)
        except Exception:
            raw = None
        if raw is None or raw.empty:
            raw = stock.get_market_ohlcv_by_date(start.replace("-", ""), end.replace("-", ""), code)
    return normalize_history(raw, item_id, "pykrx")


def fetch_price(item: dict, start: str, end: str | None = None) -> pd.DataFrame:
    """KRX: FDR → pykrx → Yahoo, US: Yahoo. 영숫자 코드를 정수로 바꾸지 않는다."""
    code, item_id = str(item["code"]), str(item["id"])
    providers: list[Callable[[], pd.DataFrame]]
    if item.get("market") == "KRX":
        providers = [
            lambda: _fetch_fdr(code, start, end, item_id),
            lambda: _fetch_pykrx(code, start, end, item_id),
            lambda: fetch_yahoo(f"{code}.KS", start, end, item_id),
        ]
    else:
        providers = [lambda: fetch_yahoo(code, start, end, item_id)]
    for provider in providers:
        try:
            return provider()
        except Exception:
            # Exceptions may contain cookie headers, private URLs or API keys.
            # Only the fixed failure code below escapes this boundary.
            continue
    raise ProviderError("all_price_sources_unavailable")
