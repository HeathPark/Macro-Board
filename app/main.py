"""개인용 매크로·자산배분 대시보드. 실행: streamlit run app/main.py"""
from __future__ import annotations

import html
import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import streamlit as st

from app.components.display import (
    ASSET_LABELS, MACRO_LABELS, BLUE, RED, chart_layout, data_fingerprint, dataset_directory,
    finance_table, korean_name, line_figure, load_market_data, metric_card, number, percent, result_card,
    series_for, signed_style,
)
from src.config import ROOT, load_config, save_private_plan
from src.maturities import read_maturities
from src.portfolio import blend_weights, price_statistics, risk_check, target_rows
from src.scenario import asset_shocks, historical_2022, instrument_shocks, simulate_portfolio
from src.signals import evaluate_signals, phase_from_signals

st.set_page_config(page_title="매크로 보드", page_icon="◈", layout="wide",
                   initial_sidebar_state="expanded")

st.markdown("""
<style>
:root { color-scheme: dark; }
.stApp { background: #0b1220; color: #e2eaf7; }
[data-testid="stHeader"] { background: rgba(11,18,32,.92); }
[data-testid="stSidebar"] { background: #101b2d; border-right: 1px solid #21304a; }
[data-testid="stSidebar"] * { color: #d8e3f5; }
.block-container { padding-top: 2.4rem; padding-bottom: 3rem; max-width: 1520px; }
h1,h2,h3 { letter-spacing: -.04em; }
.eyebrow { font-size: .73rem; font-weight: 700; color:#56d4bb; letter-spacing:.18em; }
.hero-title { font-size:2.8rem; font-weight:750; letter-spacing:-.06em; margin:.1rem 0 .3rem; }
.hero-subtitle { color:#8b9bb5; font-size:.94rem; margin-bottom:1.2rem; }
.update-note { text-align:right; color:#8b9bb5; font-size:.8rem; padding-top:1.2rem; }
.phase-box { border:1px solid #29443f; background:linear-gradient(115deg,#142c2a,#142138);
 border-radius:14px; padding:22px 26px; margin-bottom:18px; }
.phase-title { font-size:.8rem; color:#a0bbbd; margin-bottom:6px; }
.phase-value { font-size:1.8rem; font-weight:700; color:#77e3cc; letter-spacing:-.04em; }
.phase-note { color:#9fb0c8; font-size:.85rem; margin-top:8px; }
.signal-box { min-height:155px; border:1px solid #25334a; border-radius:12px; padding:18px;
 background:#121e30; margin-bottom:16px; }
.signal-label { color:#aab9cf; font-size:.82rem; margin-bottom:7px; }
.signal-state { font-size:1.1rem; font-weight:650; margin-bottom:9px; }
.signal-detail { font-size:.77rem; color:#98a9c0; line-height:1.65; }
.market-card { border:1px solid #25334a; background:#111d2e; border-radius:12px;
 padding:19px 19px 15px; margin-bottom:15px; min-height:160px; }
.card-label { font-size:.82rem; color:#a1b0c7; }
.card-value { font-size:1.75rem; font-weight:650; margin:10px 0 13px; letter-spacing:-.04em; }
.card-changes { display:flex; flex-wrap:wrap; gap:15px; font-size:.72rem; color:#8b9bb5; }
.card-changes b { font-weight:550; margin-left:3px; }
.card-note { margin-top:10px; color:#70849f; font-size:.68rem; }
.section-label { margin:22px 0 13px; font-size:1.05rem; font-weight:650; letter-spacing:-.02em; }
.todo-box { border-left:3px solid #56d4bb; background:#101f30; border-radius:0 10px 10px 0;
 padding:15px 20px; margin:0 0 22px; font-size:.9rem; color:#c1d0e4; line-height:1.9; }
.stTabs [data-baseweb="tab-list"] { gap:24px; border-bottom:1px solid #23314a; }
.stTabs [data-baseweb="tab"] { color:#91a4c1; padding:10px 3px 14px; }
.stTabs [aria-selected="true"] { color:#76e0cb !important; }
.stTabs [data-baseweb="tab-highlight"] { background:#56d4bb; }
[data-testid="stMetric"] { background:#111d2e; border:1px solid #25334a; border-radius:12px; padding:16px; }
[data-testid="stMetricValue"] { color:#e1eaf7; }
[data-testid="stDataFrame"] { border:1px solid #25334a; border-radius:9px; }
.stButton button, .stFormSubmitButton button { border-radius:8px; }
.stCaption { color:#8b9bb5; }
.finance-table-wrap { overflow-x:auto; border:1px solid #25334a; border-radius:10px; margin-bottom:16px; }
.finance-table { width:100%; border-collapse:collapse; font-size:.8rem; white-space:nowrap; }
.finance-table th { background:#162237; color:#91a5c2; font-weight:500; padding:12px 14px; text-align:right; }
.finance-table td { padding:11px 14px; text-align:right; border-top:1px solid #20304a; color:#d5dfef; }
.finance-table td:first-child, .finance-table th:first-child { text-align:left; }
.finance-table td svg { vertical-align:middle; }
</style>
""", unsafe_allow_html=True)


