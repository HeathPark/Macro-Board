# AGENTS.md

## 프로젝트
개인용 매크로·자산배분 대시보드(Streamlit).
하루 1회 시세·매크로 수집 → 국면 신호, 종목 수익률, 계좌별 목표 비중, 시나리오 시뮬레이션 표시.
작업 전 docs/CONTEXT.md를 반드시 읽을 것.

## 절대 규칙
- 개인 금액·계좌번호·실제 보유 내역을 코드/커밋/로그/테스트/문서에 넣지 않는다. 금액은 private/(gitignore)에만 둔다.
- 증권사 잔고 API는 쓰지 않는다. 공개 시세·매크로 데이터만 쓴다.
- 수집이 실패해도 앱이 죽으면 안 된다. 화면에 "데이터 없음" 표시 + data/meta/fetch_log.json에 기록.
- UI는 한국어, 상승 빨강 / 하락 파랑, 금액은 만원 단위.
- 종목·비중·금리·임계값은 코드에 하드코딩하지 말고 config/*.yaml에 둔다.

## 명령어
- 샘플 데이터로 실행: python -m src.update --demo
- 데이터 수집: python -m src.update (오늘 데이터가 없을 때만: --if-stale)
- 테스트: pytest -q
- 앱 실행: streamlit run app/main.py (맥북에서는 ./run.sh)

## PR 규칙
- PR 설명에 변경 요약, 테스트 결과, 실데이터 미검증 항목을 적는다.
- 결정이나 가정이 바뀌면 docs/CONTEXT.md의 '변경 이력'에 한 줄 추가한다.
