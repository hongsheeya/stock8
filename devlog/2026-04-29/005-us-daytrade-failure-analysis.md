# FN-20260429-0001: 미장 단타 장애 원인 분석

## 작업 번호
- **ID**: FN-20260429-0001
- **날짜**: 2026-04-29
- **유형**: 버그 분석 및 조사

## 장애 현상
어젯밤(2026-04-28) 미장 단타가 작동하지 않음

## 근본 원인 분석

### 1. 증상
- **runtime_logs.json**: 미장(market="US") 관련 로그 항목 **0개**
- **live_state.json**: 미장 심볼 상태 항목 **0개** (국장 항목만 존재)
- **결론**: 미장 단타가 **스케줄러에서 실행되지 않았음**

### 2. 확인된 근본 원인

#### 원인 1: 미장 구성 데이터 부재
- `trading_cycle` DB 테이블에 market="US" 구성이 저장되었으나, runtime execution이 이를 로드하지 않음
- 가능한 이유: 
  - 데이터베이스 마이그레이션 불완전
  - 구성 캐시 TTL 만료 후 재로드 실패
  - 스케줄러 재시작 시 US 구성을 건너뜀

#### 원인 2: 스케줄러 트리거 실패
- **문제 지점**: api.py의 `live_status()` 함수에서만 미장이 쿼리됨
- **missing**: 자동 실행 스케줄러(`wiz service`의 scheduler)가 미장 심볼을 포함하지 않음
- **현재 상태**: page.daytrade UI에서는 미장 수동 실행만 가능

#### 원인 3: 실시간 신호 생성 중지
- `daytrade_engine.py`의 `signal_status()` 메서드가 미장 시간(ET 09:30~16:00)에도 실행되지 않음
- 원인: 스케줄러가 미장 심볼을 실행 큐에 추가하지 않음

### 3. 관련 코드 위치
- **스케줄러 설정**: `/opt/app/public/app.py` 또는 `/opt/app/project/main/config/season.py`
- **엔진 초기화**: `src/portal/trading/model/struct/daytrade_engine.py` 라인 ~150
- **라이브 상태 캐시**: `src/app/page.daytrade/api.py` 라인 ~100
- **구성 로드**: `src/portal/trading/model/struct/daytrade.py` 라인 ~200

## 재발 방지 체크리스트

### 즉시 조치 (우선순위: 높음)
- [ ] `trading_cycle` DB에서 market별 구성 명시적 조회 테스트
- [ ] 스케줄러의 심볼 초기화 시 국장/미장 모두 포함 확인
- [ ] `signal_status()` 메서드에 market 필터 추가 및 log 출력

### 단계별 검증 포인트
1. **DB 계층**: US 구성 저장 여부 확인
2. **엔진 계층**: `daytrade_engine.signal_status()` US 실행 여부 확인
3. **API 계층**: `live_status()` 응답에 US 데이터 포함 여부 확인
4. **UI 계층**: page.daytrade 페이지 로딩 시 US 상태 표시 여부 확인

## 구현 계획

### Phase 1: 진단 (완료)
- 로그 파일 분석 → **미장 실행 기록 없음 확인**
- DB 쿼리 → **미장 구성 데이터 확인**

### Phase 2: 수정 대상 파일 (다음 단계)
1. `daytrade_engine.py`: US market 조건 추가
2. `page.daytrade/api.py`: live_status() US 필터 확인
3. 스케줄러 설정: US 심볼 실행 추가

### Phase 3: 테스트 (별도 FN-0002에서 진행)
- 백테스트 프레임워크로 US 알고리즘 성능 검증
- 실시간 신호 생성 재테스트

## 결론

**근본 원인**: 스케줄러가 미장 심볼을 실행 큐에 포함하지 않음 → 신호 생성 불가 → 매매 미실행

**해결 방향**:
1. 스케줄러 설정에서 `market="US"` 심볼 명시적 추가
2. `daytrade_engine.signal_status()` 메서드에서 국장/미장 구분 로직 추가
3. 매 시스템 재시작 후 US 구성 로드 확인

**예상 투입 시간**: FN-0004(장마감 로직) 완료 후 통합 테스트 시 함께 검증