def section(label: str):
    st.markdown(f'<div class="section-label">{html.escape(label)}</div>', unsafe_allow_html=True)


def summary(frame: pd.DataFrame, identifier: str) -> dict:
    result = price_statistics(series_for(frame, identifier))
    result["price"] = result.get("close")
    return result


def timestamp_label(value) -> str:
    if not value:
        return "아직 수집하지 않았습니다"
    try:
        t = pd.Timestamp(value)
        if pd.isna(t):
            return "아직 수집하지 않았습니다"
        t = t.tz_localize("UTC") if t.tzinfo is None else t
        return t.tz_convert("Asia/Seoul").strftime("%Y.%m.%d %H:%M 한국시간")
    except (TypeError, ValueError):
        return "아직 수집하지 않았습니다"




try:
    universe_config = load_config("universe")
    signal_config = load_config("signals")
    scenario_config = load_config("scenarios")
    plan = load_config("plan", private_override=True)
except (OSError, ValueError, TypeError):
    st.error("설정 파일을 읽지 못했습니다. 설정 파일 형식과 접근 권한을 확인해 주세요.")
    st.stop()

universe = universe_config.get("universe", []) + universe_config.get("manual", [])
by_id = {item["id"]: item for item in universe}
accounts = plan.get("accounts", {})
directory, is_demo = dataset_directory(ROOT)
prices, macro, metadata, fetch_log, read_errors = load_market_data(str(directory), data_fingerprint(directory))
signals = evaluate_signals(macro, signal_config)
phase = phase_from_signals(signals)
k = phase["k"]

with st.sidebar:
    st.markdown("### ◈ 매크로 보드")
    st.caption("시장을 읽고, 계획을 점검하세요.")
    st.divider()
    st.markdown("#### 자산배분 기준")
    mode = st.selectbox("적용 국면", ["자동(신호 기반)", "P1 고정", "P2 고정"], key="allocation_mode")
    st.caption(f"신호 {k}/3개 충족 · {phase['phase']}")
    if phase.get("incomplete") and mode == "자동(신호 기반)":
        st.warning("일부 신호에 데이터가 없어 자동 비중이 보수적으로 계산됩니다.")
    st.divider()
    st.markdown("#### 계좌별 금액")
    st.caption("만원 단위 · 이 기기의 비공개 파일에만 저장")
    amounts = {}
    saved_amounts = plan.get("amounts", {})
    if not isinstance(saved_amounts, dict):
        saved_amounts = {}
    with st.form("account_amounts"):
        for account_id, account in accounts.items():
            try:
                initial = float(saved_amounts.get(account_id, 0))
                if not math.isfinite(initial) or initial < 0:
                    initial = 0.0
            except (TypeError, ValueError):
                initial = 0.0
            amounts[account_id] = st.number_input(
                f"{account.get('label', account_id)} (만원)", min_value=0.0,
                value=initial, step=100.0, format="%.0f", key=f"amount_{account_id}")
        save = st.form_submit_button("금액 저장·적용", width="stretch")
    if save:
        try:
            plan["amounts"] = amounts
            save_private_plan(plan)
            saved_amounts = amounts
            st.success("이 기기에 저장했습니다.")
        except (OSError, ValueError, TypeError):
            st.error("금액을 저장하지 못했습니다. 비공개 폴더의 접근 권한을 확인해 주세요.")
    st.divider()
    st.caption("상승은 빨강 · 하락은 파랑")
    st.caption("공개 시장 데이터만 사용하며 증권사 계좌에 연결하지 않습니다.")

