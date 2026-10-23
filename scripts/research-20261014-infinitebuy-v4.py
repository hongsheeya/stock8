"""Research only: daily replay of Stock8's FireGate v4 infinite-buy rules.

Uses the project's own decision and accounting functions (no reimplementation):
  * orders : Engine._firegate_v4_buy_decision / Engine._firegate_v4_sell_orders
             (engine.py), buying stops when floor(T) >= splits (calculate_buy_decision)
  * state  : firegate_bridge.apply_v4_transaction (T, avg, reverse mode) and
             _authoritative_cycle_state_from_portfolio (FireGate is authoritative)
Fills with daily OHLC (no intraday path):
  * first buy LIMIT (prev close +12%): fills at the open if open <= limit,
    else at the limit if the low reaches it
  * LOC buy  : fills at the close when close <= LOC price
  * LOC sell : fills at the close when close >= LOC price
  * LIMIT sell (+15% TQQQ / +20% others): fills at max(limit, open) if high >= limit
  Intraday limit sells are booked before the closing LOC orders.
Commission 0.25% per side (engine default). A completed cycle restarts the
next session with the same fixed seed (engine auto-restart, no compounding).
The 2026-10-13 daily bar was downloaded mid-session and is excluded.
"""
import argparse
import csv
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import research_20261014_lib as L  # noqa: E402

SEEDS = {'SOXL': 15000.0, 'TQQQ': 10000.0}
FEE = 0.0025


