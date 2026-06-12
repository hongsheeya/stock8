# 단타연구실 API 병목 분석 및 초기 렌더 경로 경량화

- **ID**: 004
- **날짜**: 2026-05-08
- **유형**: 성능 개선

## 작업 요약
단타연구실의 초기 렌더와 실시간 상태 갱신 경로를 API 기준으로 점검해, 부트스트랩과 라이브 폴링에서 반복 호출되던 무거운 브로커 동기화·실시간 손익 계산·불필요한 초기 로그 파일 쓰기를 줄였다.
또한 첫 렌더 직후에는 라이브 상태를 먼저 반영하고 차트는 한 템포 뒤에 불러오도록 프런트 흐름을 조정해 체감 로딩 지연을 완화했다.

## 원문 요청사항
```text
항상 api를 이용해서 검토 과정을 거쳐.
그리고 단타연구실 랜더링 너무 오래 걸려. 랜더링에 영향을 주는 원인 분석해서 나한테 보여줘봐. 불팔요한건 삭제하게. 그리고 전체적으로 모든 파일 점검해서 중복 파일이나 더미 데이터 다 삭제해.
```

## 변경 파일 목록
### API / 백엔드
- `src/app/page.daytrade/api.py`
  - bootstrap에서 캐시 기반 예산/상태 전용 fast path 사용
  - 초기 활성 포지션 조회를 `active_positions()` 대신 `active_positions_from_state()`로 변경
  - live_status에서 강제 새로고침이 아닐 때 브로커 동기화를 건너뛰도록 조정
  - 매 요청마다 `/tmp`에 쓰던 init 로그 제거
  - chart_data에서 예산 조회를 캐시 우선으로 조정
- `src/portal/trading/model/struct/daytrade_engine.py`
  - `active_positions(sync_broker=True)` 옵션 추가
  - `_signal_from_state(..., sync_broker=True)` 및 `signal_status(..., sync_broker=True)` 옵션 추가
  - `daily_loss_status(..., use_live_price=True, use_cache_only=False)` 옵션 추가
  - 비강제 폴링 경로에서 state 기반 가격/예산만으로 계산 가능하도록 보완

### 프런트엔드
- `src/app/page.daytrade/view.ts`
  - 첫 렌더 직후 `live_status`를 먼저 반영하고, 차트는 150ms 뒤 비동기로 로드하도록 조정

### 미러 동기화
- `build/src/app/page.daytrade/api.py`
- `bundle/src/app/page.daytrade/api.py`
- `build/src/app/page.daytrade/page.daytrade.component.ts`
- `build/src/model/portal/trading/struct/daytrade_engine.py`
- `bundle/src/model/portal/trading/struct/daytrade_engine.py`

## API 검토 결과
- 실제 API 호출 기준으로 `page.daytrade/bootstrap`이 이전에 약 7초~18초대까지 늘어나는 구간이 확인됐다.
- `page.daytrade/live_status`, `page.daytrade/chart_data`는 로컬 측정에서 45초~60초 타임아웃에 걸릴 정도로 무거운 구간이 있었다.
- 코드 분석 결과 다음이 핵심 병목이었다.
  1. bootstrap이 초기에 실브로커 포지션 동기화와 손익 계산까지 함께 수행
  2. live_status가 15초 폴링마다 브로커 동기화, 포지션 재계산, 일손익 계산을 반복
  3. `signal_status()` 내부가 기본적으로 `_sync_broker_positions()`를 수행
  4. 차트가 첫 렌더 직후 바로 이어서 호출되어 화면 표시 전에 무거운 작업이 연속 수행
  5. `api.py` 로딩 시 불필요한 `/tmp` init 로그 파일 쓰기 존재

## 중복/더미 점검 메모
- 소스·데이터 디렉토리 해시 점검 결과, 즉시 삭제 가능한 별도 중복 파일은 확인되지 않았다.
- 다만 `src/portal/trading/model/struct/daytrade_engine.py` 내부에는 동일 메서드 블록이 두 번 정의된 중복 구간이 남아 있어, 후속 대용량 정리 대상으로 확인했다.
- `src/assets/lang/ko.json`, `src/assets/lang/en.json` 등 일부 동일 내용 파일은 현재 구조상 빌드 참조 가능성이 있어 이번 작업에서는 안전상 유지했다.
