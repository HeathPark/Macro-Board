#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# 개인 설정은 private/에 있으므로 공개 저장소 갱신과 분리됩니다.
git pull --ff-only

if [[ ! -x .venv/bin/python ]]; then
  if command -v python3.11 >/dev/null 2>&1; then
    python3.11 -m venv .venv
  elif command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; raise SystemExit(sys.version_info[:2] != (3, 11))'; then
    python3 -m venv .venv
  else
    printf '%s\n' 'Python 3.11을 먼저 설치해 주세요. 맥북: brew install python@3.11' >&2
    exit 1
  fi
fi
.venv/bin/python -c 'import sys; sys.exit("Python 3.11 가상환경이 필요합니다.") if sys.version_info[:2] != (3, 11) else None'

# 요구사항이 바뀐 경우에만 설치합니다. 성공한 설치의 지문만 저장합니다.
requirements_hash="$(shasum -a 256 requirements.txt | cut -d ' ' -f 1)"
installed_hash=""
if [[ -f .venv/.requirements.sha256 ]]; then
  installed_hash="$(cat .venv/.requirements.sha256)"
fi
if [[ "$requirements_hash" != "$installed_hash" ]]; then
  .venv/bin/python -m pip install --quiet -r requirements.txt
  printf '%s\n' "$requirements_hash" > .venv/.requirements.sha256
fi
if ! .venv/bin/python -m src.update --if-stale; then
  printf '%s\n' '데이터 갱신을 완료하지 못했습니다. 저장된 데이터로 화면을 엽니다. 수집 상태를 확인해 주세요.' >&2
fi
exec .venv/bin/python -m streamlit run app/main.py --server.address=127.0.0.1 --server.headless=false
