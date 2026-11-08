"""KRX 금 현물과 국제 금 환산가. ETF 가격은 원/g으로 간주하지 않는다.

KRX 공개 화면이 표를 제공하지 않거나 접근 제한이 있으면 호출자가 ETF의
가격 추이를 대체값으로 보여 준다. 인증이 필요한 KRX API를 우회하지 않는다.
"""
from __future__ import annotations

from io import StringIO
import re

import pandas as pd
import requests

GOLD_PAGE = (
    "https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd"
    "?menuId=MDC0203050101"
)
COLUMNS = ["date", "id", "close", "source"]


def fetch_gold(start: str, end: str | None = None) -> pd.DataFrame:
    """공개 KRX 표에서 *금 99.99_1kg*의 일별 원/g 종가만 수용한다.

    해당 공개 화면이 동적 데이터/인증만 제공하면 추정하거나 ETF를 끼워
    넣지 않고 실패를 반환한다. 실패 메시지에는 요청 URL/인증값이 없다.
    현재 공개 표 스키마의 실환경 검증 여부는 docs/ASSUMPTIONS.md 참고.
    """
    try:
        response = requests.get(GOLD_PAGE, timeout=(5, 12))
        response.raise_for_status()
        tables = pd.read_html(StringIO(response.text))
    except Exception:
        raise ValueError("KRX 금시장 공개 데이터에 접근할 수 없습니다") from None
    found = []
    for table in tables:
        table.columns = [" ".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in table.columns]
        names = {re.sub(r"\s", "", str(c)): c for c in table.columns}
        date_col = next((names[c] for c in ("일자", "기준일자", "거래일자") if c in names), None)
        close_col = next((names[c] for c in ("종가", "종가(원/g)", "종가(원/그램)") if c in names), None)
        product_col = next((names[c] for c in ("종목명", "상품명") if c in names), None)
        # A page title alone does not identify which product a table contains.
        if not (date_col and close_col and product_col):
            continue
        # The 1kg contract name alone does not establish the quoted price unit.
        unit_text = re.sub(r"\s", "", response.text).lower()
        if not any(unit in unit_text for unit in ("원/g", "원/그램")):
            continue
        normalized = table[product_col].astype(str).str.replace(r"[\s_,]", "", regex=True).str.lower()
        rows = table[normalized.isin(["금99.991kg", "금99.99(1kg)"])]
        if rows.empty:
            continue
        frame = pd.DataFrame({
            "date": pd.to_datetime(rows[date_col].astype(str), errors="coerce"),
            "close": pd.to_numeric(rows[close_col].astype(str).str.replace(",", ""), errors="coerce"),
        }).dropna()
        frame = frame[(frame["date"] >= pd.Timestamp(start)) & (frame["close"] > 0)]
        if end:
            frame = frame[frame["date"] <= pd.Timestamp(end)]
        frame["date"] = frame["date"].dt.strftime("%Y-%m-%d")
        frame["id"] = "KRX_GOLD_SPOT"
        frame["source"] = "KRX 금시장 공개표(원/g)"
        found.append(frame[COLUMNS])
    if not found:
        raise ValueError("KRX 금 99.99_1kg의 검증 가능한 일별 원/g 표가 없습니다")
    return pd.concat(found, ignore_index=True).drop_duplicates(["date", "id"]).sort_values("date")


def _series(frame: pd.DataFrame, ids: tuple[str, ...]) -> pd.Series:
    if frame.empty or not {"date", "id", "close"}.issubset(frame.columns):
        return pd.Series(dtype=float)
    for item_id in ids:
        subset = frame.loc[frame["id"].eq(item_id), ["date", "close"]].copy()
        if subset.empty:
            continue
        subset["date"] = pd.to_datetime(subset["date"], errors="coerce").dt.normalize()
        subset["close"] = pd.to_numeric(subset["close"], errors="coerce")
        subset = subset.dropna().drop_duplicates("date", keep="last").sort_values("date")
        return subset.set_index("date")["close"]
    return pd.Series(dtype=float)


def calculate_gold(
    macro_df: pd.DataFrame,
    prices_df: pd.DataFrame,
    correction_pct: float = 0.0,
) -> pd.DataFrame:
    """동일 거래일의 금·환율·KRX 원/g으로 김프를 계산한다.

    correction_pct는 국제 선물가격에 곱하는 보정률(%, 기본 0)이다.
    예: 선물보다 0.5% 낮게 가정하려면 -0.5. 가격 날짜가 다른 경우
    미래값/임의 보간으로 김프를 만들지 않는다. ETF는 proxy_price에만
    남겨 가격 추이용 '대체값' 표시를 허용한다.
    """
    if not (-100 < float(correction_pct) < 100):
        raise ValueError("국제 금 보정률은 -100% 초과, 100% 미만이어야 합니다")
    gold = _series(macro_df, ("GC=F", "GOLD", "GOLD_USD"))
    fx = _series(macro_df, ("KRW=X", "USDKRW", "USD_KRW"))
    spot = _series(prices_df, ("KRX_GOLD_SPOT",))
    if spot.empty:
        spot = _series(macro_df, ("KRX_GOLD_SPOT",))
    proxy_price = _series(prices_df, ("GOLD_KRX",))
    frame = pd.concat({"gold_usd": gold, "fx": fx, "krx_krw_g": spot, "proxy_price": proxy_price}, axis=1)
    if frame.empty:
        return pd.DataFrame(columns=["date", "international_krw_g", "krx_krw_g", "premium_pct", "proxy", "proxy_price"])
    frame["international_krw_g"] = frame["gold_usd"] * frame["fx"] / 31.1035 * (1 + float(correction_pct) / 100)
    valid = (frame["krx_krw_g"] > 0) & (frame["international_krw_g"] > 0)
    frame["premium_pct"] = ((frame["krx_krw_g"] / frame["international_krw_g"] - 1) * 100).where(valid)
    frame["proxy"] = frame["krx_krw_g"].isna() & frame["proxy_price"].notna()
    frame.index.name = "date"
    frame = frame.reset_index()
    frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
    return frame[["date", "international_krw_g", "krx_krw_g", "premium_pct", "proxy", "proxy_price"]]
