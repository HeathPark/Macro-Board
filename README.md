# 매크로 보드

맥북에서 혼자 사용하는 한국어 매크로·자산배분 대시보드입니다. 오늘의 국면 신호, 관심 종목, 계좌별 목표 비중, 6개월 시나리오를 보여 줍니다. 증권사 API나 잔고 조회는 사용하지 않습니다.

코드 작업을 시작하기 전에 [AGENTS.md](AGENTS.md)와 [투자 프레임워크 맥락](docs/CONTEXT.md)을 먼저 읽습니다. 맥락 문서의 세금·상품 메모는 사용자가 제공한 가정이며 실시간 법규·판매 조건을 확인한 자료는 아닙니다.

## 설치와 실행

Python **3.11**과 Git이 필요합니다. 맥북에서는 `brew install python@3.11`로 Python을 설치할 수 있습니다.

```bash
git clone https://github.com/HeathPark/Macro-Board.git
cd Macro-Board
chmod +x run.sh
./run.sh
```

`run.sh`는 `git pull --ff-only` → `.venv` 생성 및 변경된 의존성 설치 → `python -m src.update --if-stale` → 브라우저를 여는 Streamlit 실행 순서로 동작합니다. 저장소에 연결된 추적 브랜치가 있어야 하며, 코드 충돌이 있으면 먼저 해결해야 합니다. 서버는 맥북의 로컬 주소에서만 실행됩니다. 종료는 터미널에서 `Ctrl+C`를 누릅니다. 갱신 명령 자체가 실패해도 경고 후 저장된 자료로 화면을 엽니다.

