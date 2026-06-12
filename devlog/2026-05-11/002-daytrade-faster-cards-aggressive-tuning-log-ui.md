# 단타 카드 빠른 반영, 적극 운용 튜닝, 운영로그 가독성 개선

- **ID**: 002
- **날짜**: 2026-05-11
- **유형**: 기능 추가

## 작업 요약
국내 단타 화면에서 진행 중 종목 카드가 `live_status` 완료를 기다리며 늦게 반영되던 문제를 분리된 빠른 스냅샷 API와 5초 폴링으로 개선했다.
동시에 V-REV 기본 프로파일과 자동순환 후보 기준을 소폭 완화해 더 적극적으로 진입/청산이 이뤄지도록 조정하고, 운영로그 UI를 일반 사용자가 읽기 쉬운 알림형 카드로 재구성했다.

## 원문 요청사항
```text
1. 진행중인 단타 종목 표시해주는 카드 반영이 너무 느려
2. 조금 더 적극적으로 매매 진행해
3. 운영로그 조금 더 일반 사용자한테 보기 편하게 만들어줘
```

## 변경 파일 목록
### 빠른 진행중 종목 카드 반영
- `src/app/page.daytrade/api.py`
  - `active_positions_snapshot()` API 추가
  - 국내 진행중 종목의 빠른 현재가 스냅샷/호가 캐시 헬퍼 추가
  - `bootstrap()`, `live_status()`에서 빠른 카드용 스냅샷 경로 사용
- `src/app/page.daytrade/view.ts`
  - 5초 간격 빠른 포지션 카드 폴링 추가
  - 선택 종목 상세 패널과 카드 현재가/손익 동기화 로직 추가
- `src/app/page.daytrade/view.pug`
  - 진행 중 카드에 빠른 반영 안내 및 갱신 시각 표시 추가

### 조금 더 적극적인 단타 운용
- `src/portal/trading/model/struct/daytrade.py`
  - 국내 V-REV 기본 프로파일을 약간 더 공격적으로 조정
  - 진입 트리거, 익절 기준, 쿨다운, 미세익절 보류 기준 완화
- `src/portal/trading/model/struct/daytrade_engine.py`
  - 자동순환 후보 최소 변동성 기준 기본값 완화

### 운영로그 가독성 개선
- `src/app/page.daytrade/view.ts`
  - 로그 레벨/제목/설명/배지/메타 텍스트를 사용자 친화적으로 변환하는 헬퍼 추가
- `src/app/page.daytrade/view.pug`
  - 운영/안전 로그를 “자동매매 알림판” 형태의 카드 UI로 재구성

### 검증
- 클린 빌드 수행 (`wiz project build --clean true`)
- 수정 파일 오류 검사 통과
- `active_positions_snapshot` / `live_status` API 실호출 검증 통과