hero, update_col = st.columns([3, 2])
with hero:
    st.markdown('<div class="eyebrow">나의 시장 관측실</div><div class="hero-title">매크로 보드</div>'
                '<div class="hero-subtitle">오늘의 시장에서, 다음 자산배분까지.</div>', unsafe_allow_html=True)
with update_col:
    st.markdown(f'<div class="update-note">마지막 업데이트<br>'
                f'{html.escape(timestamp_label(metadata.get("updated_at")))}</div>', unsafe_allow_html=True)

if is_demo:
    st.info("데모 모드 · 아래 시장 데이터는 화면과 계산을 확인하기 위한 가상 데이터입니다. 실제 시장 판단에 사용하지 마세요.")
elif prices.empty and macro.empty:
    st.info("아직 시장 데이터가 없습니다. README의 데이터 수집 또는 데모 실행 방법을 확인해 주세요.")
if read_errors:
    st.warning("일부 데이터 파일이 없거나 읽을 수 없습니다. 해당 항목은 ‘데이터 없음’으로 표시합니다.")

holdings_path = ROOT / "private/holdings.csv"
tab_names = ["오늘", "종목", "계획", "시뮬레이션"] + (["보유"] if holdings_path.is_file() else [])
tabs = st.tabs(tab_names)

with tabs[0]:
    phase_text = {"P1": "P1 · 방어적 배분", "P2": "P2 · 전환 완료"}.get(phase["phase"], phase["phase"])
    if phase.get("incomplete"):
        phase_text += " · 잠정"
    st.markdown(f'<div class="phase-box"><div class="phase-title">현재 시장 국면</div>'
                f'<div class="phase-value">{html.escape(phase_text)}</div>'
                f'<div class="phase-note">전환 신호 {k}/3개 충족 · 목표 비중은 사이드바에서 변경할 수 있습니다.</div></div>',
                unsafe_allow_html=True)
    for col, signal in zip(st.columns(3), signals):
        state = signal["status"]
        symbol = {"충족": "🟢", "강한 충족": "🟢", "근접": "🟡", "미충족": "🔴"}.get(state, "⚪")
        with col:
            st.markdown(f'<div class="signal-box"><div class="signal-label">'
                        f'{html.escape(signal["id"])} · {html.escape(signal["label"])}</div>'
                        f'<div class="signal-state">{symbol} {html.escape(state)}</div>'
                        f'<div class="signal-detail">{html.escape(str(signal["detail"]))}</div></div>',
                        unsafe_allow_html=True)
    todos = []
    maturity_state = read_maturities(
        ROOT / "private/maturities.csv",
        window_days=universe_config.get("alerts", {}).get("maturity_days"),
    )
    if maturity_state["present"] and maturity_state["invalid"]:
        st.warning("만기 알림: 데이터 없음. 만기 파일의 열 이름·금리·날짜 형식을 확인해 주세요.")
    if maturity_state["items"]:
        upcoming = []
        for item in maturity_state["items"]:
            when = "오늘 만기" if item["days_left"] == 0 else f"{item['days_left']}일 후 만기"
            upcoming.append(f"{item['item']} · 연 {item['rate']:.2f}% · {item['maturity_date']} ({when})")
        todos.append("만기 확인: " + " / ".join(upcoming))
    premium = series_for(macro, "KRX_PREMIUM")
    if not premium.empty and premium.iloc[-1] > 3:
        todos.append("김프가 3%를 넘었습니다. 이번 달 금 매수는 SOL 국제금과 비교해 보세요.")
    current_states = tuple(s["status"] for s in signals)
    previous_states = st.session_state.get("previous_signal_states")
    if previous_states is not None and previous_states != current_states:
        todos.append("전환 신호가 바뀌었습니다. 계획 탭에서 목표 비중을 다시 확인하세요.")
    st.session_state["previous_signal_states"] = current_states
    log_items = fetch_log.get("items", []) if isinstance(fetch_log, dict) else fetch_log
    failed = [item for item in log_items if item.get("status") in ("failed", "skipped")]
    if failed:
        todos.append(f"수집하지 못한 항목 {len(failed)}개가 있습니다. 아래 데이터 상태를 확인하세요.")
    if phase.get("incomplete"):
        todos.append("일부 신호는 데이터가 부족합니다. ‘데이터 없음’을 미충족으로 단정하지 마세요.")
    if not todos:
        todos.append("시장 신호와 계좌별 목표 비중을 확인하세요. 계획에 따라 차분히 점검할 시간입니다.")
    section("오늘 할 일")
    st.markdown('<div class="todo-box">' + "<br>".join(f"{i+1}. {html.escape(t)}" for i, t in enumerate(todos[:3])) + '</div>',
                unsafe_allow_html=True)
    section("주요 시장 지표")
    cards = [("코스피", "KOSPI", "", 2), ("원/달러", "USDKRW", "원", 1),
             ("국제 금 · 온스", "GOLD_USD", "달러", 1), ("KRX 김프", "KRX_PREMIUM", "%", 2),
             ("미국 국채 10년", "US10Y", "%", 2), ("국고채 3년", "KR3Y", "%", 2),
             ("WTI · 배럴", "WTI", "달러", 2), ("변동성 지수", "VIX", "", 2)]
    for offset in (0, 4):
        for col, (label, identifier, unit, digits) in zip(st.columns(4), cards[offset:offset+4]):
            with col:
                note = "대체값 · ETF 추이만 제공, 김프 계산 제외" if identifier == "KRX_PREMIUM" and metadata.get("gold_proxy") else ""
                metric_card(label, summary(macro, identifier), unit=unit, digits=digits, note=note)
    st.caption("1일·1개월 변화는 수익률입니다. 금리와 김프의 현재값은 % 단위이며, 기준일이 다른 자료는 각각의 최신 관측값을 표시합니다.")
    if metadata.get("gold_proxy"):
        section("KRX 금현물 대체 추이")
        gold_proxy = series_for(prices, "GOLD_KRX")
        st.caption("대체값 · TIGER KRX금현물 ETF의 주당 가격입니다. 금 1g 가격이 아니므로 김프를 계산하지 않습니다.")
        if not gold_proxy.empty:
            st.plotly_chart(line_figure(gold_proxy.tail(120), "KRX 금현물 ETF"), use_container_width=True)
        else:
            st.caption("데이터 없음")
    with st.expander("데이터 상태와 관측일"):
        if log_items:
            state_labels = {"success": "수집 완료", "failed": "데이터 없음", "skipped": "건너뜀"}
            rows = []
            for item in log_items:
                sid = item.get("id", "")
                s = series_for(prices, sid)
                if s.empty:
                    s = series_for(macro, sid)
                rows.append({"항목": korean_name(by_id[sid]) if sid in by_id else MACRO_LABELS.get(sid, sid),
                             "상태": state_labels.get(item.get("status"), "확인 필요"),
                             "수집 소스": item.get("source") or "데이터 없음",
                             "최신 관측일": s.index[-1].strftime("%Y-%m-%d") if not s.empty else "데이터 없음"})
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        else:
            st.caption("아직 수집 기록이 없습니다.")

