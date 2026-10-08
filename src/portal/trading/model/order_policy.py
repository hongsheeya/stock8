"""Fresh, account-scoped authorization checked at the broker boundary."""
import contextvars
import hashlib
import inspect
import json
import os
import re
import sys
import threading

if not hasattr(sys, '_stock8_order_policy_context'):
    sys._stock8_order_policy_context = contextvars.ContextVar('stock8_order_policy', default=('', ''))
    sys._stock8_order_policy_lock = threading.RLock()
CONTEXT = sys._stock8_order_policy_context
LOCK = sys._stock8_order_policy_lock
WARNING_VERSION = 'live-strategy-locks-v1'
LANES = ('infinite_buy', 'daytrade_ks', 'daytrade_us')

def symbol_key(value):
    value = str(value or '').strip().upper()
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9.\-]{0,19}', value):
        raise ValueError('올바른 종목코드를 입력하세요.')
    return value

class BoundBroker:
    def __init__(self, broker, lane):
        self._broker, self._lane = broker, lane

    def __getattr__(self, name):
        value = getattr(self._broker, name)
        if not callable(value):
            return value
        def call(*args, **kwargs):
            symbol = ''
            try:
                symbol = inspect.signature(value).bind_partial(*args, **kwargs).arguments.get('symbol', '')
            except (ValueError, TypeError):
                pass
            lane = self._lane
            if lane == 'daytrade':
                lane = 'daytrade_ks' if 'domestic' in name else 'daytrade_us'
            if lane.startswith('daytrade') and str(symbol).strip().upper() == 'SOXL' and name.startswith(('buy_', 'sell_', 'cancel_', 'modify_')):
                raise RuntimeError('SOXL은 무한매수 전용입니다. 단타 매수·매도·정정·취소를 차단합니다.')
            token = CONTEXT.set((lane, symbol))
            try:
                return value(*args, **kwargs)
            finally:
                CONTEXT.reset(token)
        return call

