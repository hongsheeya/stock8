from flask import request

def _trading():
    session = wiz.model('portal/season/session').use()
    if not session.get('id'):
        wiz.response.status(401, message='로그인이 필요합니다.')
    return wiz.model('struct').trading

def status():
    try:
        state = _trading().order_policy.status()
    except Exception:
        wiz.response.status(503, message='주문 권한 조회 실패. ON으로 간주하지 않습니다.')
    wiz.response.status(200, state)

def holdings():
    trading = _trading()
    rows, errors = [], []
    try:
        broker = getattr(trading, 'broker_api', None) or trading.kis_api
        for method in ('get_domestic_balance', 'get_balance'):
            try:
                with broker.request_options(timeout=3, retries=0):
                    rows.extend((getattr(broker, method)() or {}).get('holdings', []) or [])
            except Exception:
                errors.append('국내' if method == 'get_domestic_balance' else '해외')
    except Exception:
        errors = ['국내', '해외']
    wiz.response.status(200, {'holdings': rows, 'message': ('·'.join(errors) + ' 보유 조회 실패. 빈 잔고로 판단하지 마세요.') if errors else ''})


def save():
    if request.method != 'POST':
        wiz.response.status(405, message='POST 요청만 허용됩니다.')
    origin = request.headers.get('Origin')
    if origin and origin != request.host_url.rstrip('/'):
        wiz.response.status(403, message='다른 출처에서 주문 설정을 변경할 수 없습니다.')
    trading = _trading()
    lane = str(wiz.request.query('lane', '') or '')
    symbol = str(wiz.request.query('symbol', '') or '')
    confirmation = str(wiz.request.query('confirmation', '') or '')
    if lane in ('daytrade_ks', 'daytrade_us') and not trading.order_policy.daytrade_allowed():
        wiz.response.status(403, message='단타는 관리자 전용 기능입니다.')
    try:
        if lane and not symbol:
            enabled = str(wiz.request.query('enabled', '')).lower()
            if enabled not in ('true', 'false'):
                raise ValueError('ON/OFF 값을 확인하세요.')
            if lane not in ('infinite_buy', 'daytrade_ks', 'daytrade_us'):
                raise ValueError('전략을 확인하세요.')
            current = trading.order_policy.status()
            if not current['configured']:
                raise ValueError('먼저 API 계좌를 설정하세요.')
            if enabled == 'true' and confirmation != current['warning_version']:
                raise ValueError('자동매매 위험 안내를 확인해야 켤 수 있습니다.')
            if enabled == 'false':
                trading.order_policy.update(lane=lane, enabled=False)
            keys = {'infinite_buy': ('auto_trade_enabled', 'loc_auto_schedule_enabled'),
                    'daytrade_ks': ('daytrade_auto_enabled', 'daytrade_exit_watch_enabled'),
                    'daytrade_us': ('daytrade_us_auto_enabled', 'daytrade_us_exit_watch_enabled',
                                    'us_daytrade_auto_enabled', 'us_daytrade_exit_watch_enabled')}[lane]
            for key in keys:
                trading.set_config(key, enabled, description='사용자 확인 후 전략별 자동매매 설정')
                storage_key = trading._user_config_key(trading._current_user_id(), key)
                saved = trading.db('trading_config').get(key=storage_key) or {}
                if saved.get('value') != enabled:
                    trading.order_policy.update(lane=lane, enabled=False)
                    raise RuntimeError('전략 설정 저장 실패. 주문 권한은 OFF로 유지합니다.')
            state = trading.order_policy.update(lane=lane, enabled=enabled == 'true', confirmation=confirmation)
            if lane != 'infinite_buy':
                trading.set_config('daytrade_feature_enabled',
                                   'true' if state['daytrade'] else 'false')
        elif symbol and not lane:
            locked = str(wiz.request.query('locked', '')).lower()
            if locked not in ('true', 'false'):
                raise ValueError('잠금 값을 확인하세요.')
            state = trading.order_policy.update(symbol=symbol, locked=locked == 'true', confirmation=confirmation)
        else:
            raise ValueError('전략 또는 종목을 선택하세요.')
    except (ValueError, RuntimeError) as exc:
        wiz.response.status(400, message=str(exc))
    wiz.response.status(200, state)