with tabs[1]:
    section("관심 종목")
    account_filter = st.selectbox("계좌로 종목 보기", ["전체"] + list(accounts),
                                 format_func=lambda value: "전체 계좌" if value == "전체" else accounts[value].get("label", value), key="account_filter")
    selected_ids = None
    if account_filter != "전체":
        selected_ids = set(accounts[account_filter].get("P1", {})) | set(accounts[account_filter].get("P2", {}))
    groups = {}
    for item in universe:
        if selected_ids is not None and item["id"] not in selected_ids:
            continue
        groups.setdefault(item["asset_class"], []).append(item)
    for asset, items in groups.items():
        st.markdown(f"##### {ASSET_LABELS.get(asset, asset)}")
        rows = []
        for item in items:
            stats = summary(prices, item["id"])
            rows.append({"종목": korean_name(item), "코드": item.get("code", "수동 평가"),
                         "가격": stats["price"], "통화": "달러" if item.get("market") == "US" else "원",
                         **{c: stats.get(c) for c in ("1D", "1W", "1M", "3M", "YTD")},
                         "52주 고점 대비": stats.get("drawdown"), "최근 20일": stats.get("sparkline", []),
                         "관측일": stats.get("date") or "데이터 없음"})
        df = pd.DataFrame(rows)
        return_cols = ["1D", "1W", "1M", "3M", "YTD", "52주 고점 대비"]
        titles = {"1D": "1일", "1W": "1주", "1M": "1개월", "3M": "3개월", "YTD": "연초 대비"}
        finance_table(df.rename(columns=titles), percent_columns=[titles.get(c,c) for c in return_cols], sparkline_columns=["최근 20일"])
    st.caption("가격은 종목의 거래 통화 기준입니다. 수익률은 가격 기준이며 배당·분배금·세금·수수료를 별도 반영하지 않습니다. 시세가 없는 수동 항목은 시나리오 가정으로 평가합니다.")

