# 7개 이슈 일괄 수정 (인증·수익률·Y축·1회차 체크·엔진)

- **ID**: 011
- **날짜**: 2026-05-08
- **유형**: 버그 수정

## 작업 요약

사용자가 보고한 7개 이슈 중 코드 수정으로 해결 가능한 5건을 수정했다.
이슈 3(네비 버튼 부족), 4(자동매매 꺼짐), 5(API 미연결)는 모두 인증 세션 미설정에서 비롯된 것으로,
request.ts의 `readyState:0` 처리 방식 수정으로 연쇄 해결된다.

## 원문 요청사항

```text
1. 총 수익률 -35,457% 이상값
2. 자산 추이 Y축 값 불일치
3. 네비 버튼 3개만 보임 (대시보드/무한매수/거래이력)
4. 무한매수 자동매매 초기화로 꺼짐
5. 무한매수 API 미연결
6. 무한매수 1회차 시드 < 전일종가 시 매수 차단 → 차단 완화 요청
7. Auth fallback session 에러 (readyState: 0) - 실제 원인
```

## 변경 파일 목록

### 1. `src/portal/season/libs/util/request.ts` (이슈 7 → 3, 4, 5 연쇄 해결)
- **변경**: Promise를 `resolve`만 있는 구조에서 `resolve/reject` 분리
- `readyState === 0` 또는 `status === 0`인 경우 `reject(new Error(...))` → auth.ts catch 블록이 제대로 동작하여 재시도 및 올바른 세션 설정
- HTTP 에러의 경우도 `reject(Error)` 처리 (이전에는 jqXHR 객체를 resolve로 반환하여 catch가 발동 안 됨)
- **효과**: `/auth/check` 네트워크 오류 시 fallback session `{ verified: 'unknown' }` 대신 정상 session 반환 → admin nav 버튼 표시, settings auto_trade 정상 로딩, API 연결 상태 정상 표시

### 2. `src/app/page.dashboard/api.py` (이슈 1, 2)
- **이슈 1 (총 수익률)**: `total_return` 분모를 `base_asset`(설정값 1,000,000원 고정)에서 `total_invested`(실제 투자금) 우선으로 변경.
  - `_return_denom = total_invested if total_invested > 0 else base_asset`
  - `realized_return`, `unrealized_return`도 동일 분모 적용
- **이슈 2 (Y축 불일치)**: `snapshot_to_krw()` 함수가 항상 raw 값을 그대로 반환하는 버그 수정.
  - DB 스냅샷 `total_asset`이 USD 단위로 저장된 경우 KRW 변환이 누락되어 Y축이 $25,000 → ₩25,000으로 표시되던 문제
  - `100,000 미만이면 USD로 판단 → exchange_rate 곱하기` 로직 추가

### 3. `src/portal/trading/model/struct/engine.py` (이슈 6)
- **변경**: 1회차 씨앗금 < 전일종가 시 완전 차단 → 최소 1주 진입 허용으로 완화
  - `order_qty == 0`이지만 `prev_close > 0`이면 `order_qty = 1`, `should_buy = True`
  - reason 메시지에 완화 정책 명시
