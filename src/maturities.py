"""개인 만기 파일은 캐시·로그 없이 읽고 금액 열은 허용하지 않는다."""
from __future__ import annotations

import csv
from datetime import date, datetime
import math
from pathlib import Path
from zoneinfo import ZoneInfo


def read_maturities(path: Path | str, *, window_days: int, as_of=None) -> dict:
    """오늘부터 설정한 달력일 이내의 만기를 반환한다. 오류 내용은 노출하지 않는다.

    예상한 헤더가 아니면 데이터 행을 읽지 않는다. 유효하지 않은 행은 제외하고
    ``invalid``로만 알린다. 실제 파일의 내용이나 경로는 예외·로그로 내보내지 않는다.
    """
    result = {"present": False, "items": [], "invalid": False}
    try:
        if isinstance(window_days, bool) or int(window_days) != window_days or window_days < 0:
            raise ValueError
        if as_of is None:
            today = datetime.now(ZoneInfo("Asia/Seoul")).date()
        elif isinstance(as_of, datetime):
            today = (as_of.astimezone(ZoneInfo("Asia/Seoul")) if as_of.tzinfo else as_of).date()
        elif isinstance(as_of, date):
            today = as_of
        else:
            today = date.fromisoformat(str(as_of))
    except (TypeError, ValueError, OverflowError):
        return {**result, "invalid": True}
    try:
        with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
            result["present"] = True
            reader = csv.reader(handle)
            header = next(reader, [])
            if len(header) != 3 or set(header) != {"item", "rate", "maturity_date"}:
                return {**result, "invalid": True}
            for values in reader:
                if not values:
                    continue
                if len(values) != len(header):
                    result["invalid"] = True
                    continue
                row = dict(zip(header, values))
                try:
                    item = row["item"].strip()
                    rate = float(row["rate"])
                    raw_date = row["maturity_date"].strip()
                    maturity = date.fromisoformat(raw_date)
                    if not item or not math.isfinite(rate) or maturity.isoformat() != raw_date:
                        raise ValueError
                except (TypeError, ValueError, OverflowError):
                    result["invalid"] = True
                    continue
                days_left = (maturity - today).days
                if 0 <= days_left <= window_days:
                    result["items"].append({"item": item, "rate": rate,
                                            "maturity_date": maturity.isoformat(), "days_left": days_left})
    except FileNotFoundError:
        return result
    except (OSError, UnicodeError, csv.Error):
        return {"present": True, "items": [], "invalid": True}
    result["items"].sort(key=lambda row: (row["maturity_date"], row["item"]))
    return result