with tabs[2]:
    import plotly.graph_objects as go

    section("계획한 비중, 목표한 금액")
    allocations = target_rows(plan, amounts, k, mode, universe_config)
    total = sum(amounts.values())
    overview = st.columns(3)
    overview[0].metric("총 계획 금액", f"{number(total, 0)} 만원")
    overview[1].metric("적용 기준", mode)
    overview[2].metric("전환 신호", f"{k} / 3개")
    if total <= 0:
        st.info("사이드바에서 계좌별 금액을 입력하면 목표 금액과 전체 자산군 비중을 확인할 수 있습니다.")
    left, right = st.columns([3, 2])
    with left:
        for account_id, account in accounts.items():
            section(account.get("label", account_id))
            account_rows = allocations.loc[allocations["account"] == account_id].copy()
            account_rows["name"] = account_rows["id"].map(lambda ident: korean_name(by_id.get(ident, {"id": ident})))
            account_rows["rate"] = account_rows["id"].map(lambda ident: by_id.get(ident, {}).get("rate"))
            display = account_rows[["name", "weight", "amount", "rate"]].rename(columns={
                "name": "종목", "weight": "목표 비중 (%)", "amount": "목표 금액 (만원)", "rate": "개별 연 금리 (%)"})
            st.dataframe(display, hide_index=True, width="stretch", column_config={
                "목표 비중 (%)": st.column_config.NumberColumn(format="%.2f"),
                "개별 연 금리 (%)": st.column_config.NumberColumn(format="%.2f"),
                "목표 금액 (만원)": st.column_config.NumberColumn(format="localized")})
            if "risk_cap" in account:
                check = risk_check(blend_weights(account, k, mode), account["risk_cap"])
                message = f"퇴직연금 위험자산 {check['risk_weight']:.1f}% / 한도 {check['cap']:.0f}%"
                st.warning(message + " · 위험자산 한도를 초과했습니다.") if check["exceeded"] else st.success(message + " · 한도 이내")
    with right:
        section("전체 자산군 배분")
        if total > 0 and not allocations.empty:
            grouped = allocations.groupby("asset_class")["amount"].sum()
            grouped = grouped[grouped > 0]
            fig = go.Figure(go.Pie(labels=[ASSET_LABELS.get(c, c) for c in grouped.index], values=grouped.values,
                                   hole=.66, textinfo="percent", marker=dict(colors=["#56d4bb", "#6e9eff", "#e9bc67", "#ad8ef2", "#ec869d", "#7dc5dd", "#abc077"])))
            fig.update_traces(hovertemplate="%{label}<br>%{value:,.0f} 만원 · %{percent}<extra></extra>")
            st.plotly_chart(chart_layout(fig, 400), use_container_width=True)
        else:
            st.caption("금액을 입력하면 전체 비중이 표시됩니다.")
        st.caption("계획 비중은 P1 + (P2 − P1) × 충족 신호 수/3으로 계산합니다. 고정 모드에서는 선택한 국면의 비중을 사용합니다.")

