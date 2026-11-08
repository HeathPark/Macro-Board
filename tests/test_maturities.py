"""개인 일정이 아닌 합성 만기 입력으로 경계와 정보 보호를 검증한다."""
from datetime import datetime, timezone

from src.maturities import read_maturities


def test_missing_file_is_optional(tmp_path):
    assert read_maturities(tmp_path / "missing.csv", window_days=30) == {
        "present": False, "items": [], "invalid": False}


def test_today_and_day_thirty_are_inclusive_but_expired_and_day_thirty_one_are_not(tmp_path):
    path = tmp_path / "maturities.csv"
    path.write_text("item,rate,maturity_date\n"
                    "합성 31일,1,2026-12-09\n합성 당일,1,2026-11-08\n"
                    "합성 만료,1,2026-11-07\n합성 30일,1,2026-12-08\n", encoding="utf-8")
    result = read_maturities(path, window_days=30, as_of="2026-11-08")
    assert not result["invalid"]
    assert [row["days_left"] for row in result["items"]] == [0, 30]
    assert [row["item"] for row in result["items"]] == ["합성 당일", "합성 30일"]


def test_window_is_configurable_and_timezone_uses_korea(tmp_path):
    path = tmp_path / "maturities.csv"
    path.write_text("item,rate,maturity_date\n합성 당일,1,2026-11-08\n합성 이틀,1,2026-11-10\n",
                    encoding="utf-8")
    as_of = datetime(2026, 11, 7, 15, 30, tzinfo=timezone.utc)
    result = read_maturities(path, window_days=1, as_of=as_of)
    assert [row["days_left"] for row in result["items"]] == [0]


def test_unexpected_amount_header_is_rejected_without_reading_rows(tmp_path, monkeypatch):
    path = tmp_path / "maturities.csv"
    path.write_text("item,rate,maturity_date,amount\n", encoding="utf-8")
    def header_only(handle):
        yield ["item", "rate", "maturity_date", "amount"]
        raise AssertionError("허용하지 않은 파일의 데이터 행을 읽었습니다")
    monkeypatch.setattr("src.maturities.csv.reader", header_only)
    result = read_maturities(path, window_days=30)
    assert result == {"present": True, "items": [], "invalid": True}


def test_invalid_rows_are_skipped_without_exposing_raw_values(tmp_path, caplog):
    marker = "SYNTHETIC_PRIVATE_MARKER"
    path = tmp_path / "maturities.csv"
    path.write_text(f"item,rate,maturity_date\n{marker},invalid,invalid\n"
                    "합성 정상,1,2026-11-08\n합성 잘못된 금리,nan,2026-11-08\n",
                    encoding="utf-8")
    result = read_maturities(path, window_days=30, as_of="2026-11-08")
    assert result["invalid"]
    assert [row["item"] for row in result["items"]] == ["합성 정상"]
    assert marker not in str(result)
    assert marker not in caplog.text


def test_bad_encoding_and_duplicate_headers_are_safe(tmp_path):
    path = tmp_path / "maturities.csv"
    path.write_bytes(b"\xff\xfe\x00")
    assert read_maturities(path, window_days=30)["invalid"]
    path.write_text("item,rate,rate\n", encoding="utf-8")
    assert read_maturities(path, window_days=30)["invalid"]
