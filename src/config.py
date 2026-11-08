"""공개 설정과 Git에서 제외한 개인 설정을 읽고 안전하게 저장합니다."""
from __future__ import annotations

import copy
import os
from pathlib import Path
import tempfile
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key not in {"P1", "P2"} and isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        # 예외에 개인 파일 내용이나 값이 포함되지 않도록 합니다.
        raise ValueError("설정 파일을 읽을 수 없습니다. YAML 형식을 확인해 주세요.") from None
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("설정 파일의 최상위 항목은 목록이 아닌 키·값이어야 합니다.")
    return value


def load_config(name: str, private_override: bool = False, *, root: Path | str | None = None) -> dict[str, Any]:
    """확장자를 생략할 수 있습니다. 개인 설정은 명시한 경우에만 병합합니다."""
    base = Path(root) if root is not None else ROOT
    stem = name.removesuffix(".yaml").removesuffix(".yml")
    if stem not in {"universe", "plan", "plan.example", "scenarios", "signals"}:
        raise ValueError("지원하지 않는 설정 이름입니다.")
    filename = "plan.example.yaml" if stem in {"plan", "plan.example"} else f"{stem}.yaml"
    public = _read_yaml(base / "config" / filename)
    if private_override:
        private_name = "plan" if stem == "plan.example" else stem
        path = base / "private" / f"{private_name}.yaml"
        if path.is_file():
            public = _merge(public, _read_yaml(path))
    return public


def load_private_environment(*, root: Path | str | None = None) -> None:
    """이미 주입된 환경변수는 덮어쓰지 않습니다. 값은 출력하지 않습니다."""
    base = Path(root) if root is not None else ROOT
    load_dotenv(base / "private" / ".env", override=False)


def save_private_plan(plan: dict[str, Any], *, root: Path | str | None = None) -> Path:
    """금액을 포함한 계획은 private/에만 원자적으로 저장합니다."""
    if not isinstance(plan, dict):
        raise ValueError("계획은 키·값 형식이어야 합니다.")
    base = Path(root) if root is not None else ROOT
    private = base / "private"
    private.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(private, 0o700)
    target = private / "plan.yaml"
    descriptor, temporary = tempfile.mkstemp(prefix=".plan-", suffix=".yaml", dir=private)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            yaml.safe_dump(plan, handle, allow_unicode=True, sort_keys=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return target
