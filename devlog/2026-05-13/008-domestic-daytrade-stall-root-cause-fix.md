# 008. Domestic daytrade stall root cause fix

- Symptom: KS daytrade looked stopped during market hours.
- Finding: the worker was running, but BUY attempts were rejected by KIS with `주문가능금액을 초과 했습니다`.
- Finding: after the seed was lowered to 1,000,000 KRW, the high-price candidate was excluded, but the relaxed recommendation cache path crashed on `name 'seed' is not defined`.
- Finding: the source file had ROTATE candidate support, but the runtime `build`/`bundle` copy still had the older strict `trade_ready` gate. This caused candidates with acceptable rotation quality to be blocked by a single quality warning such as overfit gap.

Changes:

- Fixed `_recommendation_price_filter` to accept and persist `seed`.
- Synced `daytrade.py` from source to `build` and `bundle` so the active runtime uses automation grades and ROTATE candidates.
- Changed KS live BUY orders to default to an aggressive LIMIT order with a KIS orderable-amount preflight, instead of submitting market BUY orders that can require a larger collateral amount than the strategy budget estimate.
- Fixed BUY execution logging/return handling. BUY orders were updating position state but not returning `executed=True`, so auto-cycle summaries could say "check only" even after a live buy was accepted.
- Verified syntax with `python -m py_compile` across source, build, and bundle copies.

Operational note:

- A real fill is intentionally not forced from maintenance work. The next automatic worker tick should recompute recommendations using selection version `2026-05-13.2` and either submit a preflighted LIMIT order or log the exact orderable-amount block reason.
