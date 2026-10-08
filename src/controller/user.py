import season

class Controller(wiz.controller("base")):
    def __init__(self):
        super().__init__()

        if wiz.session.has("id") == False:
            wiz.response.status(401)

        import os
        if os.environ.get('TRADING_MODE', 'PAPER').upper() == 'PAPER':
            from flask import request
            subscribed = wiz.model('portal/trading/paper_subscription')(wiz.server.path.root).enabled(wiz.session.get('id'))
            if not subscribed and not request.path.startswith(('/settings', '/wiz/api/page.settings/', '/wiz/api/component.nav.trading/')):
                wiz.response.status(403, message='설정에서 모의투자를 먼저 신청하세요.')

        from flask import request
        if request.path == '/daytrade' or request.path.startswith('/daytrade/'):
            trading = wiz.model('struct').trading
            if not trading._current_user_is_admin(wiz.session.get('id')):
                wiz.response.status(403, message='단타는 관리자 전용 기능입니다. 무한매수를 이용해주세요.')

        # TODO: 실제 구현 시 사용자 접근 권한 검증
        # struct = wiz.model("portal/{pkg}/struct")
        # struct.user(wiz.session.get("id")).access()