수동 실행이나 최초 설치는 다음과 같습니다.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m src.update --if-stale
python -m streamlit run app/main.py --server.address=127.0.0.1
```

인터넷 없이 화면과 계산을 확인할 때:

```bash
source .venv/bin/activate
python -m src.update --demo
python -m streamlit run app/main.py --server.address=127.0.0.1
```

데모는 시장 실측값이 아닌 **합성 데이터**입니다. 공개 실데이터와 섞지 않고 `data/demo/`에 저장하며 화면에 데모 상태를 표시합니다. 다시 `python -m src.update`를 실행하면 실데이터 모드로 돌아갑니다. 데모 파일과 활성 모드 표시는 Git에서 제외합니다.

## 개인 정보 저장

공개 저장소에는 개인 금액, 계좌번호, 실제 보유 내역을 넣지 마세요. 사이드바에서 **만원** 단위로 입력한 금액은 `private/plan.yaml`에만 저장합니다. 기본 예시는 계좌별 목표 비중만 담고 있으며 개인 금액을 포함하지 않습니다.

`private/` 전체와 `.env`는 `.gitignore`에 등록되어 있습니다. 개인 파일을 `git add -f`로 강제 추가하지 마세요. Streamlit은 로컬에서만 실행하고 개인 화면을 외부에 공개하지 마세요.

직접 비중을 바꾸려면:

```bash
mkdir -p private
cp -n config/plan.example.yaml private/plan.yaml
```

`private/plan.yaml`의 계좌별 `P1`·`P2` 비중을 수정합니다. 각 국면의 합계는 100%여야 합니다. 금액은 앱에서 입력하면 `amounts` 항목에 저장됩니다. 공개 예시를 개인 정보로 수정하지 마세요. 자동 비중은 `P1 + (P2 − P1) × 충족 신호 수/3`입니다. 퇴직연금 위험자산이 70%를 넘으면 경고합니다. 상품별 실제 퇴직연금 매매 가능 여부는 별도 확인이 필요합니다.

기존 `private/plan.yaml`은 공개 예시가 바뀌어도 덮어쓰지 않습니다. 최신 비중을 사용하려면 개인 파일의 비중을 직접 옮겨 주세요. 이전 개인 계획과의 호환성을 위해 `SHORT_KTB_DIRECT`·`USD_RP`는 유니버스에만 남겨 두며 새 공개 계획에서는 사용하지 않습니다.

### 수동 상품별 금리

`config/universe.yaml`의 `manual`에서 CMA, 특판 발행어음, 은행 예금, 외화 발행어음을 구분합니다. `rate`는 **연율 %**이며, 상품별 값이 `config/scenarios.yaml`의 자산군 기본 캐리보다 우선합니다. 같은 예금 자산군에 속해도 서로 다른 금리가 각 상품·계좌·전체 시뮬레이션에 반영됩니다. 원화 상품은 `금리 × 기간`, 외화 현금 상품은 `(1 + 금리 × 기간) × (1 + 원/달러 변화) − 1`로 계산합니다. 금리와 환율은 계산할 때 %에서 소수로 변환합니다.

계획 탭에서 상품별 연 금리를, 시뮬레이션 탭에서 수동 상품별 충격을 확인할 수 있습니다. 금리·특판 조건은 사용자 입력 가정이며 판매사의 현재 조건을 자동 조회하거나 보장하지 않습니다. 퇴직연금 안전자산 목록은 기존 구성을 유지하며 `config/universe.yaml`의 `retirement_safe_assets`에서 관리합니다.

보유 화면은 `private/holdings.csv`가 있을 때만 추가됩니다. 직접 작성할 열 이름은 `account,id,qty,avg_price`입니다. 계좌는 설정의 내부 ID, 종목은 유니버스의 ID를 사용합니다. `qty`는 수량, `avg_price`는 해당 종목 시세와 같은 통화의 평균 매수가입니다. 계좌번호를 입력할 필요가 없습니다. 이 파일은 개인 맥북의 `private/`에만 두세요.

### 선택적 만기 알림

`private/maturities.csv`가 있으면 한국시간 오늘부터 30일 이내(오늘·30일째 포함)에 만기인 항목을 ‘오늘 할 일’에 표시합니다. 만기가 지난 항목과 알림 기간 밖의 항목은 표시하지 않습니다. 파일이 없으면 알림 기능을 숨깁니다.

파일의 열은 정확히 `item,rate,maturity_date`이며 금액 열은 지원하지 않습니다. `rate`는 연율 %, 날짜는 `YYYY-MM-DD`로 입력합니다. 형식 확인용 [가짜 예시](config/maturities.example.csv)를 `private/`에 복사한 다음 해당 기기에서 항목과 날짜를 수정하세요. 알림 기간은 `config/universe.yaml`의 `alerts.maturity_days`에서 바꿀 수 있습니다. 개인 만기 파일은 공개 데이터 캐시·수집 로그·Git 커밋에 포함하지 않습니다.

## API 키와 GitHub Secrets

키 없이도 공개 시세와 데모·계산 기능을 사용할 수 있습니다. ECOS·FRED 키가 없으면 해당 지표만 `데이터 없음`으로 처리하며, 해당 자료가 필요한 신호나 재현 시나리오도 미검증 상태를 표시합니다.

맥북에서는 `private/.env`에 **본인 키를 직접** 저장하세요. 값은 저장소나 채팅에 공유하지 마세요.

```dotenv
ECOS_API_KEY=
FRED_API_KEY=
```

실행 환경에 이미 주입된 환경변수는 개인 `.env`로 덮어쓰지 않습니다. GitHub에서는 저장소의 **Settings → Secrets and variables → Actions → New repository secret**에서 `ECOS_API_KEY`, `FRED_API_KEY`를 설정합니다. 두 항목은 선택 사항입니다.

GitHub Actions는 평일 17:00 KST(`0 8 * * 1-5`)와 수동 실행에서 `python -m src.update`를 실행합니다. `data/`에 변경이 있을 때만 커밋·푸시하며 `private/`는 수집하거나 커밋하지 않습니다. Actions의 쓰기 권한과 저장소의 브랜치 보호 정책이 커밋을 허용해야 합니다. GitHub 예약 실행은 지연될 수 있습니다.

## 데이터와 종목 추가

`config/universe.yaml`의 `universe`에 고유한 `id`, 한국어 `name`, 문자열 `code`, `market`(`KRX`/`US`), `asset_class`를 추가합니다. 앞자리 0과 영숫자 코드를 보존하려면 `code`는 따옴표로 감쌉니다. 새 ID를 계획에 넣으려면 `private/plan.yaml`도 함께 수정하세요. 시세 없는 자산은 `manual`에 추가합니다.

KRX 소스 순서는 FinanceDataReader → pykrx → yfinance입니다. 미국 종목·지수는 yfinance, 한국 금리는 ECOS, 미국 정책금리·물가·신용스프레드는 FRED를 사용합니다. 시작일은 2021-12-01이며 종목별 마지막 저장일 이후 자료를 받습니다. 신규 상장 상품에 과거 자료를 인위적으로 만들지 않습니다.

- `data/prices_daily.csv`: 공개 종목 시세 (`date,id,close,source`)
- `data/macro_daily.csv`: 공개 매크로 자료 (같은 롱포맷)
- `data/meta/last_update.json`: 마지막 수집 상태
- `data/meta/fetch_log.json`: 항목별 결과와 사용 소스

일부 조회가 실패해도 다른 항목은 계속 수집합니다. 마지막 수집 시각과 지표의 마지막 관측일은 서로 다릅니다. **합성 데모를 실측 자료로 해석하지 마세요.** 종목코드·통계코드 검증 상태, 데이터 단위 및 모델의 가정은 [가정과 검증 현황](docs/ASSUMPTIONS.md)에 기록합니다.

## 계산 설정과 테스트

국면 신호 임계값은 `config/signals.yaml`, 캐리·듀레이션·시나리오 프리셋은 `config/scenarios.yaml`에서 수정합니다. L1의 금리·김프는 %p, 나머지 변화율은 %, 캐리는 연율 %입니다. 모델은 6개월 선형 듀레이션 근사이며 세금·수수료·분배금·추적오차·볼록성은 제외합니다. 과거 재현은 실제 시작일·종료일 자료가 갖춰진 경우에만 계산합니다.

```bash
source .venv/bin/activate
pytest -q
```

테스트의 자료는 공개 시세 형식의 합성 fixture이며 개인 금액·계좌번호·실제 보유 내역을 포함하지 않습니다. 수집 실패, 신호 판정, 비중 블렌딩, 퇴직연금 경고 및 시나리오 공식을 검증합니다.
