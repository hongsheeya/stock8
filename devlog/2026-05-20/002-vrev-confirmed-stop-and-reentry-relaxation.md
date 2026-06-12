# 국장 vrev 얕은 손절 및 재진입 차단 완화

- **ID**: 002
- **날짜**: 2026-05-20
- **유형**: 전략 수정

## 작업 요약
국장 `vrev`가 -1.4% 고정 자동손절에 너무 쉽게 걸리고, 손절 뒤 당일 재진입을 막아 반등을 놓치는 문제를 수정했다.
기존에는 기본 프로필과 리스크/리워드 보정 설정이 모두 손절폭을 1.4% 근처로 묶고 있었고, DB 설정의 `daytrade_ks_rr_max_stop_loss_pct=1.4`가 코드 기본값보다 우선 적용되고 있었다.

## 변경 파일 목록
- `src/portal/trading/model/struct/daytrade.py`
  - 국장 기본 자동손절폭을 1.4%에서 2.4%로 확대
  - 손절 후 당일 재진입 영구 차단 기본값을 비활성화
- `src/portal/trading/model/struct/daytrade_engine.py`
  - 국장 `vrev` 손절폭 보정 로직을 최소 2.4%, 상한 2.8% 기준으로 변경
  - 자동손절선 터치 시 즉시 매도하지 않고 장초반 유예, 최소 보유시간, 지속 이탈 시간, VWAP/이평/RSI 약세 확인을 거친 뒤 매도
  - 하드 손절은 -3.0% 기준으로 즉시 허용
  - 손절 후 당일 재진입 영구 차단을 설정 기반으로 끄고 기본 쿨다운을 900초로 단축
  - 장초반/당일 손절 누적 신규진입 중단 기준을 너무 빠르게 잠기지 않도록 완화

## 실행 설정 반영
- `daytrade_ks_rr_min_stop_loss_pct=2.4`
- `daytrade_ks_rr_max_stop_loss_pct=2.8`
- `daytrade_ks_vrev_hard_stop_loss_pct=3.0`
- `daytrade_vrev_soft_stop_confirm_minutes=6`
- `daytrade_vrev_min_hold_before_stop_minutes=8`
- `daytrade_vrev_opening_stop_grace_minutes=12`
- `daytrade_stop_reentry_same_day_block=false`
- `daytrade_stop_reentry_cooldown_sec=900`
- `daytrade_probe_entry_enabled=false`
- `daytrade_daily_stop_loss_halt_count=3`
- `daytrade_opening_stop_halt_count=2`
- `daytrade_opening_stop_halt_minutes=20`

## 검증
- `python -m py_compile src/portal/trading/model/struct/daytrade.py src/portal/trading/model/struct/daytrade_engine.py`
