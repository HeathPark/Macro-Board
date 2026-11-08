"""개인 설정의 경계와 비중 교체를 합성 자료로 검증합니다."""
import subprocess

import pytest
import yaml

from src.config import ROOT, load_config, save_private_plan


def _public(root):
    (root / "config").mkdir()
    plan = {"accounts": {"synthetic": {"label": "합성 계좌", "P1": {"A": 50, "B": 50}, "P2": {"B": 100}}}}
    (root / "config" / "plan.example.yaml").write_text(yaml.safe_dump(plan), encoding="utf-8")
    return plan


def test_private_weights_replace_instead_of_adding_removed_assets(tmp_path):
    _public(tmp_path)
    (tmp_path / "private").mkdir()
    override = {"accounts": {"synthetic": {"P1": {"C": 100}}}}
    (tmp_path / "private" / "plan.yaml").write_text(yaml.safe_dump(override), encoding="utf-8")
    loaded = load_config("plan", private_override=True, root=tmp_path)
    assert loaded["accounts"]["synthetic"]["P1"] == {"C": 100}
    assert loaded["accounts"]["synthetic"]["label"] == "합성 계좌"
    assert loaded["accounts"]["synthetic"]["P2"] == {"B": 100}
    assert load_config("plan", root=tmp_path)["accounts"]["synthetic"]["P1"] == {"A": 50, "B": 50}


def test_private_save_is_atomic_and_owner_only(tmp_path):
    plan = _public(tmp_path)
    original = (tmp_path / "config" / "plan.example.yaml").read_bytes()
    target = save_private_plan(plan, root=tmp_path)
    assert target == tmp_path / "private" / "plan.yaml"
    assert yaml.safe_load(target.read_text()) == plan
    assert (target.stat().st_mode & 0o777) == 0o600
    assert (target.parent.stat().st_mode & 0o777) == 0o700
    assert list(target.parent.iterdir()) == [target]
    assert (tmp_path / "config" / "plan.example.yaml").read_bytes() == original
    # 다시 저장해도 같은 개인 경로만 갱신합니다.
    save_private_plan(plan, root=tmp_path)
    assert list(target.parent.iterdir()) == [target]


def test_invalid_private_yaml_does_not_expose_contents(tmp_path):
    _public(tmp_path)
    (tmp_path / "private").mkdir()
    marker = "SYNTHETIC_SENSITIVE_MARKER"
    (tmp_path / "private" / "plan.yaml").write_text(f'bad: ["{marker}"', encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_config("plan", private_override=True, root=tmp_path)
    assert marker not in str(exc.value)


def test_private_paths_are_ignored():
    result = subprocess.run(["git", "check-ignore", "private/plan.yaml", "private/.env", "private/holdings.csv"],
                            cwd=ROOT, capture_output=True, text=True, check=True)
    assert set(result.stdout.splitlines()) == {"private/plan.yaml", "private/.env", "private/holdings.csv"}
