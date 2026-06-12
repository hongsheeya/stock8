# Trading Package

무한매수법(라오어) 기반 미국 레버리지 ETF 자동매매 시스템.

---

## 구성요소

### Model

| 경로 | 설명 |
|------|------|
| `model/struct.py` | Composite Struct (싱글톤) |
| `model/struct/kis_api.py` | 한국투자증권 API 연동 |
| `model/struct/engine.py` | 무한매수법 알고리즘 엔진 |
| `model/db/trading_config.py` | 전역 매매 설정 |
| `model/db/etf_watchlist.py` | 운용 종목 리스트 |
| `model/db/trading_cycle.py` | 매매 사이클 |
| `model/db/cycle_trade.py` | 사이클 내 개별 거래 |
| `model/db/trade_log.py` | 전체 거래 로그 |
| `model/db/account_snapshot.py` | 일별 계좌 스냅샷 |
| `model/db/simulation_run.py` | 모의투자 실행 기록 |
| `model/db/simulation_trade.py` | 모의투자 거래 기록 |

### 사용법

```python
# struct 로드
trading = wiz.model("portal/trading/struct")

# DB 접근
config_db = trading.db("trading_config")
watchlist_db = trading.db("etf_watchlist")

# 한투 API
api = trading.kis_api
price = api.get_current_price("TQQQ")

# 엔진
engine = trading.engine
engine.run_daily("TQQQ")
```

## 최신 무한매수법 규칙

### 매수 규칙

- 1회차는 시장가 매수
- 2회차부터 기본 분할 횟수까지는 LOC 지정가 매수
- 분할 매수를 모두 소진하면 사이클은 `PENDING_EXTENSION` 상태로 전환되며, 대시보드에서 추가 매수 또는 홀딩 유지를 선택할 수 있음
- KIS 자동환전 주문을 고려하여, 대시보드의 매수 가능액은 USD 주문가능액 + 원화 잔고의 USD 환산값을 함께 표시함

### 매도 규칙

- 기본 전략은 목표 수익률 도달 시 전량 매도
- 고급 전략으로 분할 매도 지원
	- 설정된 시작 회차 이후 목표 수익률 도달 시 보유 수량의 일부만 매도
	- 분할 매도 후 잔량이 다시 목표 수익률에 도달하면, `partial_sell_remaining_full_exit=true` 설정 시 전량 매도
- 수수료/세금을 반영한 순수익률 기준으로 매도 판단

### 폭락장 추가 매입 규칙

- 옵션 활성화 시 전일 대비 하락률 또는 5일 이동평균 이탈률 기준으로 폭락장 감지
- 폭락장으로 판단되면 잔여 투자금의 일부를 추가 LOC 매수
- 사이클별 최대 추가 매입 횟수 제한 지원

### 대시보드 수동 제어

- 대시보드 `Engine Control` 패널에서 시작 가능한 종목을 선택하고 즉시 사이클 시작 가능
- 빠른 시작 버튼 목록으로 종목별 수동 시작 가능
- 자동 매매 토글, 즉시 실행, 강제 종료, 일시정지/재개를 모두 UI에서 제어 가능

### DB 네임스페이스

- `trading`: SQLite (`data/db/trading.db`)

### 의존성

- `portal/season`: ORM, Session, Config
- Python: `requests`, `peewee`

## Version

- **Package**: trading
- **Version**: 1.0.0

## Structure

```
trading/
├── portal.json      # Package configuration
├── README.md        # This file
├── app/             # Application components
├── controller/      # Controllers
└── route/           # Routes
```

## Usage

This package can be used within WIZ Framework projects.

## License

MIT License
