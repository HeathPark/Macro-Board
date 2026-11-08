"""일별 증분 수집과 격리된 오프라인 데모 데이터 생성."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from dotenv import load_dotenv

from src.config import ROOT, load_config
from src.fetch_prices import COLUMNS, ProviderError, empty_prices, fetch_price
from src.fetch_macro import MissingAPIKey, fetch_macro_series, macro_ids

START_DATE = "2021-12-01"


def _now() -> datetime:
    return datetime.now(ZoneInfo("Asia/Seoul"))


def dataset_directory(root: Path | None = None) -> Path:
    """UI에서 사용하는 활성 데이터 디렉터리 (네트워크 요청 없음)."""
    root = Path(root or ROOT)
    try:
        active = json.loads((root / "data/meta/active_dataset.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        active = {}
    if not isinstance(active, dict):
        active = {}
    return root / ("data/demo" if active.get("mode") == "demo" else "data")


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".update-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".update-", dir=path.parent)
    os.close(descriptor)
    try:
        frame[COLUMNS].to_csv(temporary, index=False, float_format="%.8f")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read_prices(path: Path) -> pd.DataFrame:
    if not path.exists():
        return empty_prices()
    try:
        frame = pd.read_csv(path, dtype={"id": str, "date": str, "source": str})
        if not set(COLUMNS).issubset(frame.columns):
            raise ValueError
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        return frame[COLUMNS].dropna(subset=["date", "id", "close"])
    except (OSError, ValueError, pd.errors.ParserError):
        # Keep a damaged file intact for diagnosis rather than silently replacing it.
        raise ProviderError("invalid_existing_csv") from None


def _merge(old: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    frames = [frame for frame in (old, new) if not frame.empty]
    if not frames:
        return empty_prices()
    return pd.concat(frames, ignore_index=True)[COLUMNS].drop_duplicates(["date", "id"], keep="last").sort_values(["date", "id"]).reset_index(drop=True)


def _next_start(frame: pd.DataFrame, item_id: str) -> str:
    dates = pd.to_datetime(frame.loc[frame["id"] == item_id, "date"], errors="coerce").dropna()
    return (pd.Timestamp(dates.max()) + pd.Timedelta(days=1)).strftime("%Y-%m-%d") if not dates.empty else START_DATE


def _demo_data(universe: dict, end: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """합성 공개 시세만 생성한다. 개인 계좌·금액·보유내역은 다루지 않는다."""
    dates = pd.bdate_range(START_DATE, end)
    t = np.arange(len(dates), dtype=float)
    rng = np.random.default_rng(20211201)
    def frame(item_id, values):
        return pd.DataFrame({"date": dates.strftime("%Y-%m-%d"), "id": item_id, "close": values, "source": "DEMO"})
    prices = []
    for index, item in enumerate(universe["universe"]):
        base = 10_000 + index * 800 if item.get("market") == "KRX" else 150 + index * 10
        values = base * np.exp(np.cumsum(rng.normal(0.00015, 0.006, len(dates))))
        prices.append(frame(item["id"], values))
    prices.append(frame("KRX_GOLD_SPOT", 75_000 * np.exp(t * 0.00024) * (1 + 0.018 * np.sin(t / 60))))
    bases = {"KOSPI": 2800, "KOSDAQ": 850, "SP500": 4500, "NASDAQ": 14000, "SOX": 3200,
             "USDKRW": 1280, "DXY": 103, "GOLD_USD": 1800, "WTI": 80, "COPPER": 4,
             "US10Y": 3.6, "VIX": 22, "KR_BASE_RATE": 3.0, "KR3Y": 3.4,
             "KR10Y": 3.6, "DFEDTARU": 4.5, "CPILFESL": 285, "BAMLH0A0HYM2": 4.0}
    macros = []
    for index, (item_id, base) in enumerate(bases.items()):
        if item_id in {"KR_BASE_RATE", "DFEDTARU"}:
            values = base + np.where(t < 300, t // 80 * 0.25, np.where(t < 650, 0.75, 0.5))
        elif item_id == "CPILFESL":
            values = base * np.exp(t * 0.00012)
        else:
            values = base * (1 + 0.08 * np.sin(t / (50 + index * 2)) + t * 0.000025)
        series = frame(item_id, values)
        if item_id == "CPILFESL":
            series = series.assign(month=pd.to_datetime(series["date"]).dt.to_period("M")).groupby("month").first().reset_index(drop=True)[COLUMNS]
        macros.append(series)
    return pd.concat(prices, ignore_index=True), pd.concat(macros, ignore_index=True)


def _gold_derived(macro: pd.DataFrame, prices: pd.DataFrame, correction: float) -> pd.DataFrame:
    from src.fetch_gold import calculate_gold
    gold = calculate_gold(macro, prices, correction_pct=correction)
    if gold.empty:
        return macro
    additions = []
    for column, item_id in [("international_krw_g", "GOLD_KRW_G"), ("premium_pct", "KRX_PREMIUM")]:
        if column not in gold:
            continue
        values = gold[["date", column]].dropna().rename(columns={column: "close"})
        values["id"] = item_id
        # Derived values from synthetic data remain unmistakably synthetic.
        values["source"] = "DEMO" if not macro.empty and set(macro["source"]) == {"DEMO"} else "calculated"
        additions.append(values[COLUMNS])
    derived_ids = {"GOLD_KRW_G", "KRX_PREMIUM"}
    result = macro[~macro["id"].isin(derived_ids)]
    for addition in additions:
        result = _merge(result, addition)
    return result


def run_update(if_stale: bool = False, demo: bool = False, root: Path | str | None = None) -> dict:
    root = Path(root or ROOT)
    load_dotenv(root / "private/.env", override=False)
    directory = root / ("data/demo" if demo else "data")
    mode = "demo" if demo else "live"
    now = _now()
    today = now.date().isoformat()
    metadata_path = directory / "meta/last_update.json"
    try:
        previous = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = {}
    if not isinstance(previous, dict):
        previous = {}
    previous_timestamp = previous.get("updated_at")
    if if_stale and previous.get("mode") == mode and isinstance(previous_timestamp, str) and previous_timestamp[:10] == today and previous.get("status") == "success":
        _atomic_json(root / "data/meta/active_dataset.json", {"mode": mode, "updated_at": now.isoformat()})
        return {**previous, "skipped_fresh": True}
    # Config loader's private override is intentionally off for public collection.
    config_path = root / "config/universe.yaml"
    if root != Path(ROOT) and config_path.exists():
        import yaml
        universe = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    else:
        universe = load_config("universe")
    logs: list[dict] = []
    if demo:
        prices, macro = _demo_data(universe, today)
        for item_id in [*prices["id"].unique(), *macro["id"].unique()]:
            logs.append({"id": item_id, "status": "success", "source": "DEMO", "rows": int((prices["id"] == item_id).sum() + (macro["id"] == item_id).sum()), "reason": None})
    else:
        prices = _read_prices(directory / "prices_daily.csv")
        macro = _read_prices(directory / "macro_daily.csv")
        def collect(frame, item_id, fetcher):
            start = _next_start(frame, item_id)
            if start > today:
                logs.append({"id": item_id, "status": "success", "source": "existing", "rows": 0, "reason": "already_current"})
                return frame
            try:
                fetched = fetcher(start, today)
                if fetched is None or fetched.empty:
                    raise ProviderError("empty_response")
                fetched = fetched.loc[(fetched["date"] >= start) & (fetched["date"] <= today)]
                logs.append({"id": item_id, "status": "success", "source": str(fetched["source"].iloc[-1]), "rows": len(fetched), "reason": None})
                return _merge(frame, fetched)
            except MissingAPIKey as exc:
                logs.append({"id": item_id, "status": "skipped", "source": None, "rows": 0, "reason": str(exc)})
            except Exception as exc:
                # Only our fixed error codes are safe to persist. Never repr(exc).
                reason = str(exc) if isinstance(exc, ProviderError) else "collection_failed"
                logs.append({"id": item_id, "status": "failed", "source": None, "rows": 0, "reason": reason})
            return frame
        for item in universe["universe"]:
            prices = collect(prices, item["id"], lambda start, end, item=item: fetch_price(item, start, end))
        for item_id in macro_ids():
            macro = collect(macro, item_id, lambda start, end, item_id=item_id: fetch_macro_series(item_id, start, end))
        from src.fetch_gold import fetch_gold
        prices = collect(prices, "KRX_GOLD_SPOT", fetch_gold)
    correction = float(universe.get("gold", {}).get("futures_correction_pct", 0))
    try:
        macro = _gold_derived(macro, prices, correction)
    except Exception:
        logs.append({"id": "KRX_PREMIUM", "status": "failed", "source": None, "rows": 0, "reason": "gold_calculation_unavailable"})
    successes = sum(row["status"] == "success" for row in logs)
    failures = sum(row["status"] == "failed" for row in logs)
    skips = sum(row["status"] == "skipped" for row in logs)
    metadata = {
        "updated_at": now.isoformat(), "mode": mode,
        "status": "success" if not failures and not skips else ("partial" if successes else "failed"),
        "success_count": successes, "failure_count": failures, "skipped_count": skips,
        "gold_proxy": not bool((prices["id"] == "KRX_GOLD_SPOT").any()),
    }
    _atomic_csv(directory / "prices_daily.csv", prices)
    _atomic_csv(directory / "macro_daily.csv", macro)
    _atomic_json(metadata_path, metadata)
    _atomic_json(directory / "meta/fetch_log.json", {"updated_at": now.isoformat(), "items": logs})
    _atomic_json(root / "data/meta/active_dataset.json", {"mode": mode, "updated_at": now.isoformat()})
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Macro Board 공개 데이터 갱신")
    parser.add_argument("--if-stale", action="store_true", help="오늘 성공한 수집이 있으면 생략")
    parser.add_argument("--demo", action="store_true", help="실데이터와 격리된 오프라인 합성 데이터 생성")
    args = parser.parse_args()
    try:
        result = run_update(if_stale=args.if_stale, demo=args.demo)
        print(f"수집 완료: {result['mode']} / {result['status']} / 성공 {result['success_count']} / 실패 {result['failure_count']}")
    except Exception:
        # Invalid local config/files are not market-provider failures; keep secrets out.
        print("수집을 완료하지 못했습니다. 설정 파일과 데이터 CSV 형식을 확인하세요.")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
