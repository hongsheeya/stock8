# KST 기본 시간 저장·표시 체계 전면 적용

- **ID**: 002
- **날짜**: 2026-05-12
- **유형**: 버그 수정

## 작업 요약
단타/대시보드/설정/이력/시뮬레이션 및 관련 모델 전반에서 UTC 기반 시간 생성과 표시를 한국 시간 기준으로 통일했다.
공통 KST 유틸을 추가하고, 프론트의 `toISOString()` 기반 날짜 기본값도 한국 시간 포맷으로 교체해 앞으로 새로 저장되거나 표시되는 시간이 UTC로 밀리지 않도록 정리했다.

## 원문 요청사항
```text
단타 종목에 표시하는 시간 또 UTC 시간으로 표시하잖아. 아니 그냥 한국 시간을 디폴트로 저장하고 시간 필요할때마다 그걸 가져오면 되는거잖아. 왜 그렇게 안하고 시간 추가될때마다 utc로 해서 내가 수정해야하는건데. 모든 시간이 들어가는 부분 다 수정하고 앞으로 UTC 다시 안나오게 해.. 무조건 한국 시간 기준이야
```

## 변경 파일 목록
### 공통 시간 유틸
- `src/portal/trading/model/kst.py`
  - KST 현재시각/날짜/정규화/ISO 포맷 공통 헬퍼 추가
- `src/app/utils/kst.ts`
  - 프론트 기본 날짜 문자열을 한국 시간으로 계산하는 유틸 추가
- `src/types/wiz-modules.d.ts`
  - 시간 유틸 선언 보강

### 프론트엔드
- `src/app/page.daytrade/view.ts`
  - 로그 조회 기본 날짜를 한국 날짜 기준으로 초기화
- `src/app/page.simulation/view.ts`
  - 시뮬레이션 기본 시작/종료일을 한국 날짜 기준으로 초기화

### API / 화면 데이터
- `src/app/page.daytrade/api.py`
- `src/app/page.daytrade.us/api.py`
- `src/app/page.history/api.py`
- `src/app/page.dashboard/api.py`
- `src/app/page.settings/api.py`
- `src/app/page.settings/maintenance_api.py`
- `src/app/page.simulation/api.py`
  - 응답 타임스탬프, 로그, 갱신 시각, 유지보수 상태 시간을 KST 기본값으로 통일

### 트레이딩 모델 / 스케줄러
- `src/portal/trading/model/struct.py`
- `src/portal/trading/model/struct/daytrade.py`
- `src/portal/trading/model/struct/daytrade_engine.py`
- `src/portal/trading/model/struct/engine.py`
- `src/portal/trading/model/struct/kis_api.py`
- `src/portal/trading/model/maintenance.py`
- `src/portal/trading/model/scheduler.py`
- `src/portal/trading/route/scheduler/controller.py`
  - 저장/로그/스냅샷/상태 시간과 날짜 기준을 KST 기본값으로 변경
  - 단타 런타임 로그 dedup 비교도 KST 기준으로 정리

### 기타 모델
- `src/model/struct/user.py`
- `src/portal/post/model/struct/post.py`
- `src/portal/post/model/struct/comment.py`
  - 생성/수정 시각 저장을 KST 문자열 기준으로 통일

### 검증
- 프로젝트 일반 빌드 성공
- `page.daytrade/ping` 응답 타임스탬프가 KST 기준으로 내려오는 것 확인
- `page.daytrade/live_status` 응답의 `worker_last_run_at`가 KST 문자열로 유지되는 것 확인
