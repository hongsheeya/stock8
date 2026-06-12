# 미장 단타 500 에러 및 파일 디스크립터 과다 사용 완화

- **ID**: 010
- **날짜**: 2026-05-11
- **유형**: 버그 수정

## 작업 요약
방금 미장 단타 화면 통일 작업 이후 `/daytrade/us` 진입 시 API들이 500으로 실패하던 문제를 재현했다. 원인은 미장 페이지가 초기 렌더 직후 여러 API를 병렬 호출하면서 `wiz.model("struct")`와 `portal/trading/struct/daytrade_engine` 로딩이 겹쳐 `Too many open files`가 발생한 것이었다. 트레이딩 Struct의 워커 초기화 경로를 지연 로딩으로 줄이고, 미장 페이지 요청을 순차화해 500이 재발하지 않도록 수정했다.

## 원문 요청사항
```text
Failed to load resource: the server responded with a status of 500 ()Understand this error
us:1  Failed to load resource: the server responded with a status of 500 ()
방금 작업 이후로 500에러 떴어. 원인 찾아서 해결해
```

## 변경 파일 목록
### 백엔드
- `src/portal/trading/model/struct.py`
  - `_ensure_background_worker()`가 요청마다 `daytrade_engine` 파일을 다시 열지 않도록 워커가 살아있으면 기존 `engine_id`를 재사용하도록 변경
  - `_daytrade_engine_model()` 헬퍼를 추가해 `daytrade_engine` 모델 로딩을 지연 처리
- `src/app/page.daytrade.us/api.py`
  - `_get_struct()`에 프로세스 전역 Struct 캐시를 추가해 `wiz.model("struct")` 재로딩 빈도를 낮춤

### 프론트엔드
- `src/app/page.daytrade.us/view.ts`
  - 초기 백그라운드 로드를 병렬 `Promise.all()`에서 순차 호출로 변경
  - 심볼 선택, 시드 저장, 자동매매 토글 후 재조회도 순차화
  - 초기 백그라운드 타이머에 소폭 지연을 주어 요청 폭주를 방지

## 원인 분석
- 재현 시 `/wiz/api/page.daytrade.us/us_bootstrap` 등 모든 초기 API가 실패
- 서버 응답 본문 기준 실제 오류 메시지:
  - `Package 'trading' load failed: [Errno 24] Too many open files: '/mnt/data/wiz/project/main/bundle/src/model/portal/trading/struct/daytrade_engine.py'`
- 즉, 프런트 디자인 변경 자체가 아니라 **초기 요청 패턴 증가 + 트레이딩 Struct의 과도한 모델 파일 재오픈** 조합이 문제였다.

## 검증
- `wiz project build --project=main` 일반 빌드 성공
- 인증 세션으로 아래 API 재검증
  - `us_bootstrap`
  - `us_live_status`
  - `us_daily_log`
  - `us_verify_runtime`
  - `us_model_ranking`
  - `us_search_symbols`
- 병렬 5개 동시 호출로도 모두 200 응답 확인
