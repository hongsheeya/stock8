# 데이터베이스 정리 및 최적화 가이드

## 개요

기존의 무제한 거래 기록 저장에서 벗어나, **일일 요약 기반 아키텍처**로 전환합니다.

### 핵심 변경사항

| 항목 | 기존 | 변경 후 |
|------|------|--------|
| **trade_log** | 모든 개별 거래 기록 (무한 증가) | 최근 30일만 유지 → 매 30일마다 정리 |
| **cycle_trade** | 완료된 거래만 유지 | 변경 없음 (필요한 정보) |
| **simulation_run** | 완료된 시뮬레이션 결과 저장 | 최근 90일만 유지 |
| **simulation_trade** | 모든 상세 거래 기록 | **삭제** (용량 절약) |
| **daily_trade_summary** (신규) | 없음 | 일별 거래 요약 저장 (KRW 현황) |

---

## 테이블 설명

### 1. daily_trade_summary (신규)

각 거래일의 요약 정보를 한 줄로 저장합니다.

```sql
SELECT * FROM daily_trade_summary WHERE trade_date = '2026-05-08';

-- 결과:
-- trade_date        | buy_count | sell_count | total_buy_amount | realized_profit | ...
-- 2026-05-08        | 15        | 12         | 15000000.00      | 125000.00       | ...
```

**포함 정보:**
- 거래 개수 (매수/매도/총계)
- 거래 금액 (총 매수/매도/순매수)
- 수익성 (실현 손익, 수익률)
- 거래 유형별 분류 (무한매수/단타/사이클 거래)
- 참여 종목 (리스트)

### 2. trade_log (정리됨)

최근 30일의 개별 거래 이벤트만 보관합니다.

```sql
-- 정리 전: 100,000+ 레코드
-- 정리 후: 2,000~5,000 레코드 (최근 30일만)
SELECT COUNT(*) FROM trade_log;
```

**정리 방식:**
- 매 30일마다 오래된 레코드 삭제
- daily_trade_summary에 요약 저장됨

### 3. simulation_trade (삭제됨)

시뮬레이션 상세 거래 기록은 필요 없으므로 모두 삭제합니다.

```sql
-- 정리 전: 1,000,000+ 레코드 (모든 시뮬레이션)
DELETE FROM simulation_trade;

-- 정리 후: 0 레코드
SELECT COUNT(*) FROM simulation_trade;
```

### 4. simulation_run (90일 유지)

시뮬레이션 결과 요약만 90일 유지합니다.

```sql
-- 정리 전: 500+ 레코드 (모든 연구 결과)
-- 정리 후: 50~100 레코드 (최근 90일만)
SELECT COUNT(*) FROM simulation_run WHERE created > DATE_SUB(NOW(), INTERVAL 90 DAY);
```

---

## 실행 방법

### 방법 1: 수동 실행 (API)

```bash
# 1. 현재 데이터베이스 상태 확인
curl -X POST http://localhost:3000/wiz/api/page.settings/maintenance_status \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data ""

# 응답:
# {
#   "tables": {
#     "trade_log": 85000,
#     "cycle_trade": 1200,
#     "simulation_run": 450,
#     "simulation_trade": 1200000,
#     "daily_trade_summary": 30
#   },
#   "old_trade_logs_count": 40000
# }
```

```bash
# 2. 전체 정리 실행
curl -X POST http://localhost:3000/wiz/api/page.settings/cleanup_database \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data ""

# 응답:
# {
#   "removed_incomplete_trades": 35,
#   "archived_trade_logs": 40000,
#   "cleaned_simulation_runs": 250,
#   "cleaned_simulation_trades": 1200000,
#   "built_daily_summaries": 30
# }
```

```bash
# 3. 각각 실행

# 거래 로그 정리 (30일 이상 삭제)
curl -X POST http://localhost:3000/wiz/api/page.settings/cleanup_trade_logs \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data "days=30"

# 시뮬레이션 정리 (90일 이상 삭제)
curl -X POST http://localhost:3000/wiz/api/page.settings/cleanup_simulations \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data "days=90"

# 일일 요약 재생성 (최근 30일)
curl -X POST http://localhost:3000/wiz/api/page.settings/rebuild_summaries \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data "from_date=2026-04-08&to_date=2026-05-08"
```

### 방법 2: 자동 실행 (스케줄)

설정 > 데이터 관리 페이지에서 "자동 정리 활성화" 체크

- **실행 시간:** 매일 오후 11:00
- **정리 항목:** 
  - 오래된 거래 로그 (30일 이상)
  - 불완전한 거래 (7일 이상 PENDING)
  - 오래된 시뮬레이션 (90일 이상)
  - 일일 요약 재생성 (최근 30일)

---

## 데이터 복구

### 거거래 로그 필요 시

일별 요약에서 필요한 일자의 상세 정보 조회:

```sql
-- 특정 날짜의 거래 요약 조회
SELECT * FROM daily_trade_summary WHERE trade_date = '2026-05-08';

-- 해당 날짜의 완료된 사이클 조회 (거래 가능)
SELECT * FROM cycle_trade WHERE trade_date = '2026-05-08' AND status = 'FILLED';
```

### 시뮬레이션 결과 필요 시

simulation_run 요약에서 결과만 조회 가능:

```sql
-- 특정 심볼의 시뮬레이션 결과만 확인
SELECT symbol, start_date, end_date, total_profit_rate, win_rate 
FROM simulation_run 
WHERE symbol = 'AAPL' 
ORDER BY created DESC 
LIMIT 5;
```

---

## 예상 저장공간 절감

| 항목 | 정리 전 | 정리 후 | 절감 |
|------|--------|--------|------|
| trade_log | 500MB | 50MB | **90%** |
| simulation_trade | 800MB | 0MB | **100%** |
| simulation_run | 100MB | 30MB | **70%** |
| **총합** | **1.4GB** | **0.2GB** | **85%** |

---

## 주의사항

⚠️ **정리 전 필수:**
1. 최근 거래 내역 확인 완료
2. 필요한 시뮬레이션 결과 내려받기
3. 데이터 정리 후 복구 불가 (성능 최우선)

⚠️ **시뮬레이션 주의:**
- simulation_trade는 **재현 불가**
- simulation_run의 **요약 정보만 유지**
- 상세 거래 필요 시 새로 시뮬레이션 실행

---

## 정리 일정

| 일시 | 정리 대상 | 유지 기간 |
|------|---------|---------|
| **매일 23:00** | 거래 로그 | 30일 |
| **매일 23:15** | 불완전 거래 | 7일 |
| **주 1회 (월요일 23:30)** | 시뮬레이션 | 90일 |
| **매일 23:45** | 일일 요약 | 무제한 |

---

## FAQ

**Q: 거래 로그가 정말 필요 없는가?**
A: daily_trade_summary가 모든 필요한 정보를 요약 보관합니다. 상세 거래가 필요하면 cycle_trade에서 조회 가능합니다.

**Q: 시뮬레이션 재현을 원할 때는?**
A: 시뮬레이션 재설정 후 재실행하면 됩니다. 상세 거래 기록(simulation_trade)이 필요 없으므로 재현은 불가능하지만, 결과 요약(simulation_run)으로 참고 가능합니다.

**Q: 데이터 정리 중 문제 발생시?**
A: 로그 확인: `/tmp/wiz_dashboard_api_errors.log`

**Q: 정리 주기를 변경하려면?**
A: `maintenance.py`의 호출 함수 파라미터 수정:
- `archive_old_trade_logs(days_to_keep=60)` → 60일 유지
- `cleanup_old_simulations(days_to_keep=180)` → 180일 유지
