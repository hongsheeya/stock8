# 단타 브리핑 접기·랭킹 문구 복구·총자산 정합 보정

- **ID**: 008
- **날짜**: 2026-05-11
- **유형**: 버그 수정

## 작업 요약
단타연구실 화면에 자동매매 브리핑 접기/펼치기를 추가하고, 랭킹 보조 문구가 비어 보이던 경우를 프런트 fallback 문구로 복구했다. 또한 브리핑 문구를 현재가·진입가·목표가 중심으로 더 구체화하고, 단타연구실과 대시보드의 총자산이 동일한 엔진 예산 기준으로 보이도록 정렬했다.

## 원문 요청사항
```text
1. 실시간 시그널(자동매매 브리핑) 접을 수 있는 기능 추가
2. 종목랭킹에 글들 사라졌어
3. 브리핑에 모호하게 원인 적어두지 말고 현재 금액 얼마고 얼마에 진입한다 이런것도 적어줘
4. 단타연구실에 있는 총자산이랑 대시보드에 있는 총자산이랑 다르면 어떡하냐
```

## 변경 파일 목록
### 프런트엔드
- `src/app/page.daytrade/view.pug`
  - 자동매매 브리핑 접기/펼치기 버튼과 접힘 상태 안내 문구를 추가했다.
  - 총자산 카드 아래에 총자산 기준 문구를 표시하도록 반영했다.
  - 종목랭킹 보조 문구 영역이 다시 보이도록 템플릿 구조를 정리했다.
- `src/app/page.daytrade/view.ts`
  - `briefingCollapsed` 상태와 토글 핸들러를 추가했다.
  - 브리핑/런타임 설명 문구에 현재가, 진입가, 목표가, 예상 수량 등 구체 수치를 넣도록 보강했다.
  - 랭킹 설명 필드가 비어 있을 때 전략/가격 기반 fallback 문구를 생성하도록 보완했다.
  - 총자산 표시는 `total_asset_krw`, `direct_total_asset_krw`, summary/fallback 중 최대값을 사용하도록 안전장치를 추가했다.

### 백엔드 API
- `src/app/page.daytrade/api.py`
  - 워커 캐시와 합쳐진 예산 상태에서 총자산 후보값을 정규화하는 `_normalize_budget_total_asset()`를 추가했다.
  - bootstrap/live_status 응답이 동일한 총자산 기준을 쓰도록 보정했다.
- `src/app/page.dashboard/api.py`
  - 대시보드 overview 총자산을 원화 출금가능액 + 국내평가 + 해외현금 + 해외평가 기준으로 계산하도록 보정했다.
  - 마지막에 단타 엔진의 예산 캐시를 우선 사용해 단타연구실과 동일한 총자산 값을 내리도록 맞췄다.

### 엔진/모델
- `src/portal/trading/model/struct/daytrade_engine.py`
  - 잔고 캐시에 `direct_total_asset_krw`, `usd_cash_balance_krw` 등을 포함하도록 확장했다.
  - 총자산 후보값을 비교할 수 있도록 계산 경로를 보강했다.
  - 실시간 강제 갱신이 새 캐시 키를 비우도록 `_invalidate_kis_cache()`를 수정했다.

## 검증
- `wiz project build --project=main`
- `wiz project build --project=main --clean`
- 실 API 확인 결과
  - 단타 bootstrap: `1887262.0`, `direct(krw+domestic_eval+usd_cash+usd_eval)`
  - 단타 live_status: `1887262.0`, `direct(krw+domestic_eval+usd_cash+usd_eval)`
  - 대시보드 overview: `1887262.0`, `direct(krw+domestic_eval+usd_cash+usd_eval)`
