"""Deterministic PAPER-only selective strategies. No I/O and no order sending."""
import datetime
import math

KST = datetime.timezone(datetime.timedelta(hours=9))
IDS = ('paper_selective_breakout', 'paper_selective_pullback')


def timestamp(value):
    parsed = value if isinstance(value, datetime.datetime) else datetime.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return parsed.replace(tzinfo=KST) if parsed.tzinfo is None else parsed.astimezone(KST)


class SelectiveStrategy:
    @staticmethod
    def snapshot(sessions, now):
        now = timestamp(now)
        fast = slow = previous = gain = loss = None
        previous_rsi = 50
        deltas = []
        count = 0
        latest = None
        last_ts = None
        for session in sessions:
            history = []
            pv = volume = 0
            for row in session.get('bars', []):
                ts = timestamp(row['timestamp'])
                if ts + datetime.timedelta(minutes=5) > now:
                    continue
                if last_ts is not None and ts <= last_ts:
                    raise ValueError('분봉 시간이 중복되거나 역순입니다.')
                if ts.minute % 5 or ts.second:
                    raise ValueError('확정된 5분봉이 필요합니다.')
                last_ts = ts
                o,h,l,c,v = (float(row[k]) for k in ('open','high','low','close','volume'))
                if not all(math.isfinite(x) for x in (o,h,l,c,v)) or min(o,h,l,c) <= 0 or v < 0 or not l <= min(o,c) <= max(o,c) <= h:
                    raise ValueError('분봉 가격 또는 거래량이 올바르지 않습니다.')
                old_fast = fast
                fast = c if fast is None else fast + 2/21*(c-fast)
                slow = c if slow is None else slow + 2/51*(c-slow)
                if previous is not None:
                    d = c-previous
                    deltas.append(d)
                    if len(deltas) == 14:
                        gain = sum(max(x,0) for x in deltas)/14
                        loss = sum(max(-x,0) for x in deltas)/14
                    elif len(deltas) > 14:
                        gain = (gain*13+max(d,0))/14
                        loss = (loss*13+max(-d,0))/14
                rsi = 50 if gain is None or gain == loss == 0 else (100 if loss == 0 else 100-100/(1+gain/loss))
                pv += c*max(v,1)
                volume += max(v,1)
                vwap = pv/volume
                mean_volume = sum(b['volume'] for b in history[-5:])/5 if len(history)>=5 else 0
                prior = history[-1] if history else None
                common = bool(count >= 50 and len(history)>=20 and '09:30' <= ts.strftime('%H:%M') <= '13:30'
                              and c > fast > slow and fast > old_fast and c >= vwap
                              and 55 <= rsi <= 70 and rsi > previous_rsi
                              and mean_volume > 0 and v >= mean_volume*1.5)
                latest = dict(row, timestamp=ts.isoformat(), ema20=fast, ema50=slow,
                              rsi14=rsi, vwap=vwap, volume_surge_ratio=v/mean_volume if mean_volume else 0,
                              common=common,
                              breakout=bool(history and c > max(x['high'] for x in history[-20:])),
                              pullback=bool(prior and prior['close'] <= prior['ema20'] and c > fast))
                history.append(latest)
                previous, previous_rsi = c, rsi
                count += 1
        if latest is None:
            raise ValueError('확정 분봉이 없습니다.')
        age = (now-timestamp(latest['timestamp'])-datetime.timedelta(minutes=5)).total_seconds()
        if age < 0 or age > 600 or timestamp(latest['timestamp']).date() != now.date():
            raise ValueError('확정 분봉이 오래되어 주문을 차단했습니다.')
        return latest

    @staticmethod
    def decide(strategy_id, bar, state, now, budget, allow_buy=True):
        if strategy_id not in IDS:
            raise ValueError('지원하지 않는 모의 전략입니다.')
        now = timestamp(now)
        signal = dict(action='HOLD', order_qty=0, reason='추세·거래량·진입 조건 대기',
                      strategy_id=strategy_id, signal_bar=bar['timestamp'], current_price=float(bar['close']))
        if state.get('pending_buy_order_no') or state.get('pending_sell_order_no'):
            return dict(signal, reason='미체결 주문 확인 중: 중복 주문 금지')
        if state.get('broker_unmanaged_position'):
            return dict(signal, reason='개인 보유 종목: 전략이 관리하지 않습니다.')
        orders = state.get('orders', [])
        quantity = int(state.get('position_qty',0))
        price = float(bar['close'])
        if quantity > 0:
            owned = sum((1 if str(o.get('action','')).startswith('BUY') else -1)*int(o.get('filled_qty',0))
                        for o in orders if o.get('strategy_id') == strategy_id and str(o.get('action','')).startswith(('BUY','SELL')))
            if owned != quantity:
                return dict(signal, reason='전략 체결 수량과 보유 수량 불일치: 개인 보유 보호')
            avg = float(state.get('avg_price',0))
            buys = [o for o in orders if o.get('strategy_id') == strategy_id and str(o.get('action','')).startswith('BUY') and int(o.get('filled_qty',0))>0]
            if avg <= 0 or not buys:
                return dict(signal, reason='체결 원가/진입시각 확인 필요')
            # Conservative research costs, not a claim of the broker fee tariff.
            net_pct = (price*.9978/(avg*1.0004)-1)*100
            opened = timestamp(buys[-1]['timestamp'])
            reason = ('손절 -1% 조건' if net_pct <= -1 else
                      '목표 순수익 +2.5% 조건' if net_pct >= 2.5 else
                      '최대 보유 90분 경과' if (now-opened).total_seconds() >= 5400 else
                      '정규장 마감 전 청산' if now.strftime('%H:%M') >= '15:15' else '')
            if reason:
                return dict(signal, action='SELL_STOP_LOSS' if net_pct <= -1 else 'SELL_FULL',
                            order_qty=quantity, reason=reason, net_pnl_pct=net_pct)
            return dict(signal, reason='전략 보유분 감시', net_pnl_pct=net_pct)
        if not allow_buy:
            return dict(signal, reason='신규 진입 비활성')
        for order in orders:
            if str(order.get('action','')).startswith('BUY') and timestamp(order['timestamp']).date() == now.date():
                return dict(signal, reason='종목별 하루 1회 진입 제한')
        trigger = bar['breakout'] if strategy_id.endswith('breakout') else bar['pullback']
        if bar['common'] and trigger:
            qty = int(max(0,float(budget))/(price*1.0004))
            if qty > 0:
                return dict(signal, action='BUY1', order_qty=qty,
                            reason='거래량 동반 20봉 고점 돌파' if strategy_id.endswith('breakout') else '상승 추세 EMA20 재돌파')
            return dict(signal, reason='비용 포함 주문 가능 예산 부족')
        return signal


Model = SelectiveStrategy
