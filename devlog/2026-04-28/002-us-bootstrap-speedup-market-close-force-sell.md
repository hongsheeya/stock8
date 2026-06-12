# 미장 부트스트랩 속도 개선 및 장마감 강제청산 로직 구현

- **ID**: 002
- **날짜**: 2026-04-28
- **유형**: 성능 개선 / 기능 추가

## 작업 요약
미장 단타 탭 로딩 시 20초 소요되던 지연을 해소하기 위해 `us_bootstrap`을 경량화하고 `us_live_status`에 12초 캐싱을 적용했다.
또한 국장/미장 모두 장 마감 임박 시 보유 포지션을 강제 청산하는 로직을 엔진에 추가했다.

## 성능 개선 상세

| 변경 전 | 변경 후 |
|---------|---------|
| `us_bootstrap` = `active_positions()` (KIS API ~5초) + `signal_status()` (yfinance ~15초) | `active_positions_from_state()` (DB only ~0.1초) + `signal_status` 제거 |
| `us_live_status` 캐시 없음 → 매 폴링마다 yfinance + KIS 재조회 | 12초 TTL 캐싱 + fallback 적용 |
| 프론트: bootstrap 완료 전까지 전체 대기 | bootstrap(빠름) 완료 → 즉시 화면 표시 → live_status 비동기 후행 |

## 변경 파일 목록

### daytrade_engine.py
- `_is_market_close_approaching(market)` 메서드 추가: 국장 KST 15:20~15:35, 미장 ET 15:40~16:05 감지
- `active_positions_from_state(market_filter)` 메서드 추가: KIS API 없이 state DB만 읽는 경량 포지션 조회
- `execute_exit_watch()` 내 "장마감 임박 강제청산" 루프 추가: 양 시장 공통, 포지션 전량 `manual_sell`

### api.py (page.daytrade)
- `us_bootstrap`: `active_positions()` → `active_positions_from_state(market_filter="US")` 교체, `signal_status()` 제거, `status=None` 반환
- `us_live_status`: 12초 TTL 캐싱 + degraded fallback 적용 (국장 `live_status`와 동일 패턴)

### view.ts (page.daytrade)
- `usBootstrap()`: 완료 후 `usLoadLiveStatus()` 비동기 후행 호출 추가 (await 없이 fire-and-forget)
