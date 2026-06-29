# =============================================================================
# 한국투자증권 Open API 연동 Sub-Struct
# =============================================================================
# 해외주식 시세 조회, 주문, 잔고 조회 등
# API 문서: https://apiportal.koreainvestment.com/apiservice
# =============================================================================
import json
import datetime
import time
import threading
from contextlib import contextmanager

_TIME = wiz.model("portal/trading/kst")

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

try:
    import requests
except ImportError:
    requests = None

# -----------------------------------------------------------------------------
# 상수 정의
# -----------------------------------------------------------------------------
REAL_BASE_URL = "https://openapi.koreainvestment.com:9443"
MOCK_BASE_URL = "https://openapivts.koreainvestment.com:29443"

TOKEN_ISSUE_PATH = "/oauth2/tokenP"
TOKEN_REVOKE_PATH = "/oauth2/revokeP"
_REQUEST_OPTIONS = threading.local()


class KisApi:
    """한국투자증권 Open API 래퍼"""

    # Rate limiting: 초당 최대 호출 수 제한 (KIS API 초당 20건 제한)
    _last_request_time = 0
    _min_request_interval = 0.12  # 초 (약 초당 8건)
    PRICE_EXCHANGE_CANDIDATES = ("NAS", "NYS", "AMS")
    ORDER_EXCHANGE_MAP = {"NAS": "NASD", "NYS": "NYSE", "AMS": "AMEX"}
    US_MARKET_HOLIDAYS = {
        "2026-01-01": "New Year's Day",
        "2026-01-19": "Martin Luther King Jr. Day",
        "2026-02-16": "Washington's Birthday",
        "2026-04-03": "Good Friday",
        "2026-05-25": "Memorial Day",
        "2026-06-19": "Juneteenth",
        "2026-07-03": "Independence Day observed",
        "2026-09-07": "Labor Day",
        "2026-11-26": "Thanksgiving Day",
        "2026-12-25": "Christmas Day",
        "2027-01-01": "New Year's Day",
        "2027-01-18": "Martin Luther King Jr. Day",
        "2027-02-15": "Washington's Birthday",
        "2027-03-26": "Good Friday",
        "2027-05-31": "Memorial Day",
        "2027-06-18": "Juneteenth observed",
        "2027-07-05": "Independence Day observed",
        "2027-09-06": "Labor Day",
        "2027-11-25": "Thanksgiving Day",
        "2027-12-24": "Christmas Day observed",
        "2028-01-17": "Martin Luther King Jr. Day",
        "2028-02-21": "Washington's Birthday",
        "2028-04-14": "Good Friday",
        "2028-05-29": "Memorial Day",
        "2028-06-19": "Juneteenth",
        "2028-07-04": "Independence Day",
        "2028-09-04": "Labor Day",
        "2028-11-23": "Thanksgiving Day",
        "2028-12-25": "Christmas Day",
    }

    def __init__(self, struct):
        self.struct = struct
        self._token = None
        self._token_expires = None
        self._token_scope = ""
        self._logger = None

    @property
    def logger(self):
        if self._logger is None:
            try:
                self._logger = wiz.logger("trading", "kis_api")
            except Exception:
                self._logger = None
        return self._logger

    def _log(self, level, msg):
        try:
            if self.logger:
                getattr(self.logger, level, self.logger.info)(msg)
        except Exception:
            pass

    def _kst_now(self):
        return _TIME.now()

    def _us_eastern_now(self, now=None):
        now = now or self._kst_now()
        if ZoneInfo is not None:
            try:
                if getattr(now, "tzinfo", None) is not None:
                    return now.astimezone(ZoneInfo("America/New_York"))
                return now.replace(tzinfo=ZoneInfo("Asia/Seoul")).astimezone(ZoneInfo("America/New_York"))
            except Exception:
                pass
        # Fallback: approximate US DST dates. This is only used on runtimes
        # without zoneinfo; the production image has zoneinfo.
        y = now.year
        mar1 = datetime.datetime(y, 3, 1)
        dst_start = mar1 + datetime.timedelta(days=(6 - mar1.weekday()) % 7 + 7)
        nov1 = datetime.datetime(y, 11, 1)
        dst_end = nov1 + datetime.timedelta(days=(6 - nov1.weekday()) % 7)
        offset_hours = -13 if dst_start <= now < dst_end else -14
        return now + datetime.timedelta(hours=offset_hours)

    def us_market_holiday_label(self, now=None):
        now_et = self._us_eastern_now(now)
        return self.US_MARKET_HOLIDAYS.get(now_et.date().isoformat(), "")

    def _us_auto_exchange_session(self, now=None):
        now_et = self._us_eastern_now(now)
        if now_et.weekday() >= 5:
            return {"ready": False, "session": "closed", "label": "주말 휴장"}
        holiday = self.us_market_holiday_label(now)
        if holiday:
            return {"ready": False, "session": "holiday", "label": f"미국 휴장일({holiday})"}
        hhmm = now_et.hour * 100 + now_et.minute
        if 400 <= hhmm < 930:
            return {"ready": True, "session": "premarket", "label": "프리마켓"}
        if 930 <= hhmm < 1600:
            return {"ready": True, "session": "regular", "label": "본장"}
        return {"ready": False, "session": "closed", "label": "장외 대기"}

    def _us_auto_exchange_ready(self, now=None):
        return bool(self._us_auto_exchange_session(now).get("ready", False))

    def us_auto_exchange_window(self, now=None):
        now = now or self._kst_now()
        session = self._us_auto_exchange_session(now)
        ready = bool(session.get("ready", False))
        session_label = str(session.get("label", "장외 대기") or "장외 대기")
        return {
            "enabled": True,
            "ready": ready,
            "scheduled_at": "US 프리마켓 ET 04:00",
            "session": session.get("session", "closed"),
            "label": session_label,
            "message": (f"{session_label} 진행 중: 원화 자동환전 주문 허용" if ready else "미국 프리마켓/본장 전이라 원화 자동환전 주문 대기 중"),
            "current_time": now.strftime("%H:%M KST"),
        }

    # =========================================================================
    # Config helpers
    # =========================================================================

    def _get_config(self, key, default=""):
        """캐시에서 읽음 — DB 직접 쿼리 제거, 연결 고갈 방지"""
        return self.struct.get_config(key, default)

    def _set_config(self, key, value, description="", is_secret=False):
        """DB 쓰기 + 캐시 즉시 갱신"""
        self.struct.set_config(key, str(value), description=description, is_secret=is_secret)

    @property
    def app_key(self):
        return self._get_config("kis_app_key")

    @property
    def app_secret(self):
        return self._get_config("kis_app_secret")

    @property
    def account_no(self):
        """계좌번호 (8자리-2자리 형태)"""
        return self._get_config("kis_account_no")

    @property
    def account_prefix(self):
        """계좌번호 앞 8자리"""
        acc = self.account_no
        return acc.split("-")[0] if "-" in acc else acc[:8]

    @property
    def account_suffix(self):
        """계좌번호 뒤 2자리"""
        acc = self.account_no
        if "-" in acc:
            return acc.split("-")[1]
        suffix = acc[8:]
        if suffix:
            return suffix
        # 폴백: kis_account_suffix 키에서 읽기 (레거시 호환)
        fallback = self._get_config("kis_account_suffix")
        return fallback if fallback else "01"

    @property
    def is_real(self):
        """실전투자 여부"""
        val = self._get_config("kis_is_real", "false")
        return val.lower() == "true"

    @property
    def base_url(self):
        return REAL_BASE_URL if self.is_real else MOCK_BASE_URL

    # =========================================================================
    # OAuth 토큰 관리
    # =========================================================================

    def _credential_scope(self):
        try:
            user_id = self.struct._current_user_id()
        except Exception:
            user_id = ""
        return f"{user_id}:{self.app_key}:{self.account_no}:{'real' if self.is_real else 'mock'}"

    def _issue_token(self):
        """접근토큰 발급"""
        scope = self._credential_scope()
        url = f"{self.base_url}{TOKEN_ISSUE_PATH}"
        body = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
        }
        resp = requests.post(url, json=body, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        self._token = data.get("access_token")
        self._token_scope = scope
        # 토큰 유효기간: 약 24시간, 1시간 마진
        expires_in = int(data.get("expires_in", 86400))
        self._token_expires = time.time() + expires_in - 3600

        # DB에 캐시
        self._set_config("kis_access_token", self._token, "접근토큰", True)
        self._set_config("kis_token_expires", str(self._token_expires), "토큰 만료시각")

        return self._token

    def get_token(self):
        """유효한 접근토큰 반환 (만료 시 자동 갱신)"""
        scope = self._credential_scope()
        if self._token and self._token_scope == scope and self._token_expires and time.time() < self._token_expires:
            return self._token

        # DB 캐시에서 복원 시도
        cached_token = self._get_config("kis_access_token")
        cached_expires = self._get_config("kis_token_expires", "0")
        try:
            cached_expires = float(cached_expires)
        except (ValueError, TypeError):
            cached_expires = 0

        if cached_token and time.time() < cached_expires:
            self._token = cached_token
            self._token_expires = cached_expires
            self._token_scope = scope
            return self._token

        # 신규 발급
        return self._issue_token()

    # =========================================================================
    # HTTP 요청 공통 래퍼
    # =========================================================================

    def _headers(self, tr_id, content_type="application/json; charset=utf-8"):
        """API 공통 헤더"""
        return {
            "Content-Type": content_type,
            "authorization": f"Bearer {self.get_token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }

    @contextmanager
    def request_options(self, timeout=None, retries=None):
        prev_timeout = getattr(_REQUEST_OPTIONS, "timeout", None)
        prev_retries = getattr(_REQUEST_OPTIONS, "retries", None)
        _REQUEST_OPTIONS.timeout = timeout
        _REQUEST_OPTIONS.retries = retries
        try:
            yield
        finally:
            _REQUEST_OPTIONS.timeout = prev_timeout
            _REQUEST_OPTIONS.retries = prev_retries

    def _rate_limit_wait(self):
        """API 호출 간 최소 간격 보장 (초당 호출 수 제한)"""
        now = time.time()
        elapsed = now - KisApi._last_request_time
        if elapsed < self._min_request_interval:
            wait = self._min_request_interval - elapsed
            time.sleep(wait)
        KisApi._last_request_time = time.time()

    def _request(self, method, path, tr_id, params=None, body=None, retries=2, tr_cont=""):
        """
        API 요청 공통 래퍼 (Rate limiting 포함)
        - method: "GET" | "POST"
        - path: API 경로 (예: "/uapi/overseas-price/v1/quotations/price")
        - tr_id: 거래 ID
        - params: query string dict (GET)
        - body: request body dict (POST)
        - retries: 재시도 횟수
        """
        url = f"{self.base_url}{path}"
        headers = self._headers(tr_id)
        if tr_cont:
            headers["tr_cont"] = str(tr_cont)
        request_timeout = getattr(_REQUEST_OPTIONS, "timeout", None)
        request_retries = getattr(_REQUEST_OPTIONS, "retries", None)
        try:
            request_timeout = float(request_timeout) if request_timeout is not None else 8.0
        except Exception:
            request_timeout = 8.0
        if request_retries is not None:
            try:
                retries = max(0, int(request_retries))
            except Exception:
                retries = 0

        for attempt in range(retries + 1):
            try:
                # Rate limiting 적용
                self._rate_limit_wait()

                if method.upper() == "GET":
                    resp = requests.get(url, headers=headers, params=params, timeout=request_timeout)
                else:
                    resp = requests.post(url, headers=headers, json=body, timeout=request_timeout)

                data = resp.json()
                if isinstance(data, dict):
                    tr_cont = (
                        resp.headers.get("tr_cont")
                        or resp.headers.get("Tr-Cont")
                        or resp.headers.get("TR_CONT")
                        or ""
                    )
                    if tr_cont and not data.get("tr_cont"):
                        data["tr_cont"] = tr_cont

                # 토큰 만료 에러 시 갱신 후 재시도
                rt_cd = data.get("rt_cd", "")
                msg1 = data.get("msg1", "")
                if rt_cd != "0" and "token" in msg1.lower():
                    self._issue_token()
                    headers = self._headers(tr_id)
                    continue

                # 초당 거래 건수 초과 시 대기 후 재시도
                if rt_cd != "0" and ("초과" in msg1 or "exceeded" in msg1.lower() or "EGW00201" in msg1):
                    self._log("warning", f"Rate limit exceeded (tr_id={tr_id}), waiting 1s and retrying...")
                    time.sleep(1)
                    if attempt < retries:
                        continue

                return data

            except requests.exceptions.RequestException as e:
                if attempt < retries:
                    time.sleep(1)
                    continue
                raise Exception(f"KIS API request failed: {str(e)}")

        return None

    # =========================================================================
    # API 연결 테스트
    # =========================================================================

    def test_connection(self):
        """API 연결 테스트 (토큰 발급 시도)"""
        try:
            token = self.get_token()
            if token:
                return {"success": True, "message": "API 연결 성공"}
            return {"success": False, "message": "토큰 발급 실패"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    # =========================================================================
    # 설정 저장/조회 편의 메서드
    # =========================================================================

    def save_settings(self, app_key, app_secret, account_no, is_real=False):
        """API 설정 일괄 저장"""
        self._set_config("kis_app_key", app_key, "앱 키", True)
        self._set_config("kis_app_secret", app_secret, "앱 시크릿", True)
        self._set_config("kis_account_no", account_no, "계좌번호", True)
        self._set_config("kis_is_real", str(is_real).lower(), "실전투자 여부")
        # 토큰 초기화 (새 키로 재발급)
        self._token = None
        self._token_expires = None

    def get_settings(self):
        """현재 API 설정 조회 (시크릿은 마스킹)"""
        app_key = self.app_key
        app_secret = self.app_secret
        account_no = self.account_no
        return {
            "app_key": app_key[:4] + "****" if len(app_key) > 4 else app_key,
            "app_secret": app_secret[:4] + "****" if len(app_secret) > 4 else app_secret,
            "account_no": account_no,
            "is_real": self.is_real,
        }

    # =========================================================================
    # 해외주식 현재가 조회
    # =========================================================================

    def _price_exchange_candidates(self, exchange=None):
        candidates = []
        if exchange:
            candidates.append(exchange)

        for item in self.PRICE_EXCHANGE_CANDIDATES:
            if item not in candidates:
                candidates.append(item)

        return candidates

    def _get_current_price_once(self, symbol, exchange="NAS"):
        """단일 거래소 기준 현재가 조회"""
        tr_id = "HHDFS00000300"
        path = "/uapi/overseas-price/v1/quotations/price"
        params = {
            "AUTH": "",
            "EXCD": exchange,
            "SYMB": symbol,
        }
        data = self._request("GET", path, tr_id, params=params)
        if not data or data.get("rt_cd") != "0":
            msg = data.get("msg1", "Unknown error") if data else "No response"
            raise Exception(f"현재가 조회 실패 [{symbol}:{exchange}]: {msg}")

        output = data.get("output", {})
        return {
            "symbol": symbol,
            "price": float(output.get("last", 0)),
            "change": float(output.get("diff", 0)),
            "change_rate": float(output.get("rate", 0)),
            "open": float(output.get("open", 0)),
            "high": float(output.get("high", 0)),
            "low": float(output.get("low", 0)),
            "prev_close": float(output.get("base", 0)),
            "volume": int(output.get("tvol", 0)),
            "name": output.get("name", symbol),
            "exchange": exchange,
            "order_exchange": self.ORDER_EXCHANGE_MAP.get(exchange, "NASD"),
        }

    def _get_prev_close_from_daily(self, symbol, exchange="NAS"):
        """현재가 응답에 전일종가가 없을 때 일봉으로 보완"""
        try:
            prices = self.get_daily_prices(symbol, exchange=exchange, count=3)
        except Exception as e:
            self._log("warning", f"prev_close fallback failed [{symbol}:{exchange}]: {e}")
            return 0

        for item in prices:
            close = self._safe_float(item.get("close", 0))
            if close > 0:
                return close

        return 0

    def _get_usd_krw_rate_fallback(self):
        """KIS 응답에 환율이 없을 때 사용할 USD/KRW fallback"""
        try:
            import yfinance as yf
        except ImportError:
            return {"rate": 0, "source": ""}

        try:
            hist = yf.Ticker("KRW=X").history(period="5d", auto_adjust=True)
            if hist.empty:
                return {"rate": 0, "source": ""}

            rate = self._safe_float(float(hist["Close"].dropna().iloc[-1]))
            if rate > 0:
                return {"rate": rate, "source": "yfinance:KRW=X"}
        except Exception as e:
            self._log("warning", f"USD/KRW fallback failed: {e}")

        return {"rate": 0, "source": ""}

    def get_current_price(self, symbol, exchange="NAS"):
        """
        해외주식 현재가 조회
        - symbol: 종목코드 (예: TQQQ, SOXL)
        - exchange: 거래소코드 (NAS=나스닥, NYS=뉴욕, AMS=아멕스)
        반환: dict {price, change, change_rate, volume, ...}
        """
        last_error = None
        fallback_price = None

        for candidate in self._price_exchange_candidates(exchange):
            try:
                price_data = self._get_current_price_once(symbol, exchange=candidate)
            except Exception as e:
                last_error = e
                continue

            if price_data.get("price", 0) <= 0:
                if fallback_price is None:
                    fallback_price = price_data
                continue

            if price_data.get("prev_close", 0) <= 0:
                price_data["prev_close"] = self._get_prev_close_from_daily(symbol, exchange=candidate)

            if candidate != exchange:
                self._log("info", f"price exchange fallback [{symbol}]: {exchange} -> {candidate}")

            return price_data

        if fallback_price is not None:
            if fallback_price.get("prev_close", 0) <= 0:
                fallback_price["prev_close"] = self._get_prev_close_from_daily(symbol, exchange=fallback_price.get("exchange", exchange))
            return fallback_price

        if last_error is not None:
            raise last_error

        raise Exception(f"현재가 조회 실패 [{symbol}]")

    def get_domestic_current_price(self, symbol):
        """국내주식 현재가 조회"""
        tr_id = "FHKST01010100"
        path = "/uapi/domestic-stock/v1/quotations/inquire-price"
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": str(symbol),
        }
        data = self._request("GET", path, tr_id, params=params)
        if not data or data.get("rt_cd") != "0":
            msg = data.get("msg1", "Unknown error") if data else "No response"
            rt_cd = data.get("rt_cd", "?") if data else "no_data"
            raise Exception(f"국내 현재가 조회 실패 [{symbol}]: rt_cd={rt_cd}, msg={msg}")
        output = data.get("output", {}) or {}
        return {
            "symbol": str(symbol),
            "price": float(output.get("stck_prpr", 0) or 0),
            "open": float(output.get("stck_oprc", 0) or 0),
            "high": float(output.get("stck_hgpr", 0) or 0),
            "low": float(output.get("stck_lwpr", 0) or 0),
            "prev_close": float(output.get("stck_sdpr", 0) or 0),
            "timestamp": _TIME.normalize(_TIME.now()),
            "source": "kis_domestic_quote",
            "raw": output,
        }

    # =========================================================================
    # 해외주식 기간별 시세 (일봉)
    # =========================================================================

    def get_daily_prices(self, symbol, exchange="NAS", period="D", count=100):
        """
        해외주식 기간별 시세 조회 (일봉 데이터)
        - period: D=일봉, W=주봉, M=월봉
        반환: list of dict [{date, open, high, low, close, volume}, ...]
        """
        tr_id = "HHDFS76240000"
        path = "/uapi/overseas-price/v1/quotations/dailyprice"

        end_date = _TIME.today("%Y%m%d")

        params = {
            "AUTH": "",
            "EXCD": exchange,
            "SYMB": symbol,
            "GUBN": "0",
            "BYMD": end_date,
            "MODP": "1",
        }
        data = self._request("GET", path, tr_id, params=params)
        if not data or data.get("rt_cd") != "0":
            msg = data.get("msg1", "Unknown error") if data else "No response"
            raise Exception(f"일봉 조회 실패 [{symbol}]: {msg}")

        output2 = data.get("output2", [])
        prices = []
        for item in output2[:count]:
            if not item.get("xymd"):
                continue
            prices.append({
                "date": item.get("xymd", ""),
                "open": float(item.get("open", 0)),
                "high": float(item.get("high", 0)),
                "low": float(item.get("low", 0)),
                "close": float(item.get("clos", 0)),
                "volume": int(item.get("tvol", 0)),
            })

        return prices

    # =========================================================================
    # 해외주식 매수 주문
    # =========================================================================

    def _domestic_order(self, side, symbol, qty, price=0, order_type="MARKET"):
        # Shadow Mode: 실제 주문 전송 건너뛰기
        is_shadow_mode = self._get_config("daytrade_shadow_mode", "false").lower() == "true"
        if is_shadow_mode:
            self._log("warning", f"SHADOW ORDER: {side} {symbol} {qty}주 @ {price} ({order_type})")
            return {
                "order_no": f"shadow_{int(time.time())}",
                "order_time": _TIME.now().strftime("%H%M%S"),
                "symbol": symbol,
                "qty": int(qty),
                "price": float(price),
                "order_type": order_type,
                "side": side,
                "shadow": True,
            }

        side = str(side or "BUY").upper()
        if side not in ["BUY", "SELL"]:
            raise Exception("국내주식 주문 구분이 잘못되었습니다.")

        tr_id_map = {
            "BUY": "TTTC0802U" if self.is_real else "VTTC0802U",
            "SELL": "TTTC0801U" if self.is_real else "VTTC0801U",
        }
        tr_id = tr_id_map[side]
        path = "/uapi/domestic-stock/v1/trading/order-cash"

        if order_type == "MARKET":
            ord_dvsn = "01"
            price = 0
        else:
            ord_dvsn = "00"

        cano = self.account_prefix
        acnt_cd = self.account_suffix
        if not cano or not acnt_cd:
            raise Exception("국내주식 주문을 위한 계좌번호가 올바르지 않습니다.")

        body = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_cd,
            "PDNO": symbol,
            "ORD_DVSN": ord_dvsn,
            "ORD_QTY": str(int(qty)),
            "ORD_UNPR": str(int(price)) if price else "0",
        }

        data = self._request("POST", path, tr_id, body=body, retries=0)
        if not data or data.get("rt_cd") != "0":
            msg = data.get("msg1", "Unknown error") if data else "No response"
            raise Exception(f"국내주식 {side} 주문 실패 [{symbol}]: {msg} (qty={qty}, price={price}, order_type={order_type}, ord_dvsn={ord_dvsn})")

        output = data.get("output", {})
        return {
            "order_no": output.get("ODNO", ""),
            "order_time": output.get("ORD_TMD", ""),
            "symbol": symbol,
            "qty": int(qty),
            "price": float(price),
            "order_type": order_type,
            "side": side,
        }

    def buy_domestic_order(self, symbol, qty, price=0, order_type="MARKET"):
        return self._domestic_order("BUY", symbol, qty, price=price, order_type=order_type)

    def sell_domestic_order(self, symbol, qty, price=0, order_type="MARKET"):
        return self._domestic_order("SELL", symbol, qty, price=price, order_type=order_type)

    def get_domestic_balance(self):
        """국내주식 잔고 조회"""
        tr_id = "TTTC8434R" if self.is_real else "VTTC8434R"
        path = "/uapi/domestic-stock/v1/trading/inquire-balance"
        params = {
            "CANO": self.account_prefix,
            "ACNT_PRDT_CD": self.account_suffix,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }

        data = self._request("GET", path, tr_id, params=params)
        if not data or data.get("rt_cd") != "0":
            msg = data.get("msg1", "Unknown error") if data else "No response"
            raise Exception(f"국내주식 잔고 조회 실패: {msg}")

        output1 = data.get("output1", []) or []
        output2 = data.get("output2", {}) or {}
        summary = output2[0] if isinstance(output2, list) and len(output2) > 0 else (output2 if isinstance(output2, dict) else {})
        holdings = []
        for item in output1:
            symbol = str(item.get("pdno", "") or "").strip()
            qty = self._safe_int(item.get("hldg_qty", 0), 0)
            if symbol == "" or qty <= 0:
                continue
            market = "KQ" if str(item.get("prdt_type_cd", "")).strip() == "300" else "KS"
            holdings.append({
                "symbol": symbol,
                "market": market,
                "name": item.get("prdt_name", ""),
                "qty": qty,
                "avg_price": self._safe_float(item.get("pchs_avg_pric", 0), 0),
                "current_price": self._safe_float(item.get("prpr", 0), 0),
                "profit_loss": self._safe_float(item.get("evlu_pfls_amt", 0), 0),
                "profit_rate": self._safe_float(item.get("evlu_pfls_rt", 0), 0),
            })

        portfolio_eval_info = self._pick_amount_info(summary, ["scts_evlu_amt", "evlu_amt_smtl_amt"])
        total_asset_info = self._pick_amount_info(summary, ["tot_evlu_amt", "nass_amt", "bfdy_tot_asst_evlu_amt", "tot_asst_amt"])
        return {
            "holdings": holdings,
            "krw_balance": self._safe_float(summary.get("dnca_tot_amt", 0), 0),
            "withdrawable_krw": self._safe_float(summary.get("prvs_rcdl_excc_amt", 0) or summary.get("dnca_tot_amt", 0), 0),
            "portfolio_eval_krw": self._safe_float(portfolio_eval_info.get("value", 0), 0),
            "portfolio_eval_key": portfolio_eval_info.get("key", ""),
            "total_asset_krw": self._safe_float(total_asset_info.get("value", 0), 0),
            "total_asset_key": total_asset_info.get("key", ""),
            "nxdy_excc_amt": self._safe_float(summary.get("nxdy_excc_amt", 0), 0),
            "same_day_buy_krw": self._safe_float(summary.get("thdt_buy_amt", 0), 0),
            "same_day_sell_krw": self._safe_float(summary.get("thdt_sll_amt", 0), 0),
            "raw": data,
        }

    def get_domestic_buying_power_info(self, symbol="005930", price=0, order_type="MARKET"):
        """국내주식 주문가능금액/수량 조회"""
        tr_id = "TTTC8908R" if self.is_real else "VTTC8908R"
        path = "/uapi/domestic-stock/v1/trading/inquire-psbl-order"

        symbol = str(symbol or "005930")
        order_type_upper = str(order_type or "MARKET").upper()
        is_market_order = order_type_upper == "MARKET"
        price = self._safe_float(price, 0)
        if price <= 0 and not is_market_order:
            try:
                quote = self.get_domestic_current_price(symbol)
                price = self._safe_float(quote.get("price", 0), 0)
            except Exception:
                price = 0
        if price <= 0 and not is_market_order:
            price = 1

        ord_dvsn = "01" if is_market_order else "00"
        query_price = 0 if is_market_order else int(price)
        params = {
            "CANO": self.account_prefix,
            "ACNT_PRDT_CD": self.account_suffix,
            "PDNO": symbol,
            "ORD_UNPR": str(query_price),
            "ORD_DVSN": ord_dvsn,
            "CMA_EVLU_AMT_ICLD_YN": "N",
            "OVRS_ICLD_YN": "N",
        }

        data = self._request("GET", path, tr_id, params=params)
        if not data or data.get("rt_cd") != "0":
            msg = data.get("msg1", "Unknown error") if data else "No response"
            rt_cd = data.get("rt_cd", "?") if data else "no_data"
            return {
                "amount": 0.0,
                "qty": 0,
                "ok": False,
                "message": f"국내 주문 가능액 조회 실패: rt_cd={rt_cd}, msg={msg}",
                "source": "inquire-psbl-order",
                "raw": data or {},
            }

        output = data.get("output", {}) or {}
        # amount는 실주문 예산으로 쓰이므로 가장 큰 참고값이 아니라 cash/no-margin
        # 실행 가능액을 우선한다. 큰 표시값은 display_amount로만 보존한다.
        amount_keys = [
            "nrcvb_buy_amt",
            "ord_psbl_cash",
            "psbl_cash",
            "cash",
            "ord_psbl_amt",
            "buy_psbl_amt",
            "max_buy_amt",
            "wdrw_psbl_tot_amt",
        ]
        amount_values = {
            key: self._safe_float(output.get(key, 0), 0)
            for key in amount_keys
        }

        def _first_positive_info(keys, fallback_key="inquire-psbl-order"):
            first_present = None
            for key in keys:
                if key in output and first_present is None:
                    first_present = key
                amount = amount_values.get(key, 0.0)
                if amount > 0:
                    return {
                        "value": amount,
                        "key": key,
                        "present": True,
                        "positive": True,
                    }
            return {
                "value": 0.0,
                "key": first_present or fallback_key,
                "present": first_present is not None,
                "positive": False,
            }

        no_margin_info = _first_positive_info(["nrcvb_buy_amt"])
        cash_info = _first_positive_info(["ord_psbl_cash", "psbl_cash", "cash"])
        broker_info = _first_positive_info(["ord_psbl_amt", "buy_psbl_amt", "max_buy_amt"])
        withdrawable_info = _first_positive_info(["wdrw_psbl_tot_amt"])
        amount_info = no_margin_info
        if amount_info.get("value", 0) <= 0:
            amount_info = cash_info
        if amount_info.get("value", 0) <= 0:
            amount_info = broker_info
        if amount_info.get("value", 0) <= 0:
            amount_info = withdrawable_info

        positive_candidates = [(key, value) for key, value in amount_values.items() if value > 0]
        display_key = amount_info.get("key", "inquire-psbl-order")
        display_amount = float(amount_info.get("value", 0.0))
        if positive_candidates:
            display_key, display_amount = max(positive_candidates, key=lambda item: item[1])
        qty_info = self._pick_amount_info(output, [
            "nrcvb_buy_qty",
            "ord_psbl_qty",
            "psbl_qty",
            "buy_psbl_qty",
            "max_buy_qty",
        ])
        executable_amount = float(amount_info.get("value", 0.0))
        cash_amount = max(
            amount_values.get("ord_psbl_cash", 0),
            amount_values.get("psbl_cash", 0),
            amount_values.get("cash", 0),
        )
        broker_orderable_amount = max(
            amount_values.get("ord_psbl_amt", 0),
            amount_values.get("buy_psbl_amt", 0),
            amount_values.get("max_buy_amt", 0),
        )
        picked_qty = int(qty_info.get("value", 0) or 0)
        amount_qty = int((executable_amount * 0.98) / price) if price > 0 and executable_amount > 0 else 0
        executable_qty = picked_qty
        if amount_qty > 0:
            executable_qty = min(picked_qty, amount_qty) if picked_qty > 0 else amount_qty
        source = amount_info.get("key", "inquire-psbl-order")
        if executable_amount <= 0 and cash_amount > 0:
            source = "ord_psbl_cash"
        return {
            "amount": executable_amount,
            "executable_amount": executable_amount,
            "cash_amount": cash_amount,
            "cash_orderable_amount": cash_amount,
            "broker_orderable_amount": broker_orderable_amount,
            "max_buy_amount": amount_values.get("max_buy_amt", 0) or amount_values.get("nrcvb_buy_amt", 0),
            "no_margin_buy_amount": amount_values.get("nrcvb_buy_amt", 0),
            "withdrawable_amount": amount_values.get("wdrw_psbl_tot_amt", 0),
            "display_amount": display_amount,
            "display_source": display_key,
            "qty": executable_qty,
            "broker_qty": picked_qty,
            "executable_qty": executable_qty,
            "ok": True,
            "message": "",
            "source": source,
            "qty_source": qty_info.get("key", ""),
            "symbol": symbol,
            "price": float(price),
            "query_price": query_price,
            "order_type": order_type_upper,
            "ord_dvsn": ord_dvsn,
            "debug_fields": {
                "wdrw_psbl_tot_amt": amount_values.get("wdrw_psbl_tot_amt", 0),
                "max_buy_amt": amount_values.get("max_buy_amt", 0),
                "nrcvb_buy_amt": amount_values.get("nrcvb_buy_amt", 0),
                "ord_psbl_amt": amount_values.get("ord_psbl_amt", 0),
                "buy_psbl_amt": amount_values.get("buy_psbl_amt", 0),
                "psbl_cash": amount_values.get("psbl_cash", 0),
                "ord_psbl_cash": amount_values.get("ord_psbl_cash", 0),
            },
            "amount_candidates": amount_values,
            "raw": output,
        }

    def get_domestic_buying_power(self, symbol="005930", price=0, order_type="MARKET"):
        info = self.get_domestic_buying_power_info(symbol=symbol, price=price, order_type=order_type)
        return float(info.get("amount", 0))

    def buy_order(self, symbol, qty, price=0, order_type="LOC", exchange="NASD", allow_auto_exchange_attempt=None):
        """
        해외주식 매수 주문
        - qty: 주문수량
        - price: 주문가격 (시장가=0)
        - order_type: "MARKET"=시장가, "LOC"=LOC 지정가, "LIMIT"=지정가
        - exchange: NASD, NYSE, AMEX
        반환: dict {order_no, ...}
        """
        tr_id = "TTTT1002U" if self.is_real else "VTTT1002U"
        path = "/uapi/overseas-stock/v1/trading/order"

        # 주문종류 코드 매핑
        # KIS 해외주식: ord_dvsn="00"은 지정가 주문 (price 필수)
        # 시장가 주문이라도 price를 반드시 전달해야 함 (0은 에러)
        if order_type == "MARKET":
            ord_dvsn = "00"
            # 시장가라도 price를 그대로 사용 (호출자가 전달한 가격)
        elif order_type == "LOC":
            ord_dvsn = "34"  # LOC (Limit On Close)
        else:
            ord_dvsn = "00"

        cano = self.account_prefix
        acnt_cd = self.account_suffix

        # 계좌번호 검증
        if not cano or not acnt_cd:
            raw_acc = self.account_no
            raise Exception(
                f"매수 주문 실패 [{symbol}]: 계좌번호가 올바르지 않습니다. "
                f"(원본: '{raw_acc}', CANO: '{cano}', ACNT_PRDT_CD: '{acnt_cd}'). "
                f"설정에서 계좌번호를 '12345678-01' 형식(8자리-2자리)으로 입력해주세요."
            )

        body = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_cd,
            "OVRS_EXCG_CD": exchange,
            "PDNO": symbol,
            "ORD_QTY": str(qty),
            "OVRS_ORD_UNPR": str(price),
            "ORD_SVR_DVSN_CD": "0",
            "ORD_DVSN": ord_dvsn,
        }

        try:
            buying_power_info = self.get_buying_power_info(symbol=symbol, price=price, exchange=exchange)
            max_qty = int(buying_power_info.get("executable_qty", buying_power_info.get("broker_qty", buying_power_info.get("qty", 0))) or 0)
            orderable_amount = float(buying_power_info.get("executable_amount", buying_power_info.get("broker_amount", buying_power_info.get("amount", 0))) or 0)
            estimated_amount = float(buying_power_info.get("estimated_amount", buying_power_info.get("amount", orderable_amount)) or 0)
            estimated_qty = int(buying_power_info.get("estimated_qty", buying_power_info.get("qty", max_qty)) or 0)
            auto_exchange_usd = float(buying_power_info.get("auto_exchange_usd", 0) or 0)
            krw_auto_exchange_estimate_usd = float(buying_power_info.get("krw_auto_exchange_estimate_usd", 0) or 0)
            auto_exchange_ready = bool(buying_power_info.get("auto_exchange_ready", False))
            requested_amount = float(qty) * float(price)
            if allow_auto_exchange_attempt is None:
                try:
                    allow_auto_exchange_attempt = str(self.struct.get_config("us_auto_exchange_order_attempt_enabled", "true") or "true").lower() in ("1", "true", "yes", "y", "on")
                except Exception:
                    allow_auto_exchange_attempt = True
            else:
                allow_auto_exchange_attempt = bool(allow_auto_exchange_attempt)
            planning_amount = orderable_amount
            planning_qty = max_qty
            if allow_auto_exchange_attempt:
                planning_amount = max(orderable_amount, estimated_amount)
                planning_qty = max(max_qty, estimated_qty)
            if planning_amount + 1e-9 < requested_amount or planning_qty <= 0:
                detail = (
                    f"매수 주문 실패 [{symbol}]: 실제 주문가능수량 {max_qty}주 / 실제 주문가능금액 ${orderable_amount:.2f} / 요청금액 ${requested_amount:.2f}"
                )
                if planning_amount > orderable_amount + 0.01 or planning_qty > max_qty:
                    detail += f" | 자동환전 계획 가능 ${planning_amount:.2f} / {planning_qty}주"
                if allow_auto_exchange_attempt and auto_exchange_ready is False and (planning_amount > orderable_amount + 0.01 or planning_qty > max_qty):
                    detail += " | KIS 환전후주문가능액 반영 전이지만 자동환전 주문 기준으로 시도"
                if auto_exchange_usd > 0.01:
                    detail += f" | KIS 환전이후 주문가능 반영 ${auto_exchange_usd:.2f}"
                if estimated_amount > orderable_amount + 0.01 or krw_auto_exchange_estimate_usd > 0.01:
                    detail += (
                        f" | 화면 추정 가용 ${estimated_amount:.2f} 중 원화 자동환전 추정 "
                        f"${krw_auto_exchange_estimate_usd:.2f}는 KIS 환전이후주문가능액에 미반영"
                    )
                raise Exception(detail)
            if planning_qty > 0 and int(qty) > planning_qty:
                raise Exception(
                    f"매수 주문 실패 [{symbol}]: 실제 주문가능수량 {max_qty}주 / 주문가능금액 ${orderable_amount:.2f} / "
                    f"자동환전 계획 가능 {planning_qty}주 / 요청금액 ${requested_amount:.2f}"
                )
        except Exception as e:
            if "실제 주문가능수량" in str(e):
                raise

        self._log("info", f"BUY order payload: PDNO={symbol}, OVRS_EXCG_CD={exchange}, ORD_QTY={qty}, OVRS_ORD_UNPR={price}, ORD_DVSN={ord_dvsn}, order_type={order_type}")
        self._log("info", f"BUY order: {symbol} {qty}주 @ ${price} ({order_type}), CANO={cano}, exchange={exchange}")

        data = self._request("POST", path, tr_id, body=body, retries=0)
        if not data or data.get("rt_cd") != "0":
            msg = data.get("msg1", "Unknown error") if data else "No response"
            rt_cd = data.get("rt_cd", "?") if data else "no_data"
            power_detail = ""
            if "주문가능" in str(msg) or "가능금액" in str(msg):
                try:
                    refreshed = self.get_buying_power_info(symbol=symbol, price=price, exchange=exchange)
                    power_detail = (
                        f", executable_amount=${self._safe_float(refreshed.get('executable_amount', 0), 0):.2f}"
                        f", executable_qty={self._safe_int(refreshed.get('executable_qty', 0), 0)}"
                        f", broker_amount=${self._safe_float(refreshed.get('broker_amount', 0), 0):.2f}"
                        f", exchange_after_amount=${self._safe_float(refreshed.get('exchange_after_amount', 0), 0):.2f}"
                        f", krw_auto_exchange_estimate_usd=${self._safe_float(refreshed.get('krw_auto_exchange_estimate_usd', 0), 0):.2f}"
                        f", buying_power_source={refreshed.get('source', '')}"
                    )
                except Exception:
                    power_detail = ""
            raise Exception(
                f"매수 주문 실패 [{symbol}]: {msg} "
                f"(rt_cd={rt_cd}, exchange={exchange}, qty={qty}, price={price}, ord_dvsn={ord_dvsn}, "
                f"tr_id={tr_id}, is_real={self.is_real})"
                f"{power_detail}"
            )

        output = data.get("output", {})
        return {
            "order_no": output.get("ODNO", ""),
            "order_time": output.get("ORD_TMD", ""),
            "symbol": symbol,
            "qty": qty,
            "price": price,
            "order_type": order_type,
        }

    def buy_reservation_order(self, symbol, qty, price=0, order_type="LOC", exchange="NASD"):
        """
        해외주식 미국 예약매수 주문.
        정규장 전 자동환전/예약매수 용도이며 KIS order-resv API를 사용한다.
        FireGate 기본은 표의 주문방식(지정가/LOC)을 그대로 사용한다.
        """
        tr_id = "TTTT3014U" if self.is_real else "VTTT3014U"
        path = "/uapi/overseas-stock/v1/trading/order-resv"

        cano = self.account_prefix
        acnt_cd = self.account_suffix
        if not cano or not acnt_cd:
            raw_acc = self.account_no
            raise Exception(
                f"예약매수 주문 실패 [{symbol}]: 계좌번호가 올바르지 않습니다. "
                f"(원본: '{raw_acc}', CANO: '{cano}', ACNT_PRDT_CD: '{acnt_cd}')."
            )

        qty = int(qty)
        price = self._safe_float(price, 0)
        if qty <= 0 or price <= 0:
            raise Exception(f"예약매수 주문 실패 [{symbol}]: 주문수량/가격이 올바르지 않습니다. qty={qty}, price={price}")

        order_type = str(order_type or "LOC").upper()
        if order_type in ("LOC", "RESERVE_LOC"):
            ord_dvsn = "34"
            returned_order_type = "RESERVE_LOC"
        else:
            ord_dvsn = "00"
            returned_order_type = "RESERVE_LIMIT"
        price_text = f"{price:.4f}" if price < 1 else f"{price:.2f}"
        price_text = price_text.rstrip("0").rstrip(".")

        body = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_cd,
            "PDNO": str(symbol).upper(),
            "OVRS_EXCG_CD": str(exchange or "NASD").upper(),
            "FT_ORD_QTY": str(qty),
            "FT_ORD_UNPR3": price_text,
            "ORD_DVSN": ord_dvsn,
            "ORD_SVR_DVSN_CD": "0",
        }

        self._log(
            "info",
            f"BUY reserve payload: PDNO={body['PDNO']}, OVRS_EXCG_CD={body['OVRS_EXCG_CD']}, "
            f"FT_ORD_QTY={body['FT_ORD_QTY']}, FT_ORD_UNPR3={body['FT_ORD_UNPR3']}, "
            f"ORD_DVSN={ord_dvsn}, order_type={order_type}"
        )

        data = self._request("POST", path, tr_id, body=body, retries=0)
        if not data or data.get("rt_cd") != "0":
            msg = data.get("msg1", "Unknown error") if data else "No response"
            rt_cd = data.get("rt_cd", "?") if data else "no_data"
            raise Exception(
                f"예약매수 주문 실패 [{symbol}]: {msg} "
                f"(rt_cd={rt_cd}, CANO={cano}, ACNT_PRDT_CD={acnt_cd}, "
                f"exchange={exchange}, qty={qty}, price={price_text}, ord_dvsn={ord_dvsn}, "
                f"tr_id={tr_id}, is_real={self.is_real})"
            )

        output = data.get("output", {}) or {}
        reserve_order_no = (
            output.get("ODNO")
            or output.get("OVRS_RSVN_ODNO")
            or output.get("ovrs_rsvn_odno")
            or output.get("odno")
            or ""
        )
        return {
            "order_no": reserve_order_no,
            "reserve_order_no": reserve_order_no,
            "order_time": output.get("ORD_TMD", output.get("ord_tmd", "")),
            "symbol": str(symbol).upper(),
            "qty": qty,
            "price": price,
            "order_type": returned_order_type,
            "requested_order_type": order_type,
            "exchange": str(exchange or "NASD").upper(),
            "reserved": True,
            "raw": output,
        }

    def get_overseas_reservation_orders(self, start_date=None, end_date=None, exchanges=None):
        """해외주식 예약주문 조회. 정상 접수와 장전 전송거부 상태를 함께 반환한다."""
        if self.is_real is False:
            return []

        tr_id = "TTTT3039R"
        path = "/uapi/overseas-stock/v1/trading/order-resv-list"
        if not start_date:
            start_date = _TIME.today("%Y%m%d")
        if not end_date:
            end_date = start_date

        # KIS reservation list returns all US reservation rows from a single
        # exchange query. Querying every exchange duplicates the same pages.
        exchanges = exchanges or ["NASD"]
        orders = []
        seen = set()

        try:
            max_pages = int(float(self.struct.get_config("kis_reservation_query_max_pages", "200") or 200))
        except Exception:
            max_pages = 200
        max_pages = max(1, max_pages)

        for exchange in exchanges:
            ctx_fk = ""
            ctx_nk = ""
            page = 0
            while page < max_pages:
                page += 1
                params = {
                    "CANO": self.account_prefix,
                    "ACNT_PRDT_CD": self.account_suffix,
                    "INQR_STRT_DT": start_date,
                    "INQR_END_DT": end_date,
                    "INQR_DVSN_CD": "00",
                    "OVRS_EXCG_CD": str(exchange or "NASD").upper(),
                    "PRDT_TYPE_CD": "",
                    "CTX_AREA_FK200": ctx_fk,
                    "CTX_AREA_NK200": ctx_nk,
                }

                data = self._request(
                    "GET",
                    path,
                    tr_id,
                    params=params,
                    retries=0,
                    tr_cont="N" if (ctx_fk or ctx_nk) else "",
                )
                if not data or data.get("rt_cd") != "0":
                    break

                output = data.get("output", []) or data.get("output1", []) or []
                for item in output:
                    row = {str(k).lower(): v for k, v in (item or {}).items()}
                    reserve_no = str(self._first_ci(item, [
                        "ovrs_rsvn_odno", "odno", "ovrs_odno", "ord_no", "order_no",
                    ], "") or "").strip()
                    symbol = str(self._first_ci(item, [
                        "pdno", "ovrs_pdno", "prdt_no", "symbol", "ovrs_item_cd",
                    ], "") or "").strip().upper()
                    receipt_date = str(self._first_ci(item, [
                        "rsvn_ord_rcit_dt", "ord_dt", "order_date",
                    ], start_date) or start_date)
                    output_exchange = str(self._first_ci(item, [
                        "ovrs_excg_cd", "exchange",
                    ], exchange) or exchange).upper()
                    side = self._normalize_overseas_action(item)
                    if not side:
                        side = self._normalize_overseas_action(row)
                    if not side:
                        side = "BUY" if str(row.get("sll_buy_dvsn_cd") or "") == "02" else "SELL"
                    ord_dvsn = str(self._first_ci(item, [
                        "ord_dvsn", "ORD_DVSN", "ovrs_ord_dvsn", "OVRS_ORD_DVSN",
                        "ord_dvsn_cd", "ORD_DVSN_CD",
                    ], "") or "").strip()
                    order_type = ""
                    if ord_dvsn == "34":
                        order_type = "LOC"
                    elif ord_dvsn == "00":
                        order_type = "LIMIT"
                    key = f"{receipt_date}:{reserve_no}:{symbol}:{output_exchange}"
                    if key in seen:
                        continue
                    seen.add(key)
                    orders.append({
                        "reserve_order_no": reserve_no,
                        "order_no": reserve_no,
                        "symbol": symbol,
                        "exchange": output_exchange,
                        "order_type": order_type,
                        "ord_dvsn": ord_dvsn,
                        "receipt_date": receipt_date,
                        "receipt_time": str(self._first_ci(item, ["ord_rcit_tmd", "ord_tmd", "order_time"], "") or ""),
                        "forward_time": str(self._first_ci(item, ["ord_fwdg_tmd", "fwdg_tmd"], "") or ""),
                        "side": side,
                        "qty": self._safe_int(self._first_ci(item, [
                            "ft_ord_qty", "ord_qty", "order_qty", "qty", "ord_rsvn_qty", "rsvn_ord_qty",
                        ], 0), 0),
                        "price": self._safe_float(self._first_ci(item, [
                            "ft_ord_unpr3", "ord_unpr", "ovrs_ord_unpr", "order_price",
                            "price", "ord_rsvn_unpr", "rsvn_ord_unpr",
                        ], 0), 0),
                        "filled_qty": self._safe_int(self._first_ci(item, [
                            "ft_ccld_qty", "ccld_qty", "tot_ccld_qty", "exec_qty", "filled_qty",
                        ], 0), 0),
                        "filled_price": self._safe_float(self._first_ci(item, [
                            "ft_ccld_unpr3", "ccld_unpr", "avg_pric", "exec_pric", "filled_price",
                        ], 0), 0),
                        "unfilled_qty": self._safe_int(self._first_ci(item, [
                            "nccs_qty", "unfilled_qty", "ord_psbl_qty",
                        ], 0), 0),
                        "status_code": str(self._first_ci(item, ["ovrs_rsvn_ord_stat_cd", "prcs_stat_cd", "status_code"], "") or ""),
                        "status_name": str(self._first_ci(item, ["ovrs_rsvn_ord_stat_cd_name", "prcs_stat_name", "status_name"], "") or ""),
                        "trade_status_name": str(self._first_ci(item, ["tr_dvsn_name", "rvse_cncl_dvsn_name", "trade_status_name"], "") or ""),
                        "reject_reason": str(self._first_ci(item, ["nprc_rson_text", "rjct_rson_name", "rjct_rson", "reject_reason"], "") or ""),
                        "cancel_yn": str(self._first_ci(item, ["cncl_yn", "cancel_yn", "rvse_cncl_dvsn"], "") or ""),
                        "raw": item,
                    })

                next_fk = str(data.get("ctx_area_fk200", data.get("CTX_AREA_FK200", "")) or "")
                next_nk = str(data.get("ctx_area_nk200", data.get("CTX_AREA_NK200", "")) or "")
                tr_cont = str(data.get("tr_cont", "") or "")
                if (next_fk == "" and next_nk == "") or tr_cont in ("", "D", "E"):
                    break
                if next_fk == ctx_fk and next_nk == ctx_nk:
                    break
                ctx_fk = next_fk
                ctx_nk = next_nk
            else:
                raise Exception(
                    f"해외 예약주문 조회가 {max_pages}페이지 한도를 초과했습니다. "
                    "전체 예약을 확인하지 못했으므로 취소/재예약을 중단해야 합니다."
                )

        return orders

    # =========================================================================
    # 해외주식 매도 주문
    # =========================================================================

    def sell_reservation_order(self, symbol, qty, price=0, order_type="LOC", exchange="NASD"):
        """
        해외주식 미국 예약매도 주문.
        KIS는 미국 예약주문에서 LOC 매도를 별도 TR_ID(TTTT3016U)로 접수한다.
        """
        tr_id = "TTTT3016U" if self.is_real else "VTTT3016U"
        path = "/uapi/overseas-stock/v1/trading/order-resv"

        cano = self.account_prefix
        acnt_cd = self.account_suffix
        if not cano or not acnt_cd:
            raw_acc = self.account_no
            raise Exception(
                f"예약매도 주문 실패 [{symbol}]: 계좌번호가 올바르지 않습니다. "
                f"(원본: '{raw_acc}', CANO: '{cano}', ACNT_PRDT_CD: '{acnt_cd}')."
            )

        qty = int(qty)
        price = self._safe_float(price, 0)
        if qty <= 0 or price <= 0:
            raise Exception(f"예약매도 주문 실패 [{symbol}]: 주문수량/가격이 올바르지 않습니다. qty={qty}, price={price}")

        order_type = str(order_type or "LOC").upper()
        if order_type in ("LOC", "RESERVE_LOC"):
            ord_dvsn = "34"
            returned_order_type = "RESERVE_LOC"
        else:
            ord_dvsn = "00"
            returned_order_type = "RESERVE_LIMIT"
        price_text = f"{price:.4f}" if price < 1 else f"{price:.2f}"
        price_text = price_text.rstrip("0").rstrip(".")

        body = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_cd,
            "PDNO": str(symbol).upper(),
            "OVRS_EXCG_CD": str(exchange or "NASD").upper(),
            "FT_ORD_QTY": str(qty),
            "FT_ORD_UNPR3": price_text,
            "ORD_DVSN": ord_dvsn,
            "ORD_SVR_DVSN_CD": "0",
        }

        self._log(
            "info",
            f"SELL reserve payload: PDNO={body['PDNO']}, OVRS_EXCG_CD={body['OVRS_EXCG_CD']}, "
            f"FT_ORD_QTY={body['FT_ORD_QTY']}, FT_ORD_UNPR3={body['FT_ORD_UNPR3']}, "
            f"ORD_DVSN={ord_dvsn}, order_type={order_type}"
        )

        data = self._request("POST", path, tr_id, body=body, retries=0)
        if not data or data.get("rt_cd") != "0":
            msg = data.get("msg1", "Unknown error") if data else "No response"
            rt_cd = data.get("rt_cd", "?") if data else "no_data"
            raise Exception(
                f"예약매도 주문 실패 [{symbol}]: {msg} "
                f"(rt_cd={rt_cd}, CANO={cano}, ACNT_PRDT_CD={acnt_cd}, "
                f"exchange={exchange}, qty={qty}, price={price_text}, ord_dvsn={ord_dvsn}, "
                f"tr_id={tr_id}, is_real={self.is_real})"
            )

        output = data.get("output", {}) or {}
        reserve_order_no = (
            output.get("ODNO")
            or output.get("OVRS_RSVN_ODNO")
            or output.get("ovrs_rsvn_odno")
            or output.get("odno")
            or ""
        )
        return {
            "order_no": reserve_order_no,
            "reserve_order_no": reserve_order_no,
            "order_time": output.get("ORD_TMD", output.get("ord_tmd", "")),
            "symbol": str(symbol).upper(),
            "qty": qty,
            "price": price,
            "order_type": returned_order_type,
            "requested_order_type": order_type,
            "exchange": str(exchange or "NASD").upper(),
            "reserved": True,
            "raw": output,
        }

    def cancel_overseas_reservation_order(self, reservation_order_no, symbol="", qty=0, exchange="NASD", side="", receipt_date=""):
        """
        해외주식 미국 예약주문접수취소.
        KIS 해외주식 예약주문접수취소 API는 예약주문번호(OVRS_RSVN_ODNO) 단위로 취소한다.
        """
        tr_id = "TTTT3017U" if self.is_real else "VTTT3017U"
        path = "/uapi/overseas-stock/v1/trading/order-resv-ccnl"

        cano = self.account_prefix
        acnt_cd = self.account_suffix
        if not cano or not acnt_cd:
            raise Exception("해외 예약주문 취소를 위한 계좌번호가 올바르지 않습니다.")

        reservation_order_no = str(reservation_order_no or "").strip()
        if reservation_order_no == "":
            raise Exception(f"해외 예약주문 취소 실패 [{symbol or '-'}]: 예약주문번호가 없습니다.")
        receipt_date = str(receipt_date or "").strip().replace("-", "")[:8]
        if receipt_date == "":
            raise Exception(f"해외 예약주문 취소 실패 [{symbol or '-'}]: 해외주문접수일자가 없습니다.")

        body = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_cd,
            "RSVN_ORD_RCIT_DT": receipt_date,
            "OVRS_RSVN_ODNO": reservation_order_no,
        }

        self._log(
            "info",
            f"OVERSEAS reserve cancel payload: RSVN_ORD_RCIT_DT={receipt_date}, OVRS_RSVN_ODNO={reservation_order_no}, "
            f"symbol={str(symbol or '').upper()}, exchange={str(exchange or 'NASD').upper()}, side={str(side or '').upper()}"
        )

        data = self._request("POST", path, tr_id, body=body, retries=0)
        if not data or data.get("rt_cd") != "0":
            msg = data.get("msg1", "Unknown error") if data else "No response"
            rt_cd = data.get("rt_cd", "?") if data else "no_data"
            raise Exception(
                f"해외 예약주문 취소 실패 [{symbol or '-'}]: {msg} "
                f"(rt_cd={rt_cd}, receipt_date={receipt_date}, reserve_order_no={reservation_order_no}, tr_id={tr_id}, is_real={self.is_real})"
            )

        output = data.get("output", {}) or {}
        qty_value = 0
        try:
            qty_value = int(float(qty or 0))
        except Exception:
            qty_value = 0
        return {
            "cancel_order_no": output.get("ODNO", output.get("odno", "")),
            "reserve_order_no": reservation_order_no,
            "original_order_no": reservation_order_no,
            "receipt_date": receipt_date,
            "symbol": str(symbol or "").upper(),
            "qty": qty_value,
            "exchange": str(exchange or "NASD").upper(),
            "side": str(side or "").upper(),
            "raw": output,
        }

    def sell_order(self, symbol, qty, price=0, order_type="MARKET", exchange="NASD"):
        """
        해외주식 매도 주문
        - order_type: "MARKET"=시장가, "LOC"=LOC 지정가(장마감 종가), "LIMIT"=지정가
        - LOC 매도 시 price에 지정가를 전달 (종가 이하일 때 체결)
        """
        tr_id = "TTTT1006U" if self.is_real else "VTTT1001U"
        path = "/uapi/overseas-stock/v1/trading/order"

        if order_type == "MARKET":
            ord_dvsn = "00"
            # 시장가라도 price를 그대로 사용 (호출자가 전달한 가격)
        elif order_type == "LOC":
            ord_dvsn = "34"  # LOC (Limit On Close)
        elif order_type == "LIMIT":
            ord_dvsn = "00"
        else:
            ord_dvsn = "00"

        cano = self.account_prefix
        acnt_cd = self.account_suffix

        if not cano or not acnt_cd:
            raw_acc = self.account_no
            raise Exception(
                f"매도 주문 실패 [{symbol}]: 계좌번호가 올바르지 않습니다. "
                f"(원본: '{raw_acc}', CANO: '{cano}', ACNT_PRDT_CD: '{acnt_cd}'). "
                f"설정에서 계좌번호를 '12345678-01' 형식(8자리-2자리)으로 입력해주세요."
            )

        body = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_cd,
            "OVRS_EXCG_CD": exchange,
            "PDNO": symbol,
            "ORD_QTY": str(qty),
            "OVRS_ORD_UNPR": str(price),
            "ORD_SVR_DVSN_CD": "0",
            "ORD_DVSN": ord_dvsn,
        }

        self._log("info", f"SELL order: {symbol} {qty}주 @ ${price} ({order_type}), CANO={cano}, exchange={exchange}")

        data = self._request("POST", path, tr_id, body=body)
        if not data or data.get("rt_cd") != "0":
            msg = data.get("msg1", "Unknown error") if data else "No response"
            rt_cd = data.get("rt_cd", "?") if data else "no_data"
            raise Exception(
                f"매도 주문 실패 [{symbol}]: {msg} "
                f"(rt_cd={rt_cd}, CANO={cano}, ACNT_PRDT_CD={acnt_cd}, "
                f"exchange={exchange}, qty={qty}, price={price}, ord_dvsn={ord_dvsn}, "
                f"tr_id={tr_id}, is_real={self.is_real})"
            )

        output = data.get("output", {})
        return {
            "order_no": output.get("ODNO", ""),
            "order_time": output.get("ORD_TMD", ""),
            "symbol": symbol,
            "qty": qty,
            "price": price,
            "order_type": order_type,
        }

    # =========================================================================
    # 해외주식 잔고 조회
    # =========================================================================

    def get_balance(self):
        """
        해외주식 잔고 조회 (보유종목 + 예수금)
        반환: dict {holdings: [...], cash_balance, total_eval, ...}
        """
        tr_id = "TTTS3012R" if self.is_real else "VTTS3012R"
        path = "/uapi/overseas-stock/v1/trading/inquire-balance"

        all_holdings = []
        holdings_by_symbol = {}
        summary_eval_candidates = []
        cash_balance = 0.0

        # 다중 거래소 조회
        for excg in ["NASD", "NYSE", "AMEX"]:
            try:
                params = {
                    "CANO": self.account_prefix,
                    "ACNT_PRDT_CD": self.account_suffix,
                    "OVRS_EXCG_CD": excg,
                    "TR_CRCY_CD": "USD",
                    "CTX_AREA_FK200": "",
                    "CTX_AREA_NK200": "",
                }

                data = self._request("GET", path, tr_id, params=params)
                if not data or data.get("rt_cd") != "0":
                    continue

                output1 = data.get("output1", [])
                output2 = data.get("output2", {})
                if isinstance(output2, list):
                    output2 = output2[0] if output2 else {}

                for item in output1:
                    if not item.get("ovrs_pdno"):
                        continue
                    item_qty = self._safe_int(item.get("ovrs_cblc_qty", 0), 0)
                    if item_qty <= 0:
                        continue
                    item_avg = self._safe_float(item.get("pchs_avg_pric", 0), 0)
                    item_price = self._safe_float(item.get("now_pric2", 0), 0)
                    item_eval = self._safe_float(item.get("ovrs_stck_evlu_amt", 0), 0)
                    item_profit = self._safe_float(item.get("frcr_evlu_pfls_amt", 0), 0)
                    item_profit_rate = self._safe_float(item.get("evlu_pfls_rt", 0), 0)
                    holding = {
                        "symbol": item.get("ovrs_pdno", ""),
                        "name": item.get("ovrs_item_name", ""),
                        "qty": item_qty,
                        "avg_price": item_avg,
                        "current_price": item_price,
                        "eval_amount": item_eval,
                        "profit_loss": item_profit,
                        "profit_rate": item_profit_rate,
                        "exchange": item.get("ovrs_excg_cd", excg),
                    }
                    symbol_key = str(holding.get("symbol", "") or "").upper()
                    prev = holdings_by_symbol.get(symbol_key)
                    if prev is None or self._safe_float(holding.get("eval_amount", 0), 0) >= self._safe_float(prev.get("eval_amount", 0), 0):
                        holdings_by_symbol[symbol_key] = holding

                # 주의: tot_evlu_pfls_amt 는 '평가손익'이므로 평가금액으로 사용하면 안됨
                excg_eval_info = self._pick_amount_info(output2, [
                    "tot_evlu_amt",
                    "ovrs_tot_evlu_amt",
                    "frcr_evlu_amt2",
                    "ovrs_stck_evlu_amt",
                ])
                excg_eval = self._safe_float(excg_eval_info.get("value", 0), 0)
                if excg_eval > 0:
                    summary_eval_candidates.append(excg_eval)

                # 주의: frcr_pchs_amt1 는 매수금액 계열일 수 있어 현금으로 사용하면 오차 발생
                excg_cash_info = self._pick_amount_info(output2, [
                    "ord_psbl_frcr_amt",
                    "frcr_ord_psbl_amt",
                    "frcr_dncl_amt_2",
                    "frcr_dncl_amt",
                ])
                excg_cash = self._safe_float(excg_cash_info.get("value", 0), 0)
                if excg_cash > cash_balance:
                    cash_balance = excg_cash

            except Exception:
                continue

        all_holdings = list(holdings_by_symbol.values())
        holdings_eval_sum = sum(self._safe_float(item.get("eval_amount", 0), 0) for item in all_holdings)
        # 거래소별 output2 요약은 계좌 전체 평가액이 반복될 수 있어 더하면 중복된다.
        # 실제 보유 row가 있으면 row 합계를 신뢰하고, row 평가액이 비어 있을 때만 요약값 중 최댓값을 fallback으로 쓴다.
        total_eval_sum = holdings_eval_sum
        if total_eval_sum <= 0 and len(summary_eval_candidates) > 0:
            total_eval_sum = max(summary_eval_candidates)

        return {
            "holdings": all_holdings,
            "total_eval": total_eval_sum,
            "cash_balance": cash_balance,
        }

    def _safe_float(self, value, default=0.0):
        try:
            if value is None or value == "":
                return default
            return float(str(value).replace(",", "").strip())
        except Exception:
            return default

    def _safe_int(self, value, default=0):
        try:
            if value is None or value == "":
                return default
            return int(float(str(value).replace(",", "").strip()))
        except Exception:
            return default

    def _pick_first_amount(self, payload, keys):
        for key in keys:
            amount = self._safe_float(payload.get(key, 0))
            if amount > 0:
                return amount
        return 0.0

    def _pick_amount_info(self, payload, keys):
        """후보 키 중 실제 존재/사용된 금액 정보를 반환한다."""
        fallback_key = None
        fallback_value = 0.0

        for key in keys:
            if key not in payload:
                continue
            raw = payload.get(key)
            if raw is None or raw == "":
                continue

            amount = self._safe_float(raw, 0.0)
            if amount > 0:
                return {
                    "value": amount,
                    "key": key,
                    "present": True,
                    "positive": True,
                }

            if fallback_key is None:
                fallback_key = key
                fallback_value = amount

        return {
            "value": fallback_value,
            "key": fallback_key,
            "present": fallback_key is not None,
            "positive": fallback_value > 0,
        }

    # =========================================================================
    # 해외주식 주문 체결 내역
    # =========================================================================

    def _row_ci(self, item):
        if not isinstance(item, dict):
            return {}
        return {str(k).lower(): v for k, v in item.items()}

    def _first_ci(self, item, keys, default=""):
        if not isinstance(item, dict):
            return default
        lowered = self._row_ci(item)
        for key in keys:
            if key in item:
                value = item.get(key)
            else:
                value = lowered.get(str(key).lower(), None)
            if value is not None and value != "":
                return value
        return default

    def _overseas_ccnl_rows(self, data):
        rows = []
        if not isinstance(data, dict):
            return rows
        for key in ("output", "output1", "output2"):
            output = data.get(key)
            if isinstance(output, list):
                rows.extend([item for item in output if isinstance(item, dict)])
            elif isinstance(output, dict):
                rows.append(output)
        return rows

    def _normalize_overseas_action(self, item):
        values = [
            self._first_ci(item, ["sll_buy_dvsn_cd", "sll_buy_dvsn", "sll_buy_dvsn_code", "side", "action"], ""),
            self._first_ci(item, ["sll_buy_dvsn_cd_name", "sll_buy_dvsn_name", "trad_dvsn_name", "tr_dvsn_name"], ""),
        ]
        for raw in values:
            token = str(raw or "").strip().upper()
            if token in ("02", "2", "BUY", "B"):
                return "BUY"
            if token in ("01", "1", "SELL", "S"):
                return "SELL"
            if "매수" in token:
                return "BUY"
            if "매도" in token:
                return "SELL"
        return ""

    def _normalize_overseas_ccnl_status(self, item):
        filled_qty = self._safe_int(self._first_ci(item, [
            "ft_ccld_qty",
            "ccld_qty",
            "tot_ccld_qty",
            "ccld_qty_smtl",
            "exec_qty",
            "filled_qty",
            "ft_ccld_qty1",
        ], 0), 0)
        order_qty = self._safe_int(self._first_ci(item, [
            "ft_ord_qty",
            "ord_qty",
            "order_qty",
            "qty",
            "ord_rsvn_qty",
        ], 0), 0)
        default_remaining = max(0, order_qty - filled_qty)
        remaining_qty = self._safe_int(self._first_ci(item, [
            "nccs_qty",
            "rmn_qty",
            "ord_unexec_qty",
            "unfilled_qty",
            "ord_psbl_qty",
        ], default_remaining), default_remaining)
        if filled_qty <= 0 and remaining_qty <= 0:
            return "CANCELLED"
        if filled_qty <= 0:
            return "PENDING"
        if remaining_qty > 0:
            return "PARTIAL"
        return "FILLED"

    def _normalize_overseas_ccnl_row(self, item, exchange, start_date):
        item_symbol = str(self._first_ci(item, [
            "pdno",
            "ovrs_pdno",
            "prdt_no",
            "symbol",
            "ovrs_item_cd",
        ], "") or "").strip().upper()
        order_no = str(self._first_ci(item, [
            "odno",
            "ovrs_odno",
            "ord_no",
            "order_no",
            "ovrs_ord_no",
            "ovrs_rsvn_odno",
        ], "") or "").strip()
        if not item_symbol and not order_no:
            return None

        action = self._normalize_overseas_action(item)
        order_date = str(self._first_ci(item, [
            "ord_dt",
            "order_date",
            "ccld_dt",
            "trad_dt",
            "trade_date",
            "rsvn_ord_rcit_dt",
        ], start_date) or start_date).replace("-", "")[:8]
        order_time = str(self._first_ci(item, [
            "ord_tmd",
            "order_time",
            "ccld_tmd",
            "trad_tmd",
            "trade_time",
            "ord_rcit_tmd",
        ], "") or "").replace(":", "")[:6]
        order_qty = self._safe_int(self._first_ci(item, [
            "ft_ord_qty",
            "ord_qty",
            "order_qty",
            "qty",
            "ord_rsvn_qty",
        ], 0), 0)
        filled_qty = self._safe_int(self._first_ci(item, [
            "ft_ccld_qty",
            "ccld_qty",
            "tot_ccld_qty",
            "ccld_qty_smtl",
            "exec_qty",
            "filled_qty",
            "ft_ccld_qty1",
        ], 0), 0)
        order_price = self._safe_float(self._first_ci(item, [
            "ft_ord_unpr3",
            "ord_unpr",
            "ovrs_ord_unpr",
            "order_price",
            "price",
            "ord_rsvn_unpr",
        ], 0), 0)
        filled_price = self._safe_float(self._first_ci(item, [
            "ft_ccld_unpr3",
            "ccld_unpr",
            "avg_pric",
            "exec_pric",
            "filled_price",
            "ft_ccld_unpr",
        ], 0), 0)
        filled_amount = self._safe_float(self._first_ci(item, [
            "ft_ccld_amt3",
            "ccld_amt",
            "exec_amt",
            "filled_amount",
            "ft_ccld_amt",
        ], 0), 0)
        if filled_price <= 0 and filled_qty > 0 and filled_amount > 0:
            filled_price = filled_amount / filled_qty
        if filled_amount <= 0 and filled_qty > 0 and filled_price > 0:
            filled_amount = filled_qty * filled_price

        return {
            "order_no": order_no,
            "symbol": item_symbol,
            "market": "US",
            "exchange": str(self._first_ci(item, ["ovrs_excg_cd", "exchange"], exchange) or exchange).upper(),
            "order_date": order_date,
            "order_time": order_time,
            "action": action,
            "side": action,
            "ord_qty": order_qty,
            "order_qty": order_qty,
            "order_price": order_price,
            "filled_qty": filled_qty,
            "filled_price": filled_price,
            "filled_amount": filled_amount,
            "status": self._normalize_overseas_ccnl_status(item),
            "broker": "KIS",
            "raw": item,
        }

    def _overseas_fill_signature(self, order):
        row = order if isinstance(order, dict) else {}
        return ":".join([
            str(row.get("symbol", "") or "").upper(),
            str(row.get("action", row.get("side", "")) or "").upper(),
            str(row.get("order_date", "") or "").replace("-", "")[:8],
            str(self._safe_int(row.get("filled_qty", 0), 0)),
            f"{self._safe_float(row.get('filled_price', 0), 0):.4f}",
        ])

    def _overseas_reservation_history_rows(self, start_date, end_date, exchanges):
        try:
            reservations = self.get_overseas_reservation_orders(start_date=start_date, end_date=end_date, exchanges=exchanges) or []
        except Exception as e:
            self._log("warning", f"Filled reservation fallback failed: {e}")
            return []

        rows = []
        for item in reservations:
            if not isinstance(item, dict):
                continue
            filled_qty = self._safe_int(item.get("filled_qty", 0), 0)
            filled_price = self._safe_float(item.get("filled_price", item.get("price", 0)), 0)
            if filled_qty <= 0 or filled_price <= 0:
                continue
            qty = self._safe_int(item.get("qty", filled_qty), filled_qty)
            side = self._normalize_overseas_action(item) or str(item.get("side", "") or "").upper()
            order_date = str(item.get("order_date") or item.get("filled_date") or item.get("receipt_date") or start_date).replace("-", "")[:8]
            order_time = str(item.get("order_time") or item.get("forward_time") or item.get("receipt_time") or "").replace(":", "")[:6]
            rows.append({
                "order_no": str(item.get("order_no") or item.get("reserve_order_no") or "").strip(),
                "symbol": str(item.get("symbol", "") or "").strip().upper(),
                "market": "US",
                "exchange": str(item.get("exchange", "") or "NASD").upper(),
                "order_date": order_date,
                "order_time": order_time,
                "action": side,
                "side": side,
                "ord_qty": qty,
                "order_qty": qty,
                "order_price": self._safe_float(item.get("price", filled_price), filled_price),
                "filled_qty": filled_qty,
                "filled_price": filled_price,
                "filled_amount": filled_qty * filled_price,
                "status": "PARTIAL" if qty > filled_qty else "FILLED",
                "broker": "KIS",
                "source": "reservation_filled_fallback",
                "raw": item,
            })
        return rows

    def get_overseas_order_history(self, start_date=None, end_date=None, symbol="", exchanges=None):
        """해외주식 체결/미체결 내역 조회 (NASD/NYSE/AMEX 전체, 페이지네이션 지원)."""
        tr_id = "TTTS3035R" if self.is_real else "VTTS3035R"
        path = "/uapi/overseas-stock/v1/trading/inquire-ccnl"

        if not start_date:
            start_date = _TIME.today("%Y%m%d")
        if not end_date:
            end_date = start_date

        exchanges = exchanges or ["NASD", "NYSE", "AMEX"]
        symbol = str(symbol or "").strip().upper()
        # KIS occasionally omits recent reservation-origin fills when PDNO is set.
        # Query the requested symbol first, then the all-symbol view and filter locally.
        pdno_values = [symbol, ""] if symbol else ["", "%"]
        orders = []
        seen = set()
        fill_seen = set()
        errors = []
        attempted_queries = 0
        failed_queries = 0

        for pdno_value in pdno_values:
            if pdno_value == "%" and orders:
                break
            for exchange in exchanges:
                ctx_nk = ""
                ctx_fk = ""
                for _ in range(10):
                    params = {
                        "CANO": self.account_prefix,
                        "ACNT_PRDT_CD": self.account_suffix,
                        "PDNO": pdno_value,
                        "ORD_STRT_DT": start_date,
                        "ORD_END_DT": end_date,
                        "SLL_BUY_DVSN": "00",
                        "CCLD_NCCS_DVSN": "00",
                        "OVRS_EXCG_CD": exchange,
                        "SORT_SQN": "DS",
                        "ORD_DT": "",
                        "ORD_GNO_BRNO": "",
                        "ODNO": "",
                        "CTX_AREA_NK200": ctx_nk,
                        "CTX_AREA_FK200": ctx_fk,
                    }

                    attempted_queries += 1
                    data = self._request("GET", path, tr_id, params=params)
                    if not data or data.get("rt_cd") != "0":
                        failed_queries += 1
                        msg = data.get("msg1", "Unknown error") if data else "No response"
                        errors.append(f"{exchange}/{pdno_value or 'ALL'}:{msg}")
                        break

                    for item in self._overseas_ccnl_rows(data):
                        order = self._normalize_overseas_ccnl_row(item, exchange, start_date)
                        if not order:
                            continue
                        item_symbol = str(order.get("symbol", "") or "").upper()
                        if symbol and item_symbol != symbol:
                            continue
                        action = str(order.get("action", "") or "").upper()
                        order_date = str(order.get("order_date", "") or start_date)
                        order_time = str(order.get("order_time", "") or "")[:6]
                        filled_qty = self._safe_int(order.get("filled_qty", 0), 0)
                        filled_price = self._safe_float(order.get("filled_price", 0), 0)
                        dedup_key = f"{order.get('exchange', exchange)}:{order.get('order_no', '')}:{item_symbol}:{action}:{order_date}:{order_time}:{filled_qty}:{filled_price}"
                        if dedup_key in seen:
                            continue
                        seen.add(dedup_key)
                        fill_seen.add(self._overseas_fill_signature(order))
                        orders.append(order)

                    next_nk = str(data.get("ctx_area_nk200", data.get("CTX_AREA_NK200", "")) or "")
                    next_fk = str(data.get("ctx_area_fk200", data.get("CTX_AREA_FK200", "")) or "")
                    tr_cont = str(data.get("tr_cont", "") or "")
                    if (next_nk == "" and next_fk == "") or tr_cont in ("", "D", "E"):
                        break
                    if next_nk == ctx_nk and next_fk == ctx_fk:
                        break
                    ctx_nk = next_nk
                    ctx_fk = next_fk

        for order in self._overseas_reservation_history_rows(start_date, end_date, exchanges):
            item_symbol = str(order.get("symbol", "") or "").upper()
            if symbol and item_symbol != symbol:
                continue
            fill_signature = self._overseas_fill_signature(order)
            if fill_signature in fill_seen:
                continue
            dedup_key = (
                f"{order.get('exchange', '')}:{order.get('order_no', '')}:{item_symbol}:"
                f"{order.get('action', '')}:{order.get('order_date', '')}:{order.get('order_time', '')}:"
                f"{order.get('filled_qty', 0)}:{order.get('filled_price', 0)}"
            )
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            fill_seen.add(fill_signature)
            orders.append(order)

        if len(orders) == 0 and attempted_queries > 0 and failed_queries == attempted_queries:
            raise Exception(f"해외 체결 조회 실패: {' | '.join(errors)}")

        return sorted(orders, key=lambda x: (x.get("order_date", ""), x.get("order_time", ""), x.get("order_no", "")))

    def get_overseas_fills_by_date(self, start_date=None, end_date=None, symbol="", exchanges=None):
        return self.get_overseas_order_history(start_date=start_date, end_date=end_date, symbol=symbol, exchanges=exchanges)

    def get_order_history(self, start_date=None, end_date=None):
        """레거시 호환용 해외 체결/미체결 내역 조회."""
        return self.get_overseas_order_history(start_date=start_date, end_date=end_date)

    # =========================================================================
    # 주문 가능 금액 (예수금) 조회
    # =========================================================================

    def get_buying_power(self, symbol="TQQQ", price=0, exchange="NASD"):
        """
        해외주식 주문 가능 금액 (USD) 조회
        """
        info = self.get_buying_power_info(symbol=symbol, price=price, exchange=exchange)
        return float(info.get("amount", 0))

    def get_buying_power_info(self, symbol="TQQQ", price=0, exchange="NASD"):
        """주문 가능 금액(USD) 조회 상세 정보"""
        tr_id = "TTTS3007R" if self.is_real else "VTTS3007R"
        path = "/uapi/overseas-stock/v1/trading/inquire-psamount"

        symbol = str(symbol or "TQQQ").upper()
        exchange = str(exchange or "NASD").upper()
        price = self._safe_float(price, 0)
        if price <= 0:
            price_exchange_map = {"NASD": "NAS", "NYSE": "NYS", "AMEX": "AMS", "NAS": "NAS", "NYS": "NYS", "AMS": "AMS"}
            price_exchange = price_exchange_map.get(exchange, "NAS")
            try:
                current = self.get_current_price(symbol, exchange=price_exchange)
                price = self._safe_float(current.get("price", 0), 0)
            except Exception:
                price = 50

        params = {
            "CANO": self.account_prefix,
            "ACNT_PRDT_CD": self.account_suffix,
            "OVRS_EXCG_CD": exchange,
            "OVRS_ORD_UNPR": str(price),
            "ITEM_CD": symbol,
        }

        data = self._request("GET", path, tr_id, params=params)
        if not data or data.get("rt_cd") != "0":
            msg = data.get("msg1", "Unknown error") if data else "No response"
            rt_cd = data.get("rt_cd", "?") if data else "no_data"
            self._log("warning", f"get_buying_power_info failed [{symbol}:{exchange}] rt_cd={rt_cd}, msg={msg}")
            try:
                balance = self.get_balance() or {}
                cash_balance = self._safe_float(balance.get("cash_balance", 0), 0)
                fallback_qty = int(cash_balance / price) if price > 0 and cash_balance > 0 else 0
                if cash_balance > 0:
                    return {
                        "amount": cash_balance,
                        "qty": max(0, fallback_qty),
                        "ok": True,
                        "message": f"USD 주문 가능액 API fallback 사용: rt_cd={rt_cd}, msg={msg}",
                        "source": "balance.cash_balance",
                        "symbol": symbol,
                        "exchange": exchange,
                        "price": price,
                        "raw": {"rt_cd": rt_cd, "msg1": msg, "fallback_cash_balance": cash_balance},
                    }
            except Exception as fallback_error:
                self._log("warning", f"get_buying_power_info fallback failed [{symbol}:{exchange}]: {fallback_error}")
            return {
                "amount": 0.0,
                "ok": False,
                "message": f"USD 주문 가능액 조회 실패: rt_cd={rt_cd}, msg={msg}",
                "source": "inquire-psamount",
                "symbol": symbol,
                "exchange": exchange,
                "price": price,
            }

        output = data.get("output", {})
        amount_candidates = {
            "ovrs_ord_psbl_amt": self._safe_float(output.get("ovrs_ord_psbl_amt", 0), 0),
            "ord_psbl_frcr_amt": self._safe_float(output.get("ord_psbl_frcr_amt", 0), 0),
            "frcr_ord_psbl_amt1": self._safe_float(output.get("frcr_ord_psbl_amt1", 0), 0),
        }
        qty_candidates = {
            "max_ord_psbl_qty": self._safe_int(output.get("max_ord_psbl_qty", 0), 0),
            "ord_psbl_qty": self._safe_int(output.get("ord_psbl_qty", 0), 0),
            "ovrs_max_ord_psbl_qty": self._safe_int(output.get("ovrs_max_ord_psbl_qty", 0), 0),
        }
        amount_source, broker_amount = max(amount_candidates.items(), key=lambda item: item[1])
        qty_source, broker_qty = max(qty_candidates.items(), key=lambda item: item[1])
        exchange_after_amount = self._safe_float(output.get("echm_af_ord_psbl_amt", 0), 0)
        exchange_after_qty = self._safe_int(output.get("echm_af_ord_psbl_qty", 0), 0)

        def _qty_from_amount(amount):
            if price <= 0 or amount <= 0:
                return 0
            return max(0, int(float(amount) / float(price)))

        # 원화 자동환전은 KIS의 환전이후주문가능 필드만 실주문 가능액으로 인정한다.
        # 원화 출금가능액 환산값은 화면/진단용 추정치로만 남긴다.
        cash_balance = 0.0
        krw_auto_exchange_estimate_usd = 0.0
        try:
            balance = self.get_balance() or {}
            cash_balance = self._safe_float(balance.get("cash_balance", 0), 0)
        except Exception:
            cash_balance = 0.0
        try:
            present = self.get_present_balance() or {}
            usd_krw = self._safe_float(present.get("usd_krw", 0), 0)
            withdrawable_krw = self._safe_float(present.get("withdrawable_krw", present.get("krw_balance", 0)), 0)
            if usd_krw > 0 and withdrawable_krw > 0:
                krw_auto_exchange_estimate_usd = withdrawable_krw / usd_krw
        except Exception:
            krw_auto_exchange_estimate_usd = 0.0

        auto_exchange_ready = self._us_auto_exchange_ready()
        executable_amount = broker_amount
        executable_qty = broker_qty
        source = amount_source or "ovrs_ord_psbl_amt"
        resolved_qty_source = qty_source or ""
        if exchange_after_amount > broker_amount + 0.01:
            executable_amount = exchange_after_amount
            executable_qty = max(broker_qty, exchange_after_qty)
            source = "echm_af_ord_psbl_amt"
            if exchange_after_qty > broker_qty:
                resolved_qty_source = "echm_af_ord_psbl_qty"
        elif exchange_after_qty > executable_qty:
            executable_qty = exchange_after_qty
            resolved_qty_source = "echm_af_ord_psbl_qty"

        amount_implied_qty = _qty_from_amount(executable_amount)
        if executable_qty <= 0 and amount_implied_qty > 0:
            executable_qty = amount_implied_qty
            resolved_qty_source = f"{source}:amount_implied_qty"
        elif amount_implied_qty > 0 and executable_qty > amount_implied_qty:
            executable_qty = amount_implied_qty
            resolved_qty_source = f"{resolved_qty_source or source}:amount_cap"

        auto_exchange_usd = max(0.0, executable_amount - broker_amount)
        auto_exchange_included = bool(auto_exchange_ready and auto_exchange_usd > 0.01)
        estimated_amount = max(executable_amount, broker_amount, cash_balance)
        if krw_auto_exchange_estimate_usd > 0:
            estimated_amount = max(estimated_amount, max(broker_amount, cash_balance) + krw_auto_exchange_estimate_usd)
        estimated_qty = max(executable_qty, _qty_from_amount(estimated_amount))

        estimated_source = source
        message = ""
        if source == "echm_af_ord_psbl_amt":
            estimated_source = "echm_af_ord_psbl_amt"
            message = (
                f"KIS 환전이후 주문가능액 사용: ${executable_amount:.2f} "
                f"(기본 주문가능 ${broker_amount:.2f})"
            )
        elif krw_auto_exchange_estimate_usd > 0:
            estimated_source = f"{source}+krw_auto_exchange_estimate"
            message = (
                f"원화 자동환전 추정 ${krw_auto_exchange_estimate_usd:.2f}는 "
                f"KIS 환전이후주문가능액에 미반영되어 참고값으로만 사용"
            )
        elif executable_qty > 0 and broker_qty <= 0 and amount_implied_qty > 0:
            message = (
                f"KIS 수량 필드가 0이라 {source} ${executable_amount:.2f}와 "
                f"현재가 ${price:.2f} 기준 가능수량 {executable_qty}주로 산출"
            )

        return {
            "amount": executable_amount,
            "qty": executable_qty,
            "broker_amount": broker_amount,
            "broker_qty": broker_qty,
            "executable_amount": executable_amount,
            "executable_qty": executable_qty,
            "exchange_after_amount": exchange_after_amount,
            "exchange_after_qty": exchange_after_qty,
            "auto_exchange_ready": auto_exchange_ready,
            "auto_exchange_included": auto_exchange_included,
            "estimated_amount": estimated_amount,
            "estimated_qty": estimated_qty,
            "cash_balance": cash_balance,
            "auto_exchange_usd": auto_exchange_usd,
            "krw_auto_exchange_estimate_usd": krw_auto_exchange_estimate_usd,
            "ok": True,
            "message": message,
            "source": source,
            "estimated_source": estimated_source,
            "qty_source": resolved_qty_source,
            "symbol": symbol,
            "exchange": exchange,
            "price": price,
            "raw": {
                "output": output,
                "cash_balance": cash_balance,
                "auto_exchange_usd": auto_exchange_usd,
                "krw_auto_exchange_estimate_usd": krw_auto_exchange_estimate_usd,
                "broker_amount": broker_amount,
                "broker_qty": broker_qty,
                "exchange_after_amount": exchange_after_amount,
                "exchange_after_qty": exchange_after_qty,
                "amount_implied_qty": amount_implied_qty,
                "executable_amount": executable_amount,
                "executable_qty": executable_qty,
                "auto_exchange_ready": auto_exchange_ready,
                "auto_exchange_included": auto_exchange_included,
                "estimated_qty": estimated_qty,
                "estimated_amount": estimated_amount,
                "amount_candidates": amount_candidates,
                "qty_candidates": qty_candidates,
            },
        }

    def get_present_balance(self):
        """
        해외주식 현재잔고/환율 조회
        반환: dict {usd_krw, krw_balance, withdrawable_krw, raw}
        """
        tr_id = "CTRP6504R"
        path = "/uapi/overseas-stock/v1/trading/inquire-present-balance"
        params = {
            "CANO": self.account_prefix,
            "ACNT_PRDT_CD": self.account_suffix,
            # KIS 문서: 01=원화, 02=외화
            # 원화 잔액/출금가능금액을 읽으려면 반드시 01로 조회해야 한다.
            "WCRC_FRCR_DVSN_CD": "01",
            "NATN_CD": "840",
            "TR_MKET_CD": "00",
            "INQR_DVSN_CD": "00",
        }

        data = self._request("GET", path, tr_id, params=params)
        if not data or data.get("rt_cd") != "0":
            msg = data.get("msg1", "Unknown error") if data else "No response"
            rt_cd = data.get("rt_cd", "?") if data else "no_data"
            raise Exception(f"get_present_balance API failed: rt_cd={rt_cd}, msg={msg}")

        # KIS 문서 기준
        # - output2: Array (통화별 상세)
        # - output3: Object (합계/원화 요약)
        output2 = data.get("output2", [])
        output3 = data.get("output3", {})

        currency_row = {}
        if isinstance(output2, list) and len(output2) > 0:
            currency_row = output2[0] or {}
        elif isinstance(output2, dict):
            currency_row = output2

        summary_row = output3 if isinstance(output3, dict) else {}

        if not currency_row and not summary_row:
            self._log("error", f"get_present_balance: output2/output3 empty. keys={list(data.keys())}")
            raise Exception(f"get_present_balance: output2/output3 empty. Response keys: {list(data.keys())}")

        # 원화 합계는 output3를 우선 사용, 환율은 output2를 우선 사용
        row = {}
        row.update(summary_row)
        row.update(currency_row)

        # 디버깅: 실제 API 응답의 모든 키와 값 로깅 (원화 관련)
        krw_keys = {k: v for k, v in row.items() if v and str(v) != "0" and str(v) != "0.00"}
        self._log("info", f"present_balance non-zero fields: {krw_keys}")

        krw_info = self._pick_amount_info(row, [
            # 실제 원화 예수금/잔고 계열만 사용한다.
            # wdrw_psbl_tot_amt / ord_psbl_krw_amt 는 주문·출금 가능액이라 총자산 계산에 쓰면 부풀 수 있다.
            "tot_dncl_amt",
            "dncl_amt",
            "krw_dncl_amt",
            "dnca_tot_amt",
            "frcr_dncl_amt_2",
            "krw_evlu_amt",
            "krw_amt",
        ])
        withdrawable_info = self._pick_amount_info(row, [
            # output3 요약 필드 우선
            "wdrw_psbl_tot_amt",
            # output2 / 기타 후보
            "ord_psbl_krw_amt",
            "krw_ord_psbl_amt",
            "withdrawable_krw",
            "nxdy_krw_auto_xchg_amt",
            "krw_buy_mgn_amt",
            "krw_dncl_amt",
            "frcr_dncl_amt_2",
            "frcr_evlu_amt2",
            # 추가 후보 키
            "tot_dncl_amt",
            "dnca_tot_amt",
            "dncl_amt",
        ])
        krw_balance = krw_info["value"]
        withdrawable_krw = withdrawable_info["value"]

        total_asset_info = self._pick_amount_info(summary_row, [
            "tot_asst_amt",
            "tot_evlu_amt",
            "nass_amt",
            "bfdy_tot_asst_evlu_amt",
        ])
        total_asset_krw = self._safe_float(total_asset_info.get("value", 0), 0)
        portfolio_eval_info = self._pick_amount_info(summary_row, [
            "evlu_amt_smtl_amt",
            "evlu_amt_smtl",
            "frcr_evlu_amt2",
        ])
        portfolio_eval_krw = self._safe_float(portfolio_eval_info.get("value", 0), 0)
        unsettled_buy_info = self._pick_amount_info(summary_row, [
            "ustl_buy_amt_smtl",
            "ustl_buy_amt_smtl_amt",
            "frcr_buy_amt_smtl",
        ])
        unsettled_sell_info = self._pick_amount_info(summary_row, [
            "ustl_sll_amt_smtl",
            "ustl_sll_amt_smtl_amt",
            "frcr_sll_amt_smtl",
        ])

        exchange_rate_source = "present_balance"
        usd_krw = self._safe_float(currency_row.get("frst_bltn_exrt", row.get("frst_bltn_exrt", 0)))
        # 환율이 0이면 대체 키 시도
        if usd_krw <= 0:
            usd_krw = self._safe_float(currency_row.get("bass_exrt", row.get("bass_exrt", 0)))
        if usd_krw <= 0:
            usd_krw = self._safe_float(currency_row.get("exrt", row.get("exrt", 0)))
        if usd_krw <= 0:
            fx_fallback = self._get_usd_krw_rate_fallback()
            usd_krw = self._safe_float(fx_fallback.get("rate", 0))
            if usd_krw > 0:
                exchange_rate_source = fx_fallback.get("source", "fallback")

        self._log("info", f"KRW balance={krw_balance}, withdrawable={withdrawable_krw}, usd_krw={usd_krw}, source={exchange_rate_source}")

        return {
            "usd_krw": usd_krw,
            "krw_balance": krw_balance,
            "withdrawable_krw": withdrawable_krw if withdrawable_krw > 0 else krw_balance,
            "total_asset_krw": total_asset_krw,
            "portfolio_eval_krw": portfolio_eval_krw,
            "unsettled_buy_krw": self._safe_float(unsettled_buy_info.get("value", 0), 0),
            "unsettled_sell_krw": self._safe_float(unsettled_sell_info.get("value", 0), 0),
            "meta": {
                "krw_key": krw_info["key"],
                "withdrawable_key": withdrawable_info["key"],
                "total_asset_key": total_asset_info.get("key"),
                "portfolio_eval_key": portfolio_eval_info.get("key"),
                "unsettled_buy_key": unsettled_buy_info.get("key"),
                "unsettled_sell_key": unsettled_sell_info.get("key"),
                "krw_present": krw_info["present"],
                "withdrawable_present": withdrawable_info["present"],
                "total_asset_present": total_asset_krw > 0,
                "portfolio_eval_present": portfolio_eval_krw > 0,
                "exchange_rate_present": usd_krw > 0,
                "exchange_rate_source": exchange_rate_source,
            },
            "raw": {
                "output2": currency_row,
                "output3": summary_row,
                "merged": row,
            },
        }

    def get_krw_balance(self):
        """자동환전 주문에 사용할 수 있는 원화 잔고"""
        data = self.get_present_balance()
        return float(data.get("withdrawable_krw", data.get("krw_balance", 0)))

    # =========================================================================
    # 환율 정보
    # =========================================================================

    def get_exchange_rate(self):
        """
        환율 조회 (USD/KRW)
        """
        data = self.get_present_balance()
        return {"usd_krw": float(data.get("usd_krw", 0))}

    # =========================================================================
    # 국내주식 주문 취소
    # =========================================================================

    def cancel_domestic_order(self, order_no, symbol, qty, org_branch_no=""):
        """
        국내주식 지정가 주문 취소
        TR: TTTC0803U (real) / VTTC0803U (paper)
        """
        tr_id = "TTTC0803U" if self.is_real else "VTTC0803U"
        path = "/uapi/domestic-stock/v1/trading/order-rvsecncl"
        cano = self.account_prefix
        acnt_cd = self.account_suffix
        if not cano or not acnt_cd:
            raise Exception("주문 취소를 위한 계좌번호가 올바르지 않습니다.")
        body = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_cd,
            "KRX_FWDG_ORD_ORGNO": org_branch_no or "",
            "ORGN_ODNO": str(order_no),
            "ORD_DVSN": "00",           # 지정가
            "RVSE_CNCL_DVSN_CD": "02",  # 02=취소
            "ORD_QTY": str(int(qty)),
            "ORD_UNPR": "0",
            "QTY_ALL_ORD_YN": "Y",      # 전량 취소
        }
        data = self._request("POST", path, tr_id, body=body)
        if not data or data.get("rt_cd") != "0":
            msg = data.get("msg1", "Unknown error") if data else "No response"
            raise Exception(f"주문 취소 실패 [주문번호 {order_no}]: {msg}")
        output = data.get("output", {})
        return {
            "cancel_order_no": output.get("ODNO", ""),
            "original_order_no": str(order_no),
            "symbol": symbol,
        }

    # =========================================================================
    # 국내주식 당일 체결 조회
    # =========================================================================

    def get_domestic_fills_today(self, symbol=""):
        """
        당일 국내주식 주문/체결 내역 조회
        TR: TTTC8001R (real) / VTTC8001R (paper)

        Returns: list of dict
          {order_no, symbol, side, ord_qty, filled_qty, filled_price, rmn_qty, status}
          status: "OPEN" | "PARTIAL" | "FILLED" | "CANCELLED"
        """
        tr_id = "TTTC8001R" if self.is_real else "VTTC8001R"
        path = "/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
        cano = self.account_prefix
        acnt_cd = self.account_suffix
        today = _TIME.today("%Y%m%d")
        rows = []
        ctx_fk = ""
        ctx_nk = ""
        for _ in range(10):
            params = {
                "CANO": cano,
                "ACNT_PRDT_CD": acnt_cd,
                "INQR_STRT_DT": today,
                "INQR_END_DT": today,
                "SLL_BUY_DVSN_CD": "00",   # 전체 (매도+매수)
                "INQR_DVSN": "00",
                "PDNO": symbol or "",
                "CCLD_DVSN": "00",          # 전체 (체결+미체결)
                "ORD_GNO_BRNO": "",
                "ODNO": "",
                "INQR_DVSN_3": "00",
                "INQR_DVSN_1": "",
                "CTX_AREA_FK100": ctx_fk,
                "CTX_AREA_NK100": ctx_nk,
            }
            data = self._request("GET", path, tr_id, params=params)
            if not data:
                break
            page_rows = data.get("output1", []) or []
            rows.extend(page_rows)
            next_fk = data.get("ctx_area_fk100", data.get("CTX_AREA_FK100", "")) or ""
            next_nk = data.get("ctx_area_nk100", data.get("CTX_AREA_NK100", "")) or ""
            tr_cont = str(data.get("tr_cont", "") or "")
            if (next_fk == "" and next_nk == "") or tr_cont in ["", "D", "E"]:
                break
            if next_fk == ctx_fk and next_nk == ctx_nk:
                break
            ctx_fk = next_fk
            ctx_nk = next_nk

        result = []
        for row in rows:
            ord_qty      = int(row.get("ord_qty", 0) or 0)
            tot_ccld_qty = int(row.get("tot_ccld_qty", 0) or 0)
            tot_ccld_amt = float(row.get("tot_ccld_amt", 0) or 0)
            rmn_qty      = int(row.get("rmn_qty", 0) or 0)
            avg_filled   = round(tot_ccld_amt / tot_ccld_qty, 2) if tot_ccld_qty > 0 else 0.0
            # 체결 상태 판단
            if tot_ccld_qty == 0 and rmn_qty == 0:
                status = "CANCELLED"
            elif tot_ccld_qty == 0:
                status = "OPEN"
            elif rmn_qty == 0:
                status = "FILLED"
            else:
                status = "PARTIAL"
            sll_buy = str(row.get("sll_buy_dvsn_cd", "02") or "02")
            result.append({
                "order_no":     str(row.get("odno", "") or ""),
                "symbol":       str(row.get("pdno", "") or ""),
                "name":         str(row.get("prdt_name", "") or row.get("pd_name", "") or ""),
                "side":         "BUY" if sll_buy == "02" else "SELL",
                "ord_qty":      ord_qty,
                "filled_qty":   tot_ccld_qty,
                "filled_price": avg_filled,
                "rmn_qty":      rmn_qty,
                "status":       status,
            })
        return result

    def get_domestic_fills_by_date(self, start_date, end_date, symbol=""):
        """
        지정된 기간 동안의 국내주식 주문/체결 내역 조회
        - get_domestic_fills_today를 날짜별로 반복 호출하여 구현
        """
        s_date = datetime.datetime.strptime(start_date, "%Y%m%d")
        e_date = datetime.datetime.strptime(end_date, "%Y%m%d")
        delta = e_date - s_date

        all_fills = []
        for i in range(delta.days + 1):
            day = s_date + datetime.timedelta(days=i)
            day_str = day.strftime("%Y%m%d")
            
            # get_domestic_fills_today는 내부적으로 오늘 날짜를 사용하므로,
            # 날짜를 순회하며 조회하려면 임시로 날짜를 변경해야 함.
            # 이를 위해 get_domestic_fills_for_day 함수를 새로 만듭니다.
            try:
                fills = self.get_domestic_fills_for_day(day_str, symbol=symbol)
                all_fills.extend(fills)
            except Exception as e:
                self._log("warning", f"Failed to get fills for {day_str}: {e}")
        
        return all_fills

    def get_domestic_fills_for_day(self, date_str, symbol=""):
        """
        특정 날짜의 국내주식 주문/체결 내역 조회
        TR: TTTC8001R (real) / VTTC8001R (paper)
        """
        tr_id = "TTTC8001R" if self.is_real else "VTTC8001R"
        path = "/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
        cano = self.account_prefix
        acnt_cd = self.account_suffix
        
        rows = []
        ctx_fk = ""
        ctx_nk = ""

        for _ in range(10): # Paging
            params = {
                "CANO": cano,
                "ACNT_PRDT_CD": acnt_cd,
                "INQR_STRT_DT": date_str,
                "INQR_END_DT": date_str,
                "SLL_BUY_DVSN_CD": "00",
                "INQR_DVSN": "00",
                "PDNO": symbol or "",
                "CCLD_DVSN": "00",
                "ORD_GNO_BRNO": "",
                "ODNO": "",
                "INQR_DVSN_3": "00",
                "INQR_DVSN_1": "",
                "CTX_AREA_FK100": ctx_fk,
                "CTX_AREA_NK100": ctx_nk,
            }
            data = self._request("GET", path, tr_id, params=params)
            if not data:
                break
            
            page_rows = data.get("output1", []) or []
            rows.extend(page_rows)
            
            next_fk = data.get("ctx_area_fk100", data.get("CTX_AREA_FK100", "")) or ""
            next_nk = data.get("ctx_area_nk100", data.get("CTX_AREA_NK100", "")) or ""
            tr_cont = str(data.get("tr_cont", "") or "")

            if (not next_fk and not next_nk) or tr_cont in ["", "D", "E"]:
                break
            if next_fk == ctx_fk and next_nk == ctx_nk:
                break
            
            ctx_fk = next_fk
            ctx_nk = next_nk

        result = []
        for row in rows:
            ord_qty      = int(row.get("ord_qty", 0) or 0)
            tot_ccld_qty = int(row.get("tot_ccld_qty", 0) or 0)
            tot_ccld_amt = float(row.get("tot_ccld_amt", 0) or 0)
            rmn_qty      = int(row.get("rmn_qty", 0) or 0)
            avg_filled   = round(tot_ccld_amt / tot_ccld_qty, 2) if tot_ccld_qty > 0 else 0.0
            
            if tot_ccld_qty == 0 and rmn_qty == 0:
                status = "CANCELLED"
            elif tot_ccld_qty == 0:
                status = "OPEN"
            elif rmn_qty == 0:
                status = "FILLED"
            else:
                status = "PARTIAL"
            
            sll_buy = str(row.get("sll_buy_dvsn_cd", "02") or "02")
            
            result.append({
                "order_no":     str(row.get("odno", "") or ""),
                "symbol":       str(row.get("pdno", "") or ""),
                "side":         "BUY" if sll_buy == "02" else "SELL",
                "ord_qty":      ord_qty,
                "filled_qty":   tot_ccld_qty,
                "filled_price": avg_filled,
                "rmn_qty":      rmn_qty,
                "status":       status,
                "order_date":   str(row.get("ord_dt", "") or ""),
                "order_time":   str(row.get("ord_tmd", "") or ""),
            })
        return result

    def get_domestic_period_trade_profit(self, start_date, end_date, symbol=""):
        """국내주식 기간별매매손익현황조회 결과를 반환합니다."""
        tr_id = "TTTC8715R" if self.is_real else "VTTC8715R"
        path = "/uapi/domestic-stock/v1/trading/inquire-period-trade-profit"
        cano = self.account_prefix
        acnt_cd = self.account_suffix

        rows = []
        totals = {}
        ctx_fk = ""
        ctx_nk = ""

        for _ in range(10):
            params = {
                "CANO": cano,
                "ACNT_PRDT_CD": acnt_cd,
                "SORT_DVSN": "00",
                "INQR_STRT_DT": start_date,
                "INQR_END_DT": end_date,
                "CBLC_DVSN": "00",
                "PDNO": symbol or "",
                "CCLD_DVSN": "00",
                "CTX_AREA_FK100": ctx_fk,
                "CTX_AREA_NK100": ctx_nk,
            }

            data = self._request("GET", path, tr_id, params=params)
            if not data or data.get("rt_cd") != "0":
                msg = data.get("msg1", "Unknown error") if data else "No response"
                raise Exception(f"국내 기간 손익 조회 실패: {msg}")

            page_rows = data.get("output1", []) or []
            rows.extend(page_rows)

            output2 = data.get("output2", {}) or {}
            if isinstance(output2, list):
                totals = output2[0] if len(output2) > 0 else {}
            elif isinstance(output2, dict):
                totals = output2

            next_fk = data.get("ctx_area_fk100", data.get("CTX_AREA_FK100", "")) or ""
            next_nk = data.get("ctx_area_nk100", data.get("CTX_AREA_NK100", "")) or ""
            tr_cont = str(data.get("tr_cont", "") or "")
            if (not next_fk and not next_nk) or tr_cont in ["", "D", "E"]:
                break
            if next_fk == ctx_fk and next_nk == ctx_nk:
                break

            ctx_fk = next_fk
            ctx_nk = next_nk

        result_rows = []
        for row in rows:
            result_rows.append({
                "date": str(row.get("trad_dt", "") or ""),
                "symbol": str(row.get("pdno", "") or ""),
                "name": str(row.get("prdt_name", "") or ""),
                "holding_qty": self._safe_int(row.get("hldg_qty", 0), 0),
                "avg_price": self._safe_float(row.get("pchs_unpr", 0), 0),
                "buy_qty": self._safe_int(row.get("buy_qty", 0), 0),
                "buy_amount": self._safe_float(row.get("buy_amt", 0), 0),
                "sell_qty": self._safe_int(row.get("sll_qty", 0), 0),
                "sell_amount": self._safe_float(row.get("sll_amt", 0), 0),
                "sell_price": self._safe_float(row.get("sll_pric", 0), 0),
                "pnl": self._safe_float(row.get("rlzt_pfls", 0), 0),
                "pnl_rate": self._safe_float(row.get("pfls_rt", 0), 0),
                "fee": self._safe_float(row.get("fee", 0), 0),
                "tax": self._safe_float(row.get("tl_tax", 0), 0),
                "loan_interest": self._safe_float(row.get("loan_int", 0), 0),
            })

        total_fee = self._safe_float(totals.get("tot_fee", 0), 0)
        total_tax = self._safe_float(totals.get("tot_tltx", 0), 0)
        total_loan_interest = self._safe_float(totals.get("loan_int", 0), 0)
        return {
            "rows": result_rows,
            "totals": {
                "sell_qty": self._safe_int(totals.get("sll_qty_smtl", 0), 0),
                "sell_amount": self._safe_float(totals.get("sll_tr_amt_smtl", 0), 0),
                "buy_qty": self._safe_int(totals.get("buyqty_smtl", 0), 0),
                "buy_amount": self._safe_float(totals.get("buy_tr_amt_smtl", 0), 0),
                "fee": total_fee,
                "tax": total_tax,
                "loan_interest": total_loan_interest,
                "cost_total": total_fee + total_tax + total_loan_interest,
                "pnl": self._safe_float(totals.get("tot_rlzt_pfls", 0), 0),
            },
        }


Model = KisApi
