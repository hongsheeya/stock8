# 대시보드 무한매수 표시를 FireGate 권위 포트폴리오 기준으로 정렬

- **ID**: 001
- **날짜**: 2026-06-11
- **유형**: 버그 수정

## 작업 요약
대시보드 무한매수 영역이 로컬에서 별도로 관리하던 종목까지 섞어 보여주던 문제를 수정했다.
FireGate 브릿지가 연결된 경우에는 FireGate의 `infinitystock` 포트폴리오 심볼만 권위 원본으로 간주해 사이클/시작가능 종목/상태 카운트를 해당 범위로 제한하고, 강제 새로고침 시 원격 pull을 먼저 수행하도록 조정했다.

## 원문 요청사항
```text
무한매수 포트폴리오 꼬인거 같아. 우 사트에서 관리하는 사이클을 가져와야하는데 내가 따로 관리하는 포트폴리오를 불러와서 표시하고 있어
```

## 변경 파일 목록
- 대시보드 API
  - `src/app/page.dashboard/api.py`
    - FireGate 권위 포트폴리오 판별/심볼 추출/사이클 스코프 헬퍼 추가
    - 브릿지 연결 시 FireGate 포트폴리오 심볼만 무한매수 사이클과 watchlist에 반영
    - 강제 새로고침 시 FireGate pull 후 overview를 재계산하도록 수정
    - 응답에 `infinite_buy_cycles`를 명시적으로 포함
- 테스트
  - `tests/test_dashboard_accounting_regressions.py`
    - FireGate 권위 포트폴리오 필터링과 스코프된 상태 카운트 회귀 테스트 추가
- 작업 이력
  - `devlog.md`
    - 2026-06-11 작업 요약 행 추가
  - `devlog/2026-06-11/001-dashboard-firegate-authoritative-scope.md`
    - 상세 작업 기록 추가
