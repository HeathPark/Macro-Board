"""합성 환경에서 화면·모드 전환·비공개 저장 경계를 검증한다."""
from pathlib import Path
import json
import shutil

import pytest
import yaml
from streamlit.testing.v1 import AppTest

from src import config
from src.update import run_update

APP = Path(__file__).resolve().parents[1] / "app" / "main.py"


@pytest.fixture
def local_app(tmp_path, monkeypatch):
    shutil.copytree(config.ROOT / "config", tmp_path / "config")
    monkeypatch.setattr(config, "ROOT", tmp_path)
    return tmp_path


def test_empty_market_stays_usable_without_network(local_app, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("화면이 네트워크 수집을 호출했습니다")
    monkeypatch.setattr("requests.sessions.Session.request", forbidden)
    app = AppTest.from_file(str(APP)).run(timeout=15)
    assert not app.exception
    assert [tab.label for tab in app.tabs] == ["오늘", "종목", "계획", "시뮬레이션"]
    assert any("아직 시장 데이터가 없습니다" in item.value for item in app.info)
    assert any("데이터 없음" in item.value for item in app.markdown)
    assert len(app.slider) == 9
    assert all(item.value == 0 for item in app.number_input)


def test_demo_preset_and_unavailable_historical_mode(local_app):
    run_update(demo=True, root=local_app)
    app = AppTest.from_file(str(APP)).run(timeout=15)
    assert not app.exception
    assert any("데모 모드" in item.value for item in app.info)
    scenario = next(item for item in app.selectbox if item.label == "시나리오 프리셋")
    scenario.set_value("S2").run(timeout=15)
    assert not app.exception
    assert app.slider(key="l1_kospi").value == -30.0
    assert app.slider(key="l1_us_rate").value == -0.8
    assert any("2 · 자산군별 예상 충격" in item.value for item in app.markdown)
    scenario = next(item for item in app.selectbox if item.label == "시나리오 프리셋")
    scenario.set_value("historical").run(timeout=15)
    assert not app.exception
    assert all(item.disabled for item in app.slider)
    assert any("실제 데이터가 필요" in item.value for item in app.warning)
    assert not any("2 · 자산군별 예상 충격" in item.value for item in app.markdown)


def test_synthetic_normalized_input_only_saved_under_private(local_app):
    app = AppTest.from_file(str(APP)).run(timeout=15)
    app.number_input[0].set_value(1.0)
    next(item for item in app.button if item.label == "금액 저장·적용").click().run(timeout=15)
    assert not app.exception
    private = local_app / "private" / "plan.yaml"
    assert private.is_file()
    assert private.stat().st_mode & 0o777 == 0o600
    saved = yaml.safe_load(private.read_text())
    assert saved["amounts"]["pension_savings"] == 1.0
    assert not list((local_app / "config").glob("*private*"))
    assert not (local_app / "data").exists()


def test_wrong_shaped_metadata_keeps_screen_available(local_app):
    meta = local_app / "data" / "meta"
    meta.mkdir(parents=True)
    for name, value in [("active_dataset.json", []), ("last_update.json", []),
                        ("fetch_log.json", {"items": [None, "invalid", {}]})]:
        (meta / name).write_text(json.dumps(value), encoding="utf-8")
    app = AppTest.from_file(str(APP)).run(timeout=15)
    assert not app.exception
    assert len(app.tabs) == 4


def test_optional_holdings_tab_handles_missing_quotes(local_app):
    private = local_app / "private"
    private.mkdir()
    # 실제 보유가 아닌 단위 수량의 합성 입력이다.
    (private / "holdings.csv").write_text(
        "account,id,qty,avg_price\nbrokerage,MSFT,1,1\n", encoding="utf-8")
    app = AppTest.from_file(str(APP)).run(timeout=15)
    assert not app.exception
    assert [tab.label for tab in app.tabs][-1] == "보유"
    assert len(app.tabs) == 5
    table = app.dataframe[-1].value
    row = table.loc[table["종목"].eq("마이크로소프트")].iloc[0]
    assert row["평가액 (만원)"] != row["평가액 (만원)"]  # 결측은 0으로 대체하지 않는다.
