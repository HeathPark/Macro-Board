"""공개 시세 합성 fixture/mock만 사용하며 개인 보유정보는 사용하지 않는다."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from src import fetch_macro, fetch_prices, update
from src.fetch_gold import calculate_gold, fetch_gold
from src.fetch_prices import ProviderError, empty_prices


def _rows(item_id: str, dates=("2022-01-03",), values=(100.0,), source="fixture"):
    return pd.DataFrame({"date": dates, "id": item_id, "close": values, "source": source})


@pytest.fixture
def project(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config/universe.yaml").write_text(yaml.safe_dump({
        "universe": [{"id": "GOOD", "code": "0043B0", "market": "KRX"}, {"id": "BAD", "code": "BAD", "market": "US"}],
        "gold": {"futures_correction_pct": 0},
    }), encoding="utf-8")
    return tmp_path


def test_krx_fallback_order_and_alphanumeric_code(monkeypatch):
    calls = []
    def fdr(code, start, end, item_id):
        calls.append(("fdr", code))
        raise RuntimeError("failure")
    def pykrx(code, start, end, item_id):
        calls.append(("pykrx", code))
        return _rows(item_id)
    monkeypatch.setattr(fetch_prices, "_fetch_fdr", fdr)
    monkeypatch.setattr(fetch_prices, "_fetch_pykrx", pykrx)
    result = fetch_prices.fetch_price({"id": "MMF", "code": "0043B0", "market": "KRX"}, "2022-01-01")
    assert calls == [("fdr", "0043B0"), ("pykrx", "0043B0")]
    assert result.iloc[0]["id"] == "MMF"


def test_all_price_failures_are_sanitized(monkeypatch):
    def failure(*args, **kwargs):
        raise RuntimeError("do-not-persist-provider-detail")
    monkeypatch.setattr(fetch_prices, "fetch_yahoo", failure)
    with pytest.raises(ProviderError, match="^all_price_sources_unavailable$"):
        fetch_prices.fetch_price({"id": "TEST", "code": "TEST", "market": "US"}, "2022-01-01")


def test_normalize_timezone_close_and_invalid_values():
    raw = pd.DataFrame({"Close": [100, 0, -2, "101.5"]}, index=pd.date_range("2022-01-03", periods=4, tz="Asia/Seoul"))
    result = fetch_prices.normalize_history(raw, "TEST", "fixture")
    assert result["date"].tolist() == ["2022-01-03", "2022-01-06"]
    assert result["close"].tolist() == [100, 101.5]


def test_missing_api_keys_skip_without_network(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.delenv("ECOS_API_KEY", raising=False)
    monkeypatch.setattr(fetch_macro, "_safe_json", lambda *a, **k: pytest.fail("missing keys must not connect"))
    with pytest.raises(fetch_macro.MissingAPIKey):
        fetch_macro.fetch_fred("DFEDTARU", "2022-01-01")
    with pytest.raises(fetch_macro.MissingAPIKey):
        fetch_macro.fetch_ecos("KR3Y", "2022-01-01")


def test_fred_numeric_missing_observations(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "fixture-only-not-a-secret")
    monkeypatch.setattr(fetch_macro, "_safe_json", lambda *a, **k: {"observations": [{"date": "2022-01-01", "value": "."}, {"date": "2022-01-02", "value": "4.5"}]})
    result = fetch_macro.fetch_fred("DFEDTARU", "2022-01-01")
    assert result["close"].tolist() == [4.5]


def test_ecos_item_lookup_before_series(monkeypatch):
    monkeypatch.setenv("ECOS_API_KEY", "fixture-only-not-a-secret")
    calls = []
    def rows(service, key, suffix):
        calls.append(service)
        if service == "StatisticItemList":
            return [{"ITEM_CODE": "010200000", "ITEM_NAME": "국고채(3년)", "CYCLE": "D"}]
        return [{"TIME": "20220103", "DATA_VALUE": "2.13"}]
    monkeypatch.setattr(fetch_macro, "_ecos_rows", rows)
    result = fetch_macro.fetch_ecos("KR3Y", "2022-01-01", "2022-01-04")
    assert calls == ["StatisticItemList", "StatisticSearch"]
    assert result.iloc[0]["date"] == "2022-01-03"
    assert result.iloc[0]["close"] == 2.13


def test_ecos_unknown_item_not_silently_accepted(monkeypatch):
    monkeypatch.setenv("ECOS_API_KEY", "fixture-only-not-a-secret")
    monkeypatch.setattr(fetch_macro, "_ecos_rows", lambda *a: [{"ITEM_CODE": "unrelated", "ITEM_NAME": "다른 지표", "CYCLE": "D"}])
    with pytest.raises(ProviderError, match="ecos_item_not_verified"):
        fetch_macro.fetch_ecos("KR3Y", "2022-01-01")


def test_ecos_correct_code_with_wrong_name_is_not_verified(monkeypatch):
    monkeypatch.setenv("ECOS_API_KEY", "fixture-only-not-a-secret")
    monkeypatch.setattr(fetch_macro, "_ecos_rows", lambda *a: [{"ITEM_CODE": "010200000", "ITEM_NAME": "다른 지표", "CYCLE": "D"}])
    with pytest.raises(ProviderError, match="ecos_item_not_verified"):
        fetch_macro.fetch_ecos("KR3Y", "2022-01-01")


def test_partial_collection_preserves_success_and_sanitizes_logs(project, monkeypatch):
    def prices(item, start, end):
        if item["id"] == "BAD":
            raise RuntimeError("do-not-persist-provider-detail")
        return _rows(item["id"])
    monkeypatch.setattr(update, "fetch_price", prices)
    monkeypatch.setattr(update, "macro_ids", lambda: ["DFEDTARU"])
    monkeypatch.setattr(update, "fetch_macro_series", lambda *a: (_ for _ in ()).throw(fetch_macro.MissingAPIKey("missing_FRED_API_KEY")))
    monkeypatch.setattr("src.fetch_gold.fetch_gold", lambda *a: (_ for _ in ()).throw(ValueError("unavailable")))
    result = update.run_update(root=project)
    assert result["status"] == "partial"
    assert result["success_count"] == 1
    assert result["failure_count"] == 2
    stored = pd.read_csv(project / "data/prices_daily.csv")
    assert stored["id"].tolist() == ["GOOD"]
    logs = (project / "data/meta/fetch_log.json").read_text()
    assert "do-not-persist-provider-detail" not in logs
    assert "collection_failed" in logs


def test_incremental_start_and_merge_without_duplicates(project, monkeypatch):
    directory = project / "data"
    directory.mkdir()
    _rows("GOOD", dates=("2022-01-03", "2022-01-04"), values=(100, 101)).to_csv(directory / "prices_daily.csv", index=False)
    starts = []
    def fetch(item, start, end):
        starts.append((item["id"], start))
        return _rows(item["id"], dates=(start,), values=(102,))
    monkeypatch.setattr(update, "fetch_price", fetch)
    monkeypatch.setattr(update, "macro_ids", lambda: [])
    monkeypatch.setattr("src.fetch_gold.fetch_gold", lambda *a: (_ for _ in ()).throw(ValueError("unavailable")))
    update.run_update(root=project)
    assert ("GOOD", "2022-01-05") in starts
    assert ("BAD", "2021-12-01") in starts
    frame = pd.read_csv(directory / "prices_daily.csv")
    assert not frame.duplicated(["date", "id"]).any()
    assert len(frame[frame["id"] == "GOOD"]) == 3


def test_demo_is_offline_and_does_not_overwrite_live_data(project, monkeypatch):
    live = project / "data/prices_daily.csv"
    live.parent.mkdir()
    live.write_text("date,id,close,source\n2022-01-03,REAL,123,fixture\n")
    monkeypatch.setattr(update, "fetch_price", lambda *a, **k: pytest.fail("demo must not use network"))
    result = update.run_update(demo=True, root=project)
    assert result["mode"] == "demo"
    assert "REAL" in live.read_text()
    demo = pd.read_csv(project / "data/demo/prices_daily.csv")
    assert set(demo["source"]) == {"DEMO"}
    assert update.dataset_directory(project) == project / "data/demo"
    assert "2022-01-03" in set(demo["date"])
    macro = pd.read_csv(project / "data/demo/macro_daily.csv")
    assert "KRX_PREMIUM" in set(macro["id"])
    assert set(macro["source"]) == {"DEMO"}


def test_if_stale_skips_success_same_day(project, monkeypatch):
    update.run_update(demo=True, root=project)
    monkeypatch.setattr(update, "_demo_data", lambda *a: pytest.fail("fresh demo should not regenerate"))
    assert update.run_update(if_stale=True, demo=True, root=project)["skipped_fresh"]


def test_valid_json_wrong_metadata_shape_falls_back_safely(project):
    metadata = project / "data/meta"
    metadata.mkdir(parents=True)
    (metadata / "active_dataset.json").write_text("[]")
    assert update.dataset_directory(project) == project / "data"
    demo_metadata = project / "data/demo/meta"
    demo_metadata.mkdir(parents=True)
    (demo_metadata / "last_update.json").write_text("[]")
    assert update.run_update(if_stale=True, demo=True, root=project)["status"] == "success"


def test_corrupt_live_csv_is_preserved(project, monkeypatch):
    path = project / "data/prices_daily.csv"
    path.parent.mkdir()
    path.write_text("unexpected,format\n1,2\n")
    with pytest.raises(ProviderError, match="invalid_existing_csv"):
        update.run_update(root=project)
    assert path.read_text() == "unexpected,format\n1,2\n"


def test_gold_premium_uses_matching_day_and_gram_units():
    gold_usd = _rows("GOLD_USD", values=(2000,))
    fx = _rows("USDKRW", values=(1300,))
    spot = _rows("KRX_GOLD_SPOT", values=(2000 * 1300 / 31.1035 * 1.03,))
    result = calculate_gold(pd.concat([gold_usd, fx]), spot)
    assert result.iloc[0]["premium_pct"] == pytest.approx(3)


def test_gold_etf_proxy_never_becomes_fake_spot_or_premium():
    macro = pd.concat([_rows("GOLD_USD", values=(2000,)), _rows("USDKRW", values=(1300,))])
    result = calculate_gold(macro, _rows("GOLD_KRX", values=(15000,)))
    assert result.iloc[0]["proxy"]
    assert pd.isna(result.iloc[0]["premium_pct"])
    assert pd.isna(result.iloc[0]["krx_krw_g"])
    assert result.iloc[0]["proxy_price"] == 15000


def test_gold_mismatched_dates_do_not_use_future_fx():
    macro = pd.concat([_rows("GOLD_USD", values=(2000,)), _rows("USDKRW", dates=("2022-01-04",), values=(1300,))])
    result = calculate_gold(macro, _rows("KRX_GOLD_SPOT", values=(85000,)))
    assert result["premium_pct"].isna().all()


def test_gold_collector_rejects_product_without_date_unit(monkeypatch):
    class Response:
        text = "<table><tr><th>상품명</th><th>종가</th></tr><tr><td>금99.99_1kg</td><td>100000</td></tr></table>"
        def raise_for_status(self):
            pass
    monkeypatch.setattr("src.fetch_gold.requests.get", lambda *a, **k: Response())
    with pytest.raises(ValueError):
        fetch_gold("2022-01-01")


def test_gold_collector_requires_explicit_gram_price_unit(monkeypatch):
    class Response:
        text = "<table><tr><th>일자</th><th>상품명</th><th>종가</th></tr><tr><td>2022-01-03</td><td>금99.99_1kg</td><td>100000</td></tr></table>"
        def raise_for_status(self):
            pass
    monkeypatch.setattr("src.fetch_gold.requests.get", lambda *a, **k: Response())
    with pytest.raises(ValueError):
        fetch_gold("2022-01-01")


def test_gold_collector_accepts_explicit_product_date_and_unit(monkeypatch):
    class Response:
        text = "<table><tr><th>일자</th><th>상품명</th><th>종가(원/g)</th></tr><tr><td>2022-01-03</td><td>금99.99_1kg</td><td>100000</td></tr></table>"
        def raise_for_status(self):
            pass
    monkeypatch.setattr("src.fetch_gold.requests.get", lambda *a, **k: Response())
    result = fetch_gold("2022-01-01", "2022-01-04")
    assert result.iloc[0]["close"] == 100000
    assert result.iloc[0]["id"] == "KRX_GOLD_SPOT"