with tabs[3]:
    section("가정을 바꾸면, 계획은 어떻게 달라질까요?")
    presets = scenario_config.get("presets", {})
    options = list(presets) + ["historical", "custom"]
    selection = st.selectbox("시나리오 프리셋", options, key="scenario_preset",
                             format_func=lambda key: presets[key].get("label", key) if key in presets else
                             "2022 상반기 재현" if key == "historical" else "직접 입력")
    historical_missing = []
    preset_values = presets.get(selection, {}).get("inputs", {})
    historical = None
    if selection == "historical":
        if is_demo:
            st.warning("2022 상반기 재현에는 실제 데이터가 필요합니다. 데모 데이터로는 재현하지 않습니다.")
            historical_missing = ["실제 데이터"]
        else:
            historical = historical_2022(macro, prices)
            historical_missing = historical.get("missing", [])
            preset_values = historical.get("inputs") or {}
            if historical_missing:
                st.warning("2022 재현에 필요한 실제 데이터가 부족합니다. 이 프리셋의 결과는 표시하지 않습니다.")
            else:
                st.caption("2022.01.03 → 2022.06.30의 실제 관측값으로 설정한 가정입니다. 개별 종목의 당시 보유 수익률을 복원하는 기능은 아닙니다.")
    previous = st.session_state.get("scenario_selection")
    slider_definitions = [
        ("kr_rate", "한국 금리 변화 (%p)", -3.0, 3.0, .05),
        ("us_rate", "미국 10년 금리 변화 (%p)", -3.0, 3.0, .05),
        ("usdkrw", "원/달러 변화 (%)", -40.0, 40.0, 1.0),
        ("kospi", "코스피 변화 (%)", -60.0, 60.0, 1.0),
        ("semi", "국내 반도체 변화 (%)", -70.0, 70.0, 1.0),
        ("sp500", "S&P500 달러 기준 변화 (%)", -60.0, 60.0, 1.0),
        ("gold", "금 달러 기준 변화 (%)", -50.0, 60.0, 1.0),
        ("wti", "WTI 변화 (%)", -80.0, 100.0, 1.0),
        ("premium", "KRX 김프 변화 (%p)", -20.0, 20.0, .5),
    ]
    if selection != previous:
        for key, _, low, high, _ in slider_definitions:
            st.session_state[f"l1_{key}"] = max(low, min(high, float(preset_values.get(key, 0))))
        st.session_state["scenario_selection"] = selection
    section("1 · 거시 가정 입력")
    l1 = {}
    cols = st.columns(3)
    for index, (key, label, low, high, step) in enumerate(slider_definitions):
        with cols[index % 3]:
            l1[key] = st.slider(label, min_value=low, max_value=high, step=step,
                                key=f"l1_{key}", disabled=bool(historical_missing))
    st.caption("기간 6개월 · 금리·김프는 %p, 그 외 항목은 % 변화입니다. 캐리·듀레이션은 설정 파일에서 수정할 수 있습니다.")
    if not historical_missing:
        result = simulate_portfolio(plan, amounts, universe_config, l1, scenario_config, k=k, mode=mode)
        section("2 · 자산군별 예상 충격")
        shocks = asset_shocks(l1, scenario_config)
        shock_df = pd.DataFrame({"자산군": [ASSET_LABELS.get(c, c) for c in shocks],
                                 "6개월 수익률": [v * 100 for v in shocks.values()]})
        finance_table(shock_df, percent_columns=["6개월 수익률"])
        manual_shocks = instrument_shocks(l1, universe_config, scenario_config)
        manual_rows = [{"종목": korean_name(item), "개별 연 금리": item["rate"],
                        "6개월 수익률": manual_shocks[item["id"]] * 100}
                       for item in universe_config.get("manual", []) if "rate" in item]
        if manual_rows:
            section("수동 항목별 금리 반영")
            finance_table(pd.DataFrame(manual_rows), percent_columns=["개별 연 금리", "6개월 수익률"])
            st.caption("위 자산군 표는 공통 가정입니다. 실제 계획의 손익에는 각 수동 항목에 설정된 개별 금리를 적용하며, 달러 항목은 환율 변화를 곱셈 결합합니다.")
        section("3 · 내 계획에 미치는 영향")
        if result["total_amount"] <= 0:
            st.info("계좌별 금액을 입력하면 전체·계좌별 손익과 기여도가 표시됩니다.")
        result_cols = st.columns(3)
        with result_cols[0]:
            result_card("예상 전체 손익", result["pnl"], " 만원")
        with result_cols[1]:
            result_card("예상 전체 수익률", result["return_pct"], "%", digits=2)
        result_cols[2].metric("평가 기간", "6개월")
        account_result = result["accounts"].rename(columns={"label": "계좌", "amount": "계획 금액 (만원)", "pnl": "예상 손익 (만원)", "return_pct": "예상 수익률"})
        if not account_result.empty:
            visible = account_result[["계좌", "계획 금액 (만원)", "예상 손익 (만원)", "예상 수익률"]]
            finance_table(visible, percent_columns=["예상 수익률"],
                          amount_columns=["계획 금액 (만원)", "예상 손익 (만원)"], signed_columns=["예상 손익 (만원)"])
        contributions = result["contributions"]
        if not contributions.empty and result["total_amount"] > 0:
            grouped = contributions.groupby("asset_class")["pnl"].sum().sort_values()
            fig = go.Figure(go.Bar(x=grouped.values, y=[ASSET_LABELS.get(v, v) for v in grouped.index], orientation="h",
                                   marker_color=[RED if v > 0 else BLUE for v in grouped.values],
                                   hovertemplate="%{y}<br>%{x:+,.0f} 만원<extra></extra>"))
            fig.update_xaxes(title="손익 기여도 (만원)")
            st.plotly_chart(chart_layout(fig, max(250, 28 * len(grouped))), use_container_width=True)
        section("같은 시나리오, 다른 배분")
        comparison = []
        for label, allocation_mode in [("P1", "P1 고정"), (f"블렌딩 ({k}/3)", "자동(신호 기반)"), ("P2", "P2 고정")]:
            simulated = simulate_portfolio(plan, amounts, universe_config, l1, scenario_config, k=k, mode=allocation_mode)
            comparison.append({"배분": label, "예상 손익 (만원)": simulated["pnl"], "예상 수익률": simulated["return_pct"]})
        comp_df = pd.DataFrame(comparison)
        finance_table(comp_df, percent_columns=["예상 수익률"], amount_columns=["예상 손익 (만원)"], signed_columns=["예상 손익 (만원)"])
        st.caption("단순 가정에 따른 민감도 분석입니다. 볼록성·신용위험·세금·수수료·개별 종목의 초과수익은 반영하지 않습니다.")


