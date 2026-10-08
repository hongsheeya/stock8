"""KIS domestic cash-order routing. No I/O, clock or account side effects.

Rules verified against KIS notice 26dfe350-eb72-48e5-8175-34eb27970f3e
(2026-09-09). Callers must provide same-day exchange eligibility evidence.
Unknown calendars/eligibility are not permission to trade extended sessions.
"""
import datetime
import math

KST = datetime.timezone(datetime.timedelta(hours=9))


def session(now, exchange='KRX'):
    if now.tzinfo is None:
        raise ValueError('Timezone-aware clock required')
    now = now.astimezone(KST)
    if exchange not in ('KRX', 'NXT'):
        raise ValueError('Explicit KRX or NXT required; implicit SOR is disabled')
    if now.weekday() >= 5:
        return 'CLOSED'
    t = now.hour * 3600 + now.minute * 60 + now.second
    if exchange == 'NXT':
        if 8*3600 <= t < 8*3600+50*60:
            return 'PRE'
        if 9*3600+30 <= t < 15*3600+20*60:
            return 'REGULAR'
        if 15*3600+40*60 <= t < 20*3600:
            return 'AFTER'
    else:
        if 9*3600 <= t < 15*3600+20*60:
            return 'REGULAR'
        if 15*3600+20*60 <= t < 15*3600+30*60:
            return 'CLOSING_AUCTION'
        if now.date() >= datetime.date(2026, 9, 14) and 16*3600 <= t < 20*3600:
            return 'AFTER'
    return 'CLOSED'


def route(now, exchange, order_type, price, qty, evidence=None):
    phase = session(now, exchange)
    if phase in ('CLOSED', 'CLOSING_AUCTION'):
        raise ValueError('현재 시장은 자동매매 주문 시간이 아닙니다: ' + phase)
    kind = str(order_type).upper()
    if kind not in ('LIMIT', 'MARKET'):
        raise ValueError('지원하지 않는 주문 유형')
    if not math.isfinite(float(qty)) or float(qty) != int(qty) or int(qty) <= 0:
        raise ValueError('주문 수량은 양의 정수여야 합니다')
    if kind == 'LIMIT' and (not math.isfinite(float(price)) or float(price) <= 0 or float(price) != int(price)):
        raise ValueError('지정가 가격은 양의 정수여야 합니다')
    extended = phase != 'REGULAR' or exchange == 'NXT'
    evidence = evidence or {}
    if extended:
        today = now.astimezone(KST).date().isoformat()
        if evidence.get('date') != today or evidence.get('open') is not True:
            raise ValueError('당일 개장일 확인이 필요합니다')
        if evidence.get('exchange') != exchange or evidence.get('eligible') is not True:
            raise ValueError('해당 시장의 종목 거래가능 여부를 확인하지 못했습니다')
        if evidence.get('halted') is not False:
            raise ValueError('거래정지 여부를 확인하지 못했습니다')
        if phase == 'AFTER' and exchange == 'KRX' and evidence.get('instrument') != 'STOCK':
            raise ValueError('KRX 애프터마켓 ETP/분류 미확인 종목은 주문하지 않습니다')
        if kind != 'LIMIT':
            raise ValueError('연장장에서는 명시적인 지정가만 허용합니다. 시장가를 임의 변환하지 않습니다')
    code = '01' if kind == 'MARKET' else '00'
    if phase == 'AFTER' and exchange == 'KRX':
        code = '41'
    if phase == 'PRE' and exchange == 'NXT':
        code = '27'  # GTP: unfilled remainder expires at the end of premarket.
    return {'exchange': exchange, 'session': phase, 'ord_dvsn': code,
            'price': 0 if kind == 'MARKET' else int(price), 'qty': int(qty)}


def cancel_route(exchange, ord_dvsn):
    # Original order metadata, never the current clock, determines cancellation.
    allowed = {'KRX': {'00', '01', '41'}, 'NXT': {'00', '27'}}
    if exchange not in allowed or ord_dvsn not in allowed[exchange]:
        raise ValueError('원주문 시장/주문 유형 확인이 필요합니다')
    return {'EXCG_ID_DVSN_CD': exchange, 'ORD_DVSN': ord_dvsn}


class MarketRules:
    session = staticmethod(session)
    route = staticmethod(route)
    cancel_route = staticmethod(cancel_route)


Model = MarketRules()
