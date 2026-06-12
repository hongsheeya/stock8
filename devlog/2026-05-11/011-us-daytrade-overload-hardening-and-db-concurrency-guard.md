# 미장 단타 과부하 하드닝 및 DB 동시성 가드

- **ID**: 011
- **날짜**: 2026-05-11
- **유형**: 버그 수정

## 작업 요약
미장 단타 화면의 초기 API 팬아웃과 대시보드 고비용 조회 경로를 줄이기 위해 스냅샷 API, 캐시, singleflight, ORM DB 동시성 가드를 추가했다.
실서비스 `daytrade/us`와 `favicon.ico`에 대해 동시 요청 검증을 반복했고, 저부하 구간 안정성은 개선됐지만 고부하 스트레스 후에는 프로세스에 누적된 MySQL 연결이 남아 500으로 전이되는 현상도 함께 확인했다.

## 원문 요청사항
```text
계속 안되잖아. 서버 과부화인지도 체크한거야? 최적화 최대한 진행해서 과부화 안걸리게해
```

## 변경 파일 목록
- `src/app/page.daytrade.us/api.py`
  - `us_snapshot()` 통합 API 추가
  - `us_bootstrap()`에 snapshot 포함 및 bootstrap/snapshot singleflight 적용
  - `us_get_auto_status()`, `us_verify_runtime()`, `us_daily_log()` 공용 payload/cache 경로로 정리
  - 미장 초기 요청 fan-out을 줄이기 위한 TTL 캐시 추가
- `src/app/page.daytrade.us/view.ts`
  - 초기 로딩과 리프레시를 `us_snapshot()` 기반으로 통합
  - bootstrap 이후 불필요한 상태/검증 개별 호출 제거
- `src/portal/trading/model/struct.py`
  - `kis_api`, `engine`, `daytrade` sub-struct 인스턴스 재사용 캐시 추가
- `src/portal/season/model/orm.py`
  - ORM query/rows/count/insert/update/delete에 connection close 보강
  - 재진입 가능한 DB 동시성 세마포어 가드 추가
- `src/app/page.dashboard/api.py`
  - `overview()` / `trade_preview()`에 short TTL cache 및 singleflight 추가
  - 대시보드 병목이 미장 화면 과부하로 번지는 현상 완화

## 검증 메모
- `wiz project build --project=main --clean` 성공
- 후속 일반 빌드 성공
- 로컬 US API 동시 요청(bootstrap/snapshot) 12회 기준 모두 200 확인
- public `https://stock8.seasonai.net/daytrade/us`, `https://stock8.seasonai.net/favicon.ico` 저중부하 동시 요청 200 확인
- 고부하 스트레스 후 프로세스에 MySQL 연결이 53개 남아 500으로 전이되는 현상 관찰 (`psutil.net_connections` 기준)