def load_daily(symbol, last_date='2026-10-12'):
    rows = []
    with open(L.BARS / 'daily' / f'{symbol}.csv', newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            day = r['timestamp'][:10]
            if day > last_date:
                continue
            o, h, l, c = (float(r[k]) for k in ('open', 'high', 'low', 'close'))
            if min(o, h, l, c) > 0:
                rows.append({'date': day, 'open': o, 'high': h, 'low': l, 'close': c})
    return rows


class V4Sim:
    def __init__(self, symbol, seed, splits=20, fee=FEE, engine=None, fg=None):
        self.symbol, self.seed, self.splits, self.fee = symbol, seed, splits, fee
        self.engine, self.fg = engine, fg
        self.cash = seed           # account cash dedicated to this symbol
        self.realized = 0.0
        self.cycles = []
        self._new_portfolio(None)

    def _new_portfolio(self, date):
        self.p = {'seed': self.seed, 'divisionDate': self.splits, 'holdingQty': 0, 'avgPrice': 0,
                  'totalBuy': 0, 'totalSell': 0, 'tValue': 0, 'reverseMode': False, 'isRunning': True,
                  'symbol': self.symbol, 'ticker': self.symbol}
        self.cycle_start = date
        self.cycle_cost = 0.0
        self.cycle_proceeds = 0.0
        self.max_t = 0.0
        self.cycle_peak_invest = 0.0

    def _cycle(self):
        c = self.fg._authoritative_cycle_state_from_portfolio(self.p) or {}
        c.update(_firegate_authoritative=True, symbol=self.symbol)
        c['remaining_investment'] = max(self.seed - (self.p['totalBuy'] - self.p['totalSell']), 0)
        return c

    def _tx(self, kind, price, qty, date):
        price = round(price, 2)
        commission = round(price * qty * self.fee, 2)
        if kind == 'buy':
            self.cash -= price * qty + commission
            self.cycle_cost += price * qty + commission
        else:
            self.cash += price * qty - commission
            self.cycle_proceeds += price * qty - commission
        self.p = self.fg.apply_v4_transaction(self.p, {'type': kind, 'price': price, 'size': qty,
                                                       'commission': commission, 'date': date})
        self.max_t = max(self.max_t, float(self.p.get('tValue', 0)))
        self.cycle_peak_invest = max(self.cycle_peak_invest, self.p['totalBuy'] - self.p['totalSell'])

    def step(self, prev, bar):
        date = bar['date']
        if self.cycle_start is None:
            self.cycle_start = date
        cycle = self._cycle()
        qty = int(self.p.get('holdingQty', 0))
        sells = self.engine._firegate_v4_sell_orders(cycle) if qty > 0 else []
        buys = []
        if int(math.floor(float(self.p.get('tValue', 0)))) < self.splits:
            dec = self.engine._firegate_v4_buy_decision(cycle, prev['close'], 0)
            buys = dec.get('buy_orders', []) if dec.get('should_buy') else []
        # 1) intraday limit sells
        for o in sells:
            if o['order_type'] == 'LIMIT' and bar['high'] >= o['price'] and int(self.p['holdingQty']) > 0:
                q = min(o['order_qty'], int(self.p['holdingQty']))
                self._tx('sell', max(o['price'], bar['open']), q, date)
        # 1b) first-round limit buy executes at/after the open
        for o in buys:
            if o.get('order_type') == 'LIMIT':
                if bar['open'] <= o['loc_price']:
                    self._tx('buy', bar['open'], int(o['order_qty']), date)
                elif bar['low'] <= o['loc_price']:
                    self._tx('buy', o['loc_price'], int(o['order_qty']), date)
        # 2) closing LOC sells, then LOC buys
        for o in sells:
            if o['order_type'] == 'LOC' and bar['close'] >= o['price'] and int(self.p['holdingQty']) > 0:
                q = min(o['order_qty'], int(self.p['holdingQty']))
                self._tx('sell', bar['close'], q, date)
        for o in buys:
            if o.get('order_type', 'LOC') == 'LOC' and bar['close'] <= o['loc_price'] and int(o['order_qty']) > 0:
                self._tx('buy', bar['close'], int(o['order_qty']), date)
        # cycle completion -> restart next session with the fixed seed
        if int(self.p['holdingQty']) == 0 and self.p['totalBuy'] > 0:
            pnl = self.cycle_proceeds - self.cycle_cost
            self.realized += pnl
            self.cycles.append({'start': self.cycle_start, 'end': date, 'pnl': round(pnl, 2),
                                'ret_on_seed_pct': round(pnl / self.seed * 100, 2), 'max_t': round(self.max_t, 2),
                                'peak_invested': round(self.cycle_peak_invest, 2)})
            self._new_portfolio(None)
        holding = int(self.p['holdingQty'])
        return self.cash + holding * bar['close'] * (1 - self.fee)


def run(symbol, start, end, splits=20, fee=FEE):
    engine_mod = L._load('stock8_engine_research', 'portal/trading/model/struct/engine.py')
    fg = L._load('stock8_firegate_research', 'portal/trading/model/struct/firegate_bridge.py')
    engine = engine_mod.Engine(L.StructStub({}))
    bars = [b for b in load_daily(symbol) if b['date'] >= start and b['date'] <= end]
    hist = load_daily(symbol)
    prev_idx = {b['date']: i for i, b in enumerate(hist)}
    sim = V4Sim(symbol, SEEDS.get(symbol, 10000.0), splits=splits, fee=fee, engine=engine, fg=fg)
    equity = []
    for b in bars:
        i = prev_idx[b['date']]
        if i == 0:
            continue
        equity.append((b['date'], sim.step(hist[i - 1], b)))
    first, last = bars[0], bars[-1]
    seed = sim.seed
    bh_qty = seed / first['open']
    bh_curve = [seed / first['open'] * b['close'] for b in bars]
    open_cycle = None
    if int(sim.p['holdingQty']) > 0:
        open_cycle = {'start': sim.cycle_start, 't_value': sim.p['tValue'], 'qty': sim.p['holdingQty'],
                      'avg': sim.p['avgPrice'], 'unrealized_pct_of_seed': round(
                          (int(sim.p['holdingQty']) * last['close'] - (sim.p['totalBuy'] - sim.p['totalSell'])) / seed * 100, 2),
                      'invested': round(sim.p['totalBuy'] - sim.p['totalSell'], 2)}
    return {
        'symbol': symbol, 'start': first['date'], 'end': last['date'], 'seed': seed, 'splits': splits, 'fee': fee,
        'final_equity': round(equity[-1][1], 2), 'return_pct': round((equity[-1][1] / seed - 1) * 100, 2),
        'mdd_pct': L.max_drawdown_pct([e for _, e in equity]),
        'completed_cycles': len(sim.cycles), 'cycles': sim.cycles, 'open_cycle': open_cycle,
        'buy_hold_return_pct': round((bh_qty * last['close'] / seed - 1) * 100, 2),
        'buy_hold_mdd_pct': L.max_drawdown_pct(bh_curve),
        'reverse_mode_entered': any(c['max_t'] > splits - 1 for c in sim.cycles) or (open_cycle is not None and float(sim.p['tValue']) > splits - 1),
        'equity_curve': [(d, round(e, 2)) for d, e in equity],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--symbols', nargs='*', default=['SOXL', 'TQQQ'])
    args = ap.parse_args()
    windows = {
        'last_1y': ('2025-10-14', '2026-10-12'),
        'last_3y': ('2023-10-13', '2026-10-12'),
        'since_2018': ('2018-01-02', '2026-10-12'),
        'bear_2022': ('2021-11-01', '2023-06-30'),
    }
    out = {}
    for sym in args.symbols:
        for name, (s, e) in windows.items():
            for fee in (FEE, 0.0007):
                res = run(sym, s, e, fee=fee)
                key = f'{sym}_{name}_fee{fee}'
                out[key] = res
                brief = {k: v for k, v in res.items() if k not in ('cycles', 'equity_curve')}
                print(key, json.dumps(brief), flush=True)
    L.write_json('infinitebuy_v4_replay.json', out)


if __name__ == '__main__':
    main()