class Policy:
    def daytrade_allowed(self):
        try:
            uid = self.struct._current_user_id()
            return bool(uid and self.struct._current_user_is_admin(uid))
        except Exception:
            return False

    def __init__(self, struct):
        self.struct = struct
        self.live = os.environ.get('TRADING_MODE', 'PAPER').upper() == 'LIVE'

    def _key(self):
        broker = self.struct.broker_api
        account = str(getattr(broker, 'account_no', '') or '').strip()
        if not account:
            raise ValueError('먼저 현재 계정의 증권사 API와 계좌번호를 설정하세요.')
        identity = str(self.struct.broker_provider) + ':' + account
        return 'order_policy_v1:' + hashlib.sha256(identity.encode()).hexdigest()[:40]

    def read(self):
        row = self.struct.db('trading_config').get(key=self._key())
        if not row:
            return {'infinite_buy': False, 'daytrade': False, 'daytrade_ks': False, 'daytrade_us': False, 'symbols': {}}
        state = json.loads(row['value'])
        if not isinstance(state, dict) or not isinstance(state.get('symbols'), dict):
            raise RuntimeError('주문 권한 데이터 오류: 주문을 차단합니다.')
        # Legacy combined consent must not silently activate either market.
        state['daytrade_ks'] = state.get('daytrade_ks') is True
        state['daytrade_us'] = state.get('daytrade_us') is True
        state['daytrade'] = state['daytrade_ks'] or state['daytrade_us']
        return state

    def status(self):
        try:
            state = self.read()
            configured = True
        except ValueError:
            state = {'infinite_buy': False, 'daytrade': False, 'daytrade_ks': False, 'daytrade_us': False, 'symbols': {}}
            configured = False
        registry = getattr(sys, '_stock8_live_policy_workers', {})
        jobs = registry.get('jobs', {})
        worker_status = {}
        if configured:
            worker_status = {job: {k: v for k, v in item.items() if k != 'thread'}
                             for (key, job), item in list(jobs.items()) if key == self._key()}
        allowed = self.daytrade_allowed()
        if not allowed:
            state = {**state, 'daytrade': False, 'daytrade_ks': False, 'daytrade_us': False}
            worker_status = {k: v for k, v in worker_status.items() if k == 'loc'}
        return {**state, 'daytrade_allowed': allowed, 'configured': configured, 'default_locked': self.live, 'workers': worker_status,
                'dispatcher_failed': bool(registry.get('error')),
                'warning_version': WARNING_VERSION, 'mode': 'LIVE' if self.live else 'PAPER'}

    def update(self, lane=None, enabled=None, symbol=None, locked=None, confirmation=''):
        if lane in ('daytrade_ks', 'daytrade_us') and not self.daytrade_allowed():
            raise ValueError('단타는 관리자 전용 기능입니다.')
        # Serialize read-modify-write; an error must never appear as successful ON.
        with LOCK:
            state = self.read()
            if lane is not None:
                if lane not in LANES or not isinstance(enabled, bool):
                    raise ValueError('잘못된 자동매매 설정입니다.')
                if enabled and confirmation != WARNING_VERSION:
                    raise ValueError('자동매매 위험 안내를 확인해야 켤 수 있습니다.')
                state[lane] = enabled
                uid = str(self.struct._current_user_id() or '')
                if not uid:
                    raise ValueError('로그인이 필요합니다.')
                state['owner_user_id'] = uid
            if symbol is not None:
                if not isinstance(locked, bool):
                    raise ValueError('잘못된 종목 잠금 설정입니다.')
                if not locked and confirmation != WARNING_VERSION:
                    raise ValueError('종목 잠금 해제 위험 안내를 확인하세요.')
                state['symbols'][symbol_key(symbol)] = locked
            db = self.struct.db('trading_config')
            key = self._key()
            row = db.get(key=key)
            values = {'value': json.dumps(state, ensure_ascii=False), 'description': '계좌별 전략 허용 및 종목 잠금', 'is_secret': False}
            if row:
                db.update(values, id=row['id'])
            else:
                db.insert({**values, 'key': key})
            return self.status()

    def assert_order(self, symbol=''):
        lane, scoped_symbol = CONTEXT.get()
        symbol = symbol_key(symbol or scoped_symbol)
        if lane.startswith('daytrade') and symbol == 'SOXL':
            raise RuntimeError('SOXL은 무한매수 전용입니다. 단타 매수·매도·정정·취소를 차단합니다.')
        if lane in ('daytrade_ks', 'daytrade_us') and not self.daytrade_allowed():
            raise RuntimeError('단타는 관리자 전용 기능입니다. 주문을 차단합니다.')
        state = self.read()
        symbol = symbol_key(symbol or scoped_symbol)
        managed_soxl = lane == 'infinite_buy' and symbol == 'SOXL'
        if managed_soxl:
            # SOXL belongs to its cycle, never to the daytrade lock switch.
            # Recheck ownership and operation state at every broker mutation.
            uid = str(self.struct._current_user_id() or '').strip()
            active = False
            if uid and state.get('infinite_buy') is True:
                for status in ('ACTIVE', 'HOLDING', 'PENDING_EXTENSION'):
                    cycle = self.struct.db('trading_cycle').get(symbol=symbol, status=status, user_id=uid)
                    if (cycle and cycle.get('symbol') == symbol and cycle.get('status') == status
                            and str(cycle.get('user_id') or '') == uid):
                        active = True
                        break
            if not active:
                raise RuntimeError('SOXL: 무한매수 ON 및 본인 계정의 운영 중인 사이클이 필요합니다.')
        if not managed_soxl and state['symbols'].get(symbol, self.live) is not False:
            raise RuntimeError(f'{symbol}: 자동매매 잠금 상태입니다. 매수·매도·정정·취소를 차단합니다.')
        if self.live and (lane not in LANES or state.get(lane) is not True):
            raise RuntimeError('해당 전략의 실투자 자동매매가 OFF입니다.')

    def bind(self, broker, lane):
        return BoundBroker(broker, lane)

Model = Policy