def render_holdings():
    section("보유 현황과 목표의 간격")
    try:
        holdings = pd.read_csv(holdings_path, dtype={"account": str, "id": str})
        if not {"account", "id", "qty", "avg_price"}.issubset(holdings):
            raise ValueError("schema")
        for col in ("qty", "avg_price"):
            holdings[col] = pd.to_numeric(holdings[col], errors="coerce")
        valid = (holdings["account"].isin(accounts) & holdings["id"].isin(by_id)
                 & holdings["qty"].map(lambda x: pd.notna(x) and math.isfinite(x) and x >= 0)
                 & holdings["avg_price"].map(lambda x: pd.notna(x) and math.isfinite(x) and x >= 0))
        if not valid.all():
            st.warning("계좌·종목·수량·평균 단가 형식이 맞지 않는 보유 행은 제외했습니다.")
        holdings = holdings.loc[valid].copy()
    except (OSError, ValueError, pd.errors.ParserError):
        st.error("보유 파일을 읽을 수 없습니다. 필수 열과 파일 형식을 확인해 주세요.")
        return
    fx = series_for(macro, "USDKRW")
    valued = []
    for _, row in holdings.iterrows():
        history = series_for(prices, row["id"])
        multiplier = float(fx.iloc[-1]) if by_id[row["id"]].get("market") == "US" and not fx.empty else 1.0
        if by_id[row["id"]].get("market") == "US" and fx.empty:
            amount = float("nan")
        else:
            amount = float(row["qty"]) * float(history.iloc[-1]) * multiplier / 10000 if not history.empty else float("nan")
        valued.append({"account": row["account"], "id": row["id"], "valuation": amount})
    current = pd.DataFrame(valued, columns=["account", "id", "valuation"])
    if not current.empty:
        current = current.groupby(["account", "id"], as_index=False)["valuation"].agg(lambda values: values.sum(min_count=len(values)))
    targets = target_rows(plan, amounts, k, mode, universe_config)
    merged = targets.merge(current, on=["account", "id"], how="outer")
    absent = merged["valuation"].isna() & ~merged.set_index(["account", "id"]).index.isin(current.set_index(["account", "id"]).index)
    merged.loc[absent, "valuation"] = 0
    merged["amount"] = merged["amount"].fillna(0)
    merged["gap"] = merged["amount"] - merged["valuation"]
    unplanned = ~merged["account"].isin(saved_amounts)
    merged.loc[unplanned, ["amount", "gap"]] = float("nan")
    if unplanned.any():
        st.info("계획 금액이 저장되지 않은 계좌는 목표와 리밸런싱 금액을 표시하지 않습니다. 사이드바에서 금액을 저장해 주세요.")
    merged["label"] = merged["account"].map(lambda a: accounts[a].get("label", a))
    merged["name"] = merged["id"].map(lambda ident: korean_name(by_id.get(ident, {"id": ident})))
    display = merged[["label", "name", "valuation", "amount", "gap"]].rename(columns={
        "label": "계좌", "name": "종목", "valuation": "평가액 (만원)", "amount": "목표 금액 (만원)", "gap": "리밸런싱 필요 금액 (만원)"})
    display["상태"] = merged["valuation"].map(lambda value: "데이터 없음" if pd.isna(value) else "평가 완료")
    st.dataframe(display, hide_index=True, width="stretch", column_config={
        c: st.column_config.NumberColumn(format="localized") for c in display.columns[2:5]})
    st.caption("리밸런싱 필요 금액이 양수면 추가 매수, 음수면 축소할 금액입니다. 미국 종목은 최신 원/달러로 원화 환산하며, 시세·환율이 없으면 데이터 없음으로 표시합니다. 실제 주문은 실행하지 않습니다.")


if len(tabs) == 5:
    with tabs[4]:
        render_holdings()

st.divider()
st.caption("매크로 보드 · 나만의 시장 점검 루틴 · 모든 금액은 만원 단위")
