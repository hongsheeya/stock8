# 미장 단타 검증형 랭킹 강화 및 시드 배정 저장 지원

- **ID**: 015
- **날짜**: 2026-05-06
- **유형**: 기능 추가

## 작업 요약
미장 단타 연구 모델에서 전략별 시뮬레이션을 분리하고, 검증 수익·견고성·과최적화 간극을 반영한 랭킹 기준으로 재정렬했다.
동시에 미장 전용 화면에서 요청 시드를 저장하고 실효 시드·잔여 시드·종목당 시드를 바로 확인할 수 있도록 API와 UI를 보강했다.

## 원문 요청사항
```text
아니 그러면 좋은 매매 알고리즘 빨리 찾아와서 검증해. 그리고 미장 시드 배정할 수 있게 해줘
```

## 변경 파일 목록
### 모델/런타임 랭킹 강화
- `src/portal/trading/model/struct/daytrade.py`
  - `us_breakout`, `us_pullback`, `us_vwap` 전략을 공용 시뮬레이터 대신 전략별 시뮬레이터로 분리
  - 검증 수익률, 검증 승률, 견고성, 과최적화 간극, trade-ready 상태를 반영하도록 미장 자동학습 점수식과 품질 가드 강화
- `build/src/model/portal/trading/struct/daytrade.py`
  - 빌드 런타임에 동일한 미장 전략 분기/랭킹 로직 반영
- `bundle/src/model/portal/trading/struct/daytrade.py`
  - 번들 런타임에 동일한 미장 전략 분기/랭킹 로직 반영

### 미장 API/화면 시드 배정 지원
- `src/app/page.daytrade.us/api.py`
  - `us_bootstrap`에 저장형 시드 반영(`persist_seed`)과 예산 상태(`budget_status`) 응답 추가
  - `us_model_ranking`에 검증 수익·견고성·과최적화·대표 종목 메타데이터 추가
- `build/src/app/page.daytrade.us/api.py`
  - 빌드 런타임 API에 동일한 응답 필드 반영
- `bundle/src/app/page.daytrade.us/api.py`
  - 번들 런타임 API에 동일한 응답 필드 반영
- `src/app/page.daytrade.us/view.ts`
  - 미장 시드 저장 동작과 예산 상태/추천 조합 상태 관리 추가
- `src/app/page.daytrade.us/view.html`
  - 시드 저장 버튼, 시드 배정 상태 패널, 검증 기준 추천 조합/대표 종목 표시 추가
- `build/src/app/page.daytrade.us/page.daytrade.us.component.ts`
  - 빌드 런타임 컴포넌트에 동일한 상태 관리 추가
- `build/src/app/page.daytrade.us/view.html`
  - 빌드 런타임 템플릿에 동일한 시드 저장/검증 메타 표시 추가

### 검증 메모
- 터미널 샘플 검증으로 `TQQQ`, `SOXL`, `TSLL`, `NVDA`, `PLTR`, `RKLB` 기준 10일/5분봉 백테스트를 수행함
- 샘플 결과상 `us_premarket`만 유의미한 비영(非0) 검증 수익이 관측되었고, `SOXL`에서 검증 수익 약 0.35%, 견고성 4.48이 확인됨
- 나머지 전략은 이번 샘플에서 0에 가까운 결과가 많아, 새 랭킹/품질 가드가 실거래 비권장 전략을 상단 추천에서 배제하도록 보강함
