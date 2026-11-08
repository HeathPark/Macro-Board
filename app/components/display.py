"""시세 표시와 로컬 데이터 읽기. 개인 데이터는 캐시하지 않는다."""
from __future__ import annotations

import html
import json
import math
from numbers import Real
from pathlib import Path

import pandas as pd
import streamlit as st

RED = "#ff6978"
BLUE = "#69a9ff"
MUTED = "#8b9bb5"
ASSET_LABELS = {
    "KR_CASH": "원화 현금", "DEPOSIT": "예금·발행어음",
    "KR_SHORT_BOND": "국내 단기채", "KR_LONG_BOND": "국내 장기채",
    "SHORT_KTB_DIRECT": "직접 단기 국고채", "LONG_KTB_DIRECT": "직접 장기 국고채",
    "USD_CASH": "달러 현금·단기채", "US_LONG_BOND_KRW": "미국 장기채",
    "GOLD_KRW": "금 ETF", "KRX_GOLD_SPOT": "KRX 금현물",
    "US_EQ_KRW": "미국 주식·국내상장", "US_EQ_USD": "미국 주식·직접",
    "KR_EQ": "국내 주식", "KR_EQ_DEF": "국내 배당주",
    "KR_EQ_SEMI": "국내 반도체", "OIL": "원유",
}
MACRO_LABELS = {
    "KOSPI": "코스피", "KOSDAQ": "코스닥", "SP500": "S&P500", "NASDAQ": "나스닥",
    "SOX": "필라델피아 반도체", "USDKRW": "원/달러", "DXY": "달러 인덱스",
    "GOLD_USD": "국제 금", "WTI": "WTI 원유", "COPPER": "구리", "US10Y": "미국 국채 10년",
    "VIX": "변동성 지수", "KR_BASE_RATE": "한국은행 기준금리", "KR3Y": "국고채 3년",
    "KR10Y": "국고채 10년", "DFEDTARU": "연준 목표금리 상단", "CPILFESL": "미국 근원 소비자물가",
    "BAMLH0A0HYM2": "하이일드 스프레드", "GOLD_KRW_G": "국제 금 환산가 (원/g)",
    "KRX_PREMIUM": "KRX 김프",
}


def korean_name(item: dict) -> str:
    return {"BRKB": "버크셔 해서웨이 B", "MSFT": "마이크로소프트",
            "VOO": "뱅가드 S&P500"}.get(item.get("id"), item.get("name", item.get("id", "")))


def number(value, digits: int = 1, suffix: str = "") -> str:
    try:
        return f"{float(value):,.{digits}f}{suffix}" if pd.notna(value) else "데이터 없음"
    except (TypeError, ValueError):
        return "데이터 없음"


def percent(value) -> str:
    try:
        return f"{float(value):+,.2f}%" if pd.notna(value) else "데이터 없음"
    except (TypeError, ValueError):
        return "데이터 없음"


def signed_style(value) -> str:
    if isinstance(value, (int, float)) and pd.notna(value):
        return f"color: {RED if value > 0 else BLUE if value < 0 else MUTED}"
    return ""


def read_json(path: Path, fallback=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {} if fallback is None else fallback


def dataset_directory(root: Path) -> tuple[Path, bool]:
    active = read_json(root / "data/meta/active_dataset.json")
    if not isinstance(active, dict):
        active = {}
    demo = active.get("mode") == "demo"
    return root / ("data/demo" if demo else "data"), demo


def data_fingerprint(directory: Path) -> tuple:
    paths = [directory / "prices_daily.csv", directory / "macro_daily.csv",
             directory / "meta/last_update.json", directory / "meta/fetch_log.json"]
    return tuple((str(p), p.stat().st_mtime_ns if p.exists() else 0) for p in paths)


@st.cache_data(show_spinner=False, ttl=300)
def load_market_data(directory: str, fingerprint: tuple):
    """시장 공개 데이터만 캐시하며 손상 파일도 빈 표로 복구한다."""
    del fingerprint
    directory = Path(directory)
    frames, errors = [], []
    for name in ("prices_daily.csv", "macro_daily.csv"):
        empty = pd.DataFrame(columns=["date", "id", "close", "source"])
        try:
            df = pd.read_csv(directory / name, dtype={"id": str})
            if not set(empty.columns).issubset(df.columns):
                raise ValueError("schema")
            df["date"] = pd.to_datetime(df["date"], errors="coerce", utc=True).dt.tz_localize(None)
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df = df.dropna(subset=["date", "id", "close"]).sort_values("date")
            df = df.loc[df["close"].map(math.isfinite)]
            frames.append(df.drop_duplicates(["date", "id"], keep="last"))
        except (OSError, ValueError, pd.errors.ParserError):
            frames.append(empty)
            errors.append(name)
    metadata = read_json(directory / "meta/last_update.json")
    log = read_json(directory / "meta/fetch_log.json", [])
    if not isinstance(metadata, dict):
        metadata = {}
    if isinstance(log, dict):
        log = log.get("items", [])
    log = [item for item in log if isinstance(item, dict)] if isinstance(log, list) else []
    return (*frames, metadata, log, errors)


def series_for(df: pd.DataFrame, item_id: str) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=float)
    selected = df.loc[df["id"] == item_id, ["date", "close"]].dropna()
    return selected.drop_duplicates("date", keep="last").set_index("date")["close"].sort_index()


