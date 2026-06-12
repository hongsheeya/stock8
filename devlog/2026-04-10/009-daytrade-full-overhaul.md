# 단타 연구실 전면 개편 — 학습·추천·실행 통합

- **ID**: 009
- **날짜**: 2026-04-10
- **유형**: 기능 추가 + 버그 수정 + UI 리팩토링

## 작업 요약
단타 연구실의 5가지 핵심 문제를 전면 해결:
1. 실행 버튼 "신호 없음" → force 매수 옵션 추가, BUY1 강제 진입 가능
2. 모델 학습 0% → 시드 최소값(100만원) 강제, 그리드 탐색 확장, 학습 정상 동작
3. UI 과도 복잡 → 3단 구조(헤더+시그널+랭킹)로 단순화, 불필요 패널 제거
4. 종목 추천 없음 → recommend() 메서드 + 캐시 기능, 페이지 진입 시 즉시 추천
5. API 연동 미검증 → KIS 연결 확인 기능, 실제 주문 성공 검증 (주문번호 확인)

## 변경 파일 목록

### 백엔드 모델
- `src/portal/trading/model/struct/daytrade.py` — MIN_SEED 추가, 그리드 확장(-0.3~-0.7), recommend()/latest_recommendation()/_save_recommendation() 추가, auto_train에 캐시 저장
- `src/portal/trading/model/struct/daytrade_engine.py` — execute_live에 force 파라미터 추가, check_kis_connection() 추가

### API
- `src/app/page.daytrade/api.py` — 전면 재작성: bootstrap(추천 캐시+KIS 상태), recommend(), train_symbol(), live_status(), execute_live(force), search_symbols()

### 프론트엔드
- `src/app/page.daytrade/view.ts` — 전면 재작성: runRecommend(), trainSymbol(), executeLive(force), toggleSearch()
- `src/app/page.daytrade/view.pug` — 전면 재설계: 3단 단순 UI, 추천 안내 카드, 시그널 카드, 실행 버튼(시그널 기반 + 강제 매수), 랭킹 테이블, KIS 연동 상태 표시

### 검증 결과
- bootstrap: 200 OK, KIS 연동 확인
- recommend: 200 OK, 10종목 학습 완료, 성공률 70%, 1등 두산에너빌리티(0.15%, 80%)
- execute_live(force=true): 실제 KIS 주문 성공 (주문번호 0021677700, 두산에너 3주)
- live_status: 포지션 추적 정상 (3주, buy1_used=True)
