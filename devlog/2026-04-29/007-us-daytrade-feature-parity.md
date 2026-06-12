# FN-20260429-0003: 미장 단타 기능 국장 수준으로 확장

## 작업 번호
- **ID**: FN-20260429-0003
- **날짜**: 2026-04-29
- **유형**: 기능 확장

## 목표
미장 단타(US Daytrade)에서 국장(KS Daytrade)과 동일 수준의 운영 정보를 제공하도록 UI/API/데이터 구조 확장

## 기능 비교: KS vs US (현재 상태)

| 기능 | KS | US | 우선순위 |
|------|----|----|---------|
| **표시 항목** | | | |
| 실시간 신호 상태 | ✅ | ❌ | 높음 |
| 활동 포지션 목록 | ✅ | ❌ | 높음 |
| 일일 거래 요약 | ✅ | ❌ | 높음 |
| 거래 일지(trade log) | ✅ | ❌ | 높음 |
| **운영 기능** | | | |
| 자동 실행 토글 | ✅ | ❌ | 중간 |
| 전략 선택 드롭다운 | ✅ | ❌ | 중간 |
| 시드 설정 입력 | ✅ | ❌ | 중간 |
| 수동 전량 매도 버튼 | ✅ | ❌ | 낮음 |
| 손절가 설정 | ✅ | ❌ | 낮음 |
| **로그 및 상태** | | | |
| 실시간 로그 (일지) | ✅ | ❌ | 높음 |
| 거래 성공/실패 기록 | ✅ | ❌ | 중간 |
| 현재가/평가손익/수익률 | ✅ | ❌ | 높음 |
| 주문 체결 이력 | ✅ | ❌ | 중간 |
| **차트** | ✅ | ✅ (제외) | 제외 |

## 구현 범위 (차트 제외)

### 1. 데이터 구조 확인 및 확장

#### DB 테이블 검증
- `trading_cycle`: market='US' 구성 저장 가능 여부
- `trade_log`: US 거래 로그 저장 여부
- `account_snapshot`: US 포지션 스냅샷 저장 여부

#### 필요시 마이그레이션
```sql
-- US 미지원 레코드 추가 (기존 테이블 재사용)
INSERT INTO trading_cycle 
  (symbol, market, strategy_id, seed, session_date) 
VALUES 
  ('AAPL', 'US', 'us_premarket', 500000, '2026-04-29'),
  ('TSLA', 'US', 'us_breakout', 500000, '2026-04-29');
```

### 2. API 함수 추가 (page.daytrade/api.py)

#### 신규 API
- `get_us_live_status()`: 실시간 신호 + 포지션 상태
- `get_us_daily_summary()`: 일일 거래 요약 (수익률, 거래횟수)
- `get_us_trade_logs()`: 거래 일지 목록 (pagination)
- `update_us_strategy()`: 전략 선택 저장
- `update_us_seed()`: 시드 금액 수정

### 3. UI 컴포넌트 확장 (page.daytrade/view.pug)

#### 섹션 추가
1. **US Market Header** (tab 스타일)
   - 자동 실행 토글 버튼
   - 전략 선택 드롭다운
   - 시드 설정 입력필드

2. **US Live Signals** (실시간 신호 표)
   - 컬럼: 심볼, 전략, 신호상태, 수익률%, 포지션수, 포지션가
   
3. **US Active Positions** (포지션 그리드)
   - 컬럼: 심볼, 진입가, 현재가, 수량, P&L, 소유시간
   - 셀 클릭 시 상세 정보 패널 표시

4. **US Daily Summary** (거래 통계)
   - 거래 횟수, 거래대금, 순손익, 수익률
   - 전략별 분류 표시

5. **US Trade Log** (거래 이력)
   - 타임스탬프, 주문번호, 신호, 체결가, 수량, 손익
   - 페이지네이션 + 필터 (전략/상태)

### 4. TypeScript 로직 확장 (page.daytrade/view.ts)

#### 메서드 추가
```typescript
// US 데이터 로드
async loadUSStatus() { ... }
async loadUSDailyLog() { ... }

// US 운영 기능
async toggleUSAutorun() { ... }
async updateUSStrategy(strategy: string) { ... }
async updateUSSeed(amount: number) { ... }

// 주기적 갱신
startUSStatusRefresh() { setInterval(() => this.loadUSStatus(), 5000); }
```

## 구현 단계

### 단계 1: 데이터 구조 (1시간)
- [ ] `trading_cycle` 테이블 US 레코드 확인
- [ ] `trade_log` 테이블이 market 컬럼 지원하는지 확인
- [ ] 필요시 DB 마이그레이션 쿼리 작성

### 단계 2: API 개발 (2시간)
- [ ] 신규 API 함수 5개 구현
- [ ] 기존 로직과 통합 (캐시, 에러 핸들링)
- [ ] params 검증

### 단계 3: UI 개발 (3시간)
- [ ] 탭 구조 추가 (KS / US 선택)
- [ ] 각 섹션 pug 템플릿 작성
- [ ] 반응형 레이아웃 (모바일 고려)

### 단계 4: 로직 통합 (1.5시간)
- [ ] view.ts 메서드 구현
- [ ] 렌더링 이벤트 핸들링
- [ ] 에러 UI 처리

### 단계 5: 테스트 (1시간)
- [ ] KS/US 탭 전환 테스트
- [ ] 데이터 로드 테스트
- [ ] 릴스펀시브 테스트

## 예상 결과

**완료 후**:
- ✅ page.daytrade에서 KS / US 탭으로 전환 가능
- ✅ US 활동 포지션, 거래 일지, 일일 통계 실시간 표시
- ✅ 전략 선택, 시드 설정, 자동 실행 토글 가능

**총 투입 시간**: 약 8.5시간