def change_at(series: pd.Series, target: pd.Timestamp) -> float | None:
    baseline = series.loc[series.index <= target]
    if series.empty or baseline.empty or baseline.iloc[-1] == 0:
        return None
    return (series.iloc[-1] / baseline.iloc[-1] - 1) * 100


def price_summary(series: pd.Series) -> dict:
    if series.empty:
        return {"price": None, "1D": None, "1W": None, "1M": None, "3M": None,
                "YTD": None, "drawdown": None, "sparkline": [], "date": None}
    current = series.index[-1]
    last_year = series.loc[series.index >= current - pd.Timedelta(days=365)]
    return {
        "price": float(series.iloc[-1]),
        "1D": (series.iloc[-1] / series.iloc[-2] - 1) * 100 if len(series) > 1 and series.iloc[-2] else None,
        "1W": change_at(series, current - pd.Timedelta(days=7)),
        "1M": change_at(series, current - pd.DateOffset(months=1)),
        "3M": change_at(series, current - pd.DateOffset(months=3)),
        "YTD": change_at(series, pd.Timestamp(current.year, 1, 1) - pd.Timedelta(days=1)),
        "drawdown": (series.iloc[-1] / last_year.max() - 1) * 100 if last_year.max() else None,
        "sparkline": series.tail(20).astype(float).tolist(),
        "date": current.strftime("%Y-%m-%d"),
    }


def metric_card(label: str, summary: dict, unit: str = "", digits: int = 2,
                note: str = "", is_percent: bool = False):
    value = number(summary.get("price"), digits, unit)
    cells = []
    for key, title in (("1D", "1일"), ("1M", "1개월")):
        v = summary.get(key)
        color = RED if v is not None and v > 0 else BLUE if v is not None and v < 0 else MUTED
        cells.append(f'<span>{title} <b style="color:{color}">{percent(v)}</b></span>')
    date_note = summary.get("date") or "업데이트 대기"
    st.markdown(
        f'<div class="market-card"><div class="card-label">{html.escape(label)}</div>'
        f'<div class="card-value">{html.escape(value)}</div>'
        f'<div class="card-changes">{"".join(cells)}</div>'
        f'<div class="card-note">{html.escape(note or date_note)}</div></div>', unsafe_allow_html=True)


def chart_layout(fig, height=340):
    fig.update_layout(height=height, margin=dict(l=0, r=0, t=20, b=0),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(color="#c6d3e8", family="sans-serif"),
                      legend=dict(orientation="h", y=-0.12),
                      hoverlabel=dict(bgcolor="#18253b"))
    fig.update_xaxes(gridcolor="#223149", zerolinecolor="#33445e")
    fig.update_yaxes(gridcolor="#223149", zerolinecolor="#33445e")
    return fig


def line_figure(series: pd.Series, label: str):
    import plotly.graph_objects as go

    fig = go.Figure(go.Scatter(x=series.index, y=series.values, mode="lines", name=label,
                              line=dict(color="#56d4bb", width=2), fill="tozeroy",
                              fillcolor="rgba(86,212,187,.06)"))
    return chart_layout(fig, 240)


def finance_table(df: pd.DataFrame, *, percent_columns=(), amount_columns=(),
                  signed_columns=(), sparkline_columns=()):
    """색상과 스파크라인을 가벼운 HTML로 표시한다. 모든 텍스트는 이스케이프한다."""
    headers = "".join(f"<th>{html.escape(str(column))}</th>" for column in df.columns)
    body = []
    for _, row in df.iterrows():
        cells = []
        for column, value in row.items():
            color = ""
            numeric = isinstance(value, Real) and math.isfinite(float(value))
            if column in sparkline_columns:
                points = [float(x) for x in value if isinstance(x, Real) and math.isfinite(float(x))] if isinstance(value, list) else []
                if len(points) > 1:
                    lo, hi = min(points), max(points)
                    span = hi - lo or 1
                    coordinates = " ".join(f"{2 + index * 86 / (len(points)-1):.2f},{23 - (p-lo)*20/span:.2f}" for index, p in enumerate(points))
                    stroke = RED if points[-1] >= points[0] else BLUE
                    cell = (f'<svg width="90" height="26" viewBox="0 0 90 26" role="img" aria-label="최근 20일 가격 추이">'
                            f'<polyline points="{coordinates}" fill="none" stroke="{stroke}" stroke-width="1.7"/></svg>')
                else:
                    cell = "데이터 없음"
            else:
                if column in percent_columns:
                    text = percent(value)
                elif column in amount_columns:
                    text = number(value, 0)
                elif numeric:
                    text = number(value, 2)
                elif value is None or not isinstance(value, (str, list, dict)) and pd.isna(value):
                    text = "데이터 없음"
                else:
                    text = str(value)
                if numeric and column in set(percent_columns) | set(signed_columns):
                    color = f' style="color:{RED if value > 0 else BLUE if value < 0 else MUTED}"'
                cell = html.escape(text)
            cells.append(f"<td{color}>{cell}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    st.markdown(f'<div class="finance-table-wrap"><table class="finance-table"><thead><tr>{headers}</tr></thead>'
                f'<tbody>{"".join(body)}</tbody></table></div>', unsafe_allow_html=True)


def result_card(label: str, value: float, suffix: str, digits=0):
    color = RED if value > 0 else BLUE if value < 0 else "#e1eaf7"
    st.markdown(f'<div class="market-card"><div class="card-label">{html.escape(label)}</div>'
                f'<div class="card-value" style="color:{color}">{html.escape(number(value,digits,suffix))}</div>'
                '</div>', unsafe_allow_html=True)
