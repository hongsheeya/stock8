# 단타 엔진 다중 기능 개선

- **ID**: 001
- **날짜**: 2026-04-28
- **유형**: 기능 추가 / 버그 수정

## 작업 요약
1. (FN-0428-0001) 미장 us_premarket 전략의 `gap_pct` 계산 버그 수정 - anchor 대신 prev_close 사용
2. (FN-0428-0002) 미장 자동매매 On/Off 토글 API 추가 (`us_toggle_auto`, `us_get_auto_status`)
3. (FN-0428-0003) 미장 전체 기능 국장 동등 구현 (`us_daily_log`, `us_manual_sell`, `us_auto_cycle`, `us_execute_exit_watch`)
4. (FN-0428-0004) 국장 장기보유 강제손절 로직 추가 - BUY 시 `first_buy_date` 저장, `execute_exit_watch`에 force-cut 루프
5. (FN-0428-0005) 미장 전략 3종 추가 (`us_breakout`, `us_pullback`, `us_vwap`) - STRATEGIES 등록 + 시그널 로직 구현

## 변경 파일 목록

### daytrade_engine.py
- `_signal_from_state()` us_premarket 블록: `gap_pct` 버그 수정 (anchor → prev_close)
- 초기 state 구조: `first_buy_date: ""` 추가
- BUY 실행 블록: `first_buy_date` 설정 + `_store_state` + `_invalidate_kis_cache` 추가 (기존 BUY는 state 저장 누락 버그 수정)
- SELL 완료 블록: `new_qty <= 0` 시 `first_buy_date = ""` 초기화
- `manual_sell()`: US market 지원 추가 (sell_order), 수수료 계산 US/KS 분리, exec_price 사용
- SELL_PARTIAL 처리: `buy1_used = True` 마킹 추가 (1차 익절 재진입 방지)
- `execute_exit_watch()`: 국장 장기보유 강제손절 루프 추가 (hold_days >= max_hold_days && pnl_pct < -force_cut_loss_pct)
- `_signal_from_state()`: `us_breakout`, `us_pullback`, `us_vwap` 진입 시그널 블록 추가
- `_signal_from_state()` 청산 블록: US 전략 공통 청산 로직 추가 (high_stop_pct, jackpot2, VWAP 이탈)
- 엔진 하단: `us_auto_enabled()`, `us_execute_exit_watch()`, `us_auto_cycle()` 메서드 추가

### daytrade.py
- `STRATEGIES`: `us_breakout`, `us_pullback`, `us_vwap` 항목 추가
- `DEFAULT_PROFILE`: `max_hold_days: 5`, `force_cut_loss_pct: 8.0` 추가
- `US_DEFAULT_PROFILE`: `breakout_volume_ratio: 3.0`, `min_change_pct: 5.0`, `min_prior_surge_pct: 10.0` 추가

### api.py (src/app/page.daytrade/api.py)
- `us_toggle_auto()` 추가: `us_daytrade_auto_enabled` 키 토글
- `us_get_auto_status()` 추가: 미장 자동매매 상태 조회
- `us_daily_log()` 추가: 미장 US 포지션 기준 일별 거래 일지
- `us_manual_sell()` 추가: 미장 즉시 시장가 매도
- `us_auto_cycle()` 추가: 미장 자동순환 (exit_watch + 신규 진입)
- `us_execute_exit_watch()` 추가: 미장 포지션 자동청산 감시
