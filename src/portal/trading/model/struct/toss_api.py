# =============================================================================
# Toss Securities Open API wrapper
# =============================================================================
# KIS wrapper와 같은 메서드 표면을 제공해서 무한매수 엔진이 브로커를
# 바꿔도 LOC 주문/잔고/체결 동기화를 같은 방식으로 호출할 수 있게 한다.
# Official docs: https://developers.tossinvest.com/docs
# =============================================================================
import datetime
import time
import threading
import re
import base64

_TIME = wiz.model("portal/trading/kst")

try:
    import requests
except ImportError:
    requests = None


BASE_URL = "https://openapi.tossinvest.com"
TOKEN_PATH = "/oauth2/token"


class TossApi:
    """토스증권 Open API 래퍼."""

    _last_request_time = 0.0
    _min_request_interval = 0.12
    ORDER_EXCHANGE_MAP = {"NAS": "NASD", "NYS": "NYSE", "AMS": "AMEX"}
    PRICE_EXCHANGE_MAP = {"NASD": "NAS", "NYSE": "NYS", "AMEX": "AMS"}

    def __init__(self, struct):
        self.struct = struct
        self._token = None
        self._token_expires = None
        self._token_scope = ""
        self._last_token_debug = None
        self._last_api_debug = []
        self._logger = None

    @property
    def broker_name(self):
        return "toss"

    @property
    def logger(self):
        if self._logger is None:
            try:
                self._logger = wiz.logger("trading", "toss_api")
            except Exception:
                self._logger = None
        return self._logger

    def _log(self, level, msg):
        try:
            if self.logger:
                getattr(self.logger, level, self.logger.info)(msg)
        except Exception:
            pass

    def _get_config(self, key, default=""):
        return self.struct.get_config(key, default)

    def _set_config(self, key, value, description="", is_secret=False):
        self.struct.set_config(key, str(value), description=description, is_secret=is_secret)

    @property
    def client_id(self):
        return self._get_config("toss_client_id")

    @property
    def client_secret(self):
        return self._get_config("toss_client_secret")

    @property
    def account_seq(self):
        value = str(self._get_config("toss_account_seq", "") or "").strip()
        if value:
            return value
        accounts = self.list_accounts()
        if not accounts:
            return ""
        account = accounts[0]
        seq = str(account.get("accountSeq", "") or "").strip()
        if seq:
            self._set_config("toss_account_seq", seq, "토스증권 계좌 일련번호", True)
            account_no = str(account.get("accountNo", "") or "").strip()
            if account_no:
                self._set_config("toss_account_no", account_no, "토스증권 계좌번호", True)
        return seq

    def _safe_float(self, value, default=0.0):
        try:
            if value is None or value == "":
                return float(default)
            return float(str(value).replace(",", "").strip())
        except Exception:
            return float(default)

    def _safe_int(self, value, default=0):
        try:
            if value is None or value == "":
                return int(default)
            return int(float(str(value).replace(",", "").strip()))
        except Exception:
            return int(default)

    def _rate_limit_wait(self):
        now = time.time()
        elapsed = now - TossApi._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        TossApi._last_request_time = time.time()

    def _issue_token(self):
        if requests is None:
            raise Exception("requests 패키지가 설치되어 있지 않습니다.")
        if not self.client_id or not self.client_secret:
            raise Exception("토스증권 API key 또는 Secret key가 설정되어 있지 않습니다.")
        scope = self._credential_scope()
        debug = {
            "endpoint": f"{BASE_URL}{TOKEN_PATH}",
            "key_shape": self._credential_shape_debug(),
            "source": self._credential_source(),
            "authMode": "basic",
            "attempts": [],
        }
        last_code = ""
        last_message = ""
        last_status = ""
        data = {}
        attempt = self._token_attempt_spec()
        try:
            resp = requests.post(f"{BASE_URL}{TOKEN_PATH}", **attempt["kwargs"])
            data, code, message = self._response_error_fields(resp)
            status = getattr(resp, "status_code", 200)
            last_code = code
            last_message = message
            last_status = status
            debug["attempts"].append(self._token_attempt_debug(attempt, resp, code, message))
            if status >= 400:
                data = {}
        except Exception as e:
            last_code = "request_error"
            last_message = str(e)
            last_status = ""
            debug["attempts"].append(self._token_attempt_debug(attempt, None, last_code, last_message))
            data = {}

        self._last_token_debug = debug
        token = data.get("access_token")
        if not token:
            self._mark_token_missing_if_needed(debug)
            friendly = self._friendly_error_message(last_code, last_message, last_status)
            detail = self._token_debug_summary(debug)
            if friendly:
                raise Exception(f"{friendly} {detail}")
            raise Exception(f"토스증권 접근 토큰 발급에 실패했습니다. {detail}")
        expires_in = int(float(data.get("expires_in", 86400) or 86400))
        self._token = token
        self._token_expires = time.time() + expires_in - 300
        self._token_scope = scope
        self._set_config("toss_access_token", token, "토스증권 접근 토큰", True)
        self._set_config("toss_token_expires", str(self._token_expires), "토스증권 토큰 만료시각")
        return token

    def _basic_auth_value(self):
        raw = f"{self.client_id}:{self.client_secret}".encode("utf-8")
        return "Basic " + base64.b64encode(raw).decode("ascii")

    def _token_attempt_spec(self):
        return {
            "name": "curl-equivalent",
            "description": "curl 동일 Basic 토큰 요청",
            "authMode": "basic",
            "kwargs": {
                "data": {"grant_type": "client_credentials"},
                "headers": {
                    "Authorization": self._basic_auth_value(),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                "timeout": 10,
            },
        }

    def _credential_shape_debug(self):
        def shape(value, expected_prefix):
            text = str(value or "").strip()
            return {
                "prefix10": text[:10],
                "length": len(text),
                "expected_prefix": expected_prefix,
                "prefix_ok": text.startswith(expected_prefix),
            }
        return {
            "api_key": shape(self.client_id, "tsck_"),
            "secret_key": shape(self.client_secret, "tssk_"),
        }

    def _response_error_fields(self, resp):
        try:
            data = resp.json()
        except Exception:
            data = {}
        code = ""
        message = ""
        if isinstance(data, dict):
            err = data.get("error", {})
            if isinstance(err, dict):
                code = err.get("code") or data.get("code") or ""
                message = err.get("message") or err.get("error_description") or data.get("error_description") or data.get("message") or ""
            else:
                code = data.get("code") or data.get("error") or ""
                message = data.get("error_description") or data.get("message") or str(err or "")
        else:
            message = str(data or "")
        if not message:
            message = str(getattr(resp, "text", "") or "")
        return data if isinstance(data, dict) else {}, str(code or ""), str(message or "")

    def _token_attempt_debug(self, attempt, resp, code="", message=""):
        status = getattr(resp, "status_code", "") if resp is not None else ""
        headers = getattr(resp, "headers", {}) if resp is not None else {}
        www_auth = ""
        try:
            www_auth = headers.get("WWW-Authenticate", "") or headers.get("www-authenticate", "")
        except Exception:
            www_auth = ""
        status_int = int(status or 0)
        code_text = str(code or "").lower()
        error_text = str(message or "").lower()
        if resp is None:
            classification = "앱 구현 문제"
        elif status_int == 401 or "invalid_client" in (code_text, error_text):
            classification = "토스 키 세트/권한 문제"
        elif status_int == 403 or "access_denied" in (code_text, error_text):
            classification = "토스 OpenAPI 이용 권한/약관/앱 활성화 문제"
        elif status_int >= 400:
            classification = "토스 응답 오류"
        elif code:
            classification = "앱 구현 문제"
        else:
            classification = "정상"
        return {
            "method": attempt.get("name", ""),
            "description": attempt.get("description", ""),
            "source": self._credential_source(),
            "authMode": attempt.get("authMode", "basic"),
            "endpoint": f"{BASE_URL}{TOKEN_PATH}",
            "status": status,
            "code": str(code or ""),
            "error": self._sanitize_debug_text(message or code),
            "www_authenticate": self._sanitize_debug_text(www_auth),
            "classification": classification,
        }

    def _mark_token_missing_if_needed(self, debug):
        attempts = debug.get("attempts", []) if isinstance(debug, dict) else []
        if not attempts:
            return
        item = attempts[-1]
        try:
            status = int(item.get("status") or 0)
        except Exception:
            status = 0
        if status and status < 400 and not item.get("error"):
            item["error"] = "token_missing"
            item["classification"] = "앱 구현 문제"

    def _sanitize_debug_text(self, value):
        text = str(value or "")
        text = re.sub(r"(tsck|tssk)_[A-Za-z0-9_\\-]+", r"\1_***", text)
        text = re.sub(r"Bearer\\s+[A-Za-z0-9._\\-]+", "Bearer ***", text, flags=re.IGNORECASE)
        return text[:300]

    def _credential_source(self):
        return str(getattr(self.struct, "_toss_credential_source", "saved") or "saved")

    def _token_debug_summary(self, debug=None):
        debug = debug or self._last_token_debug or {}
        key_shape = debug.get("key_shape", {}) or {}
        api_key = key_shape.get("api_key", {}) or {}
        secret_key = key_shape.get("secret_key", {}) or {}
        attempts = []
        for item in debug.get("attempts", []) or []:
            status = item.get("status") or "응답없음"
            code = item.get("code") or item.get("error") or "unknown"
            attempts.append(f"{item.get('method')}: HTTP {status} / {code}")
        attempt_text = ", ".join(attempts) if attempts else "토큰 요청 기록 없음"
        last_attempt = (debug.get("attempts", []) or [{}])[-1]
        return (
            "토스 연결 진단: "
            f"source={debug.get('source', self._credential_source())}, "
            f"authMode={debug.get('authMode', 'basic')}, endpoint={debug.get('endpoint', f'{BASE_URL}{TOKEN_PATH}')}. "
            f"apiKey prefix10={api_key.get('prefix10', '')} length={api_key.get('length', 0)}, "
            f"secretKey prefix10={secret_key.get('prefix10', '')} length={secret_key.get('length', 0)}, "
            f"HTTP status={last_attempt.get('status') or '응답없음'}, "
            f"error={last_attempt.get('error') or last_attempt.get('code') or 'unknown'}, "
            f"분류={last_attempt.get('classification') or '확인 필요'}. "
            f"요청={attempt_text}. 전체 키 값은 저장/표시하지 않습니다."
        )

    def token_diagnostics(self):
        debug = self._last_token_debug or {}
        lines = []
        if debug:
            key_shape = debug.get("key_shape", {}) or {}
            api_key = key_shape.get("api_key", {}) or {}
            secret_key = key_shape.get("secret_key", {}) or {}
            source = debug.get("source", self._credential_source())
            endpoint = debug.get("endpoint", f"{BASE_URL}{TOKEN_PATH}")
            auth_mode = debug.get("authMode", "basic")
            lines.append(f"apiKey: prefix10={api_key.get('prefix10', '')}, length={api_key.get('length', 0)}, source={source}")
            lines.append(f"secretKey: prefix10={secret_key.get('prefix10', '')}, length={secret_key.get('length', 0)}, source={source}")
            for item in debug.get("attempts", []) or []:
                error = item.get("error") or ""
                line = (
                    f"authMode={item.get('authMode', auth_mode)}, "
                    f"endpoint={item.get('endpoint', endpoint)}, "
                    f"HTTP status={item.get('status') or '응답없음'}"
                )
                line += f", error={error or item.get('code') or 'unknown'}"
                if item.get("classification"):
                    line += f", 분류={item.get('classification')}"
                lines.append(line)
        return lines

    def _credential_scope(self):
        try:
            user_id = self.struct._current_user_id()
        except Exception:
            user_id = ""
        return f"{user_id}:{self.client_id}"

    def get_token(self):
        scope = self._credential_scope()
        if self._token and self._token_scope == scope and self._token_expires and time.time() < self._token_expires:
            return self._token
        cached_token = self._get_config("toss_access_token", "")
        try:
            cached_expires = float(self._get_config("toss_token_expires", "0") or 0)
        except Exception:
            cached_expires = 0.0
        if cached_token and time.time() < cached_expires:
            self._token = cached_token
            self._token_expires = cached_expires
            self._token_scope = scope
            return cached_token
        return self._issue_token()

    def _headers(self, account_required=False):
        headers = {
            "Authorization": f"Bearer {self.get_token()}",
            "Accept": "application/json",
        }
        if account_required:
            seq = self.account_seq
            if not seq:
                raise Exception("토스증권 계좌 일련번호가 설정되어 있지 않습니다.")
            headers["X-Tossinvest-Account"] = str(seq)
        return headers

    def _decode_response(self, resp):
        try:
            data = resp.json()
        except Exception:
            data = {}
        if getattr(resp, "status_code", 200) >= 400:
            if isinstance(data, dict):
                err = data.get("error", {})
                if not isinstance(err, dict):
                    err = {"message": str(err)}
                message = err.get("message") or err.get("error_description") or data.get("error_description") or data.get("message") or ""
                code = err.get("code") or data.get("code") or data.get("error") or ""
            else:
                message = str(data or getattr(resp, "text", "") or "")
                code = ""
            body_text = getattr(resp, "text", "")
            friendly = self._friendly_error_message(code, message or body_text, getattr(resp, "status_code", ""))
            if friendly:
                raise Exception(friendly)
            raise Exception(f"토스증권 API 오류: {message or body_text} ({code or resp.status_code})")
        return data

    def _friendly_error_message(self, code, message, status_code):
        code_text = str(code or "").strip().lower()
        message_text = str(message or "").strip().lower()
        if "access_denied" in (code_text, message_text):
            return (
                "토스증권 API 오류: 토스 OpenAPI 이용 권한/약관/앱 활성화 문제입니다(access_denied). "
                "토스증권 Open API 화면에서 약관 동의, 앱 활성화, 실전/테스트 환경, Open API 이용 권한이 완료되어 있는지 확인해주세요. "
                "계좌 일련번호(accountSeq)는 토큰 발급 이후 단계라 이 오류의 직접 원인이 아닙니다."
            )
        if code_text in ("invalid_client", "unauthorized_client") or message_text in ("invalid_client", "unauthorized_client"):
            return (
                f"토스증권 API 오류: 클라이언트 인증에 실패했습니다({code_text or message_text or status_code}). "
                "api key와 secret key가 같은 토스증권 Open API 앱에서 발급된 키 세트인지 확인해주세요."
            )
        return ""

    def _record_api_debug(self, method, path, resp=None, code="", message="", account_required=False):
        status = getattr(resp, "status_code", "") if resp is not None else ""
        try:
            status_int = int(status or 0)
        except Exception:
            status_int = 0
        code_text = str(code or "").lower()
        message_text = str(message or "").lower()
        if resp is None:
            classification = "네트워크/앱 실행 환경 문제"
        elif status_int == 401:
            classification = "토스 토큰 만료 또는 Bearer 인증 문제"
        elif status_int == 403 or "access_denied" in (code_text, message_text):
            classification = "토스 OpenAPI 이용 권한/약관/앱 활성화 문제"
        elif status_int >= 400:
            classification = "토스 응답 오류"
        else:
            classification = "정상"
        self._last_api_debug.append({
            "method": str(method or "").upper(),
            "endpoint": f"{BASE_URL}{path}",
            "authMode": "bearer+account" if account_required else "bearer",
            "status": status,
            "error": self._sanitize_debug_text(message or code),
            "classification": classification,
        })

    def api_diagnostics(self):
        lines = []
        for item in self._last_api_debug:
            lines.append(
                f"authMode={item.get('authMode', 'bearer')}, "
                f"endpoint={item.get('endpoint', '')}, "
                f"HTTP status={item.get('status') or '응답없음'}, "
                f"error={item.get('error') or '없음'}, "
                f"분류={item.get('classification') or '확인 필요'}"
            )
        return lines

    def _request(self, method, path, params=None, body=None, account_required=False, retries=1):
        if requests is None:
            raise Exception("requests 패키지가 설치되어 있지 않습니다.")
        url = f"{BASE_URL}{path}"
        last_error = None
        for attempt in range(retries + 1):
            response_recorded = False
            try:
                self._rate_limit_wait()
                headers = self._headers(account_required=account_required)
                if method.upper() == "GET":
                    resp = requests.get(url, headers=headers, params=params, timeout=10)
                else:
                    headers["Content-Type"] = "application/json"
                    resp = requests.post(url, headers=headers, json=body or {}, timeout=10)
                data, code, message = self._response_error_fields(resp)
                self._record_api_debug(method, path, resp=resp, code=code, message=message, account_required=account_required)
                response_recorded = True
                if resp.status_code == 401 and attempt < retries:
                    self._token = None
                    self._token_expires = None
                    self._set_config("toss_access_token", "", "토스증권 접근 토큰", True)
                    self._set_config("toss_token_expires", "0", "토스증권 토큰 만료시각")
                    continue
                return self._decode_response(resp)
            except Exception as e:
                last_error = e
                if response_recorded is False:
                    self._record_api_debug(method, path, resp=None, code="request_error", message=str(e), account_required=account_required)
                if attempt < retries:
                    time.sleep(0.5)
                    continue
                raise
        raise last_error or Exception("토스증권 API 요청에 실패했습니다.")

    def _result(self, method, path, params=None, body=None, account_required=False, retries=1):
        data = self._request(method, path, params=params, body=body, account_required=account_required, retries=retries)
        if isinstance(data, dict) and "result" in data:
            return data.get("result")
        return data

    def _order_exchange(self, exchange="NASD"):
        text = str(exchange or "").upper()
        if text in self.ORDER_EXCHANGE_MAP:
            return self.ORDER_EXCHANGE_MAP[text]
        if text in self.PRICE_EXCHANGE_MAP:
            return text
        return "NASD"

    def _currency_for_symbol(self, symbol="", exchange=""):
        symbol = str(symbol or "").strip()
        if symbol.isdigit() and len(symbol) == 6:
            return "KRW"
        if str(exchange or "").upper() in ("KRX", "KOSPI", "KOSDAQ"):
            return "KRW"
        return "USD"

    def _date_yyyymmdd_to_iso(self, value):
        text = str(value or "").strip()
        if len(text) == 8 and text.isdigit():
            return f"{text[:4]}-{text[4:6]}-{text[6:]}"
        return text

    def _display_trade_date(self, value):
        text = str(value or "").strip()
        if not text:
            return _TIME.now().strftime("%Y-%m-%d")
        if "T" in text:
            return text.split("T", 1)[0]
        if len(text) == 8 and text.isdigit():
            return f"{text[:4]}-{text[4:6]}-{text[6:]}"
        return text[:10]

    # ------------------------------------------------------------------
    # Connection / market data
    # ------------------------------------------------------------------
    def test_connection(self):
        try:
            self.get_token()
            accounts = self.list_accounts()
            if not accounts:
                return {"success": False, "message": "토스증권 계좌를 찾지 못했습니다."}
            seq = self.account_seq
            return {
                "success": True,
                "message": "토스증권 API 연결 성공",
                "broker": "toss",
                "account_seq": seq,
                "account_no": str((accounts[0] or {}).get("accountNo", "") or ""),
                "diagnostics": self.token_diagnostics() + self.api_diagnostics(),
            }
        except Exception as e:
            return {"success": False, "message": str(e), "broker": "toss", "diagnostics": self.token_diagnostics() + self.api_diagnostics()}

    def list_accounts(self):
        return self._result("GET", "/api/v1/accounts", retries=1) or []

    def get_current_price(self, symbol, exchange="NAS"):
        symbol = str(symbol or "").upper().strip()
        rows = self._result("GET", "/api/v1/prices", params={"symbols": symbol}, retries=1) or []
        if not rows:
            raise Exception(f"현재가 조회 실패 [{symbol}]: 토스증권 응답 없음")
        row = rows[0]
        price = self._safe_float(row.get("lastPrice"), 0)
        if price <= 0:
            raise Exception(f"현재가 조회 실패 [{symbol}]: price=0")

        prev_close = price
        try:
            candles = self._result("GET", "/api/v1/candles", params={
                "symbol": symbol,
                "interval": "1d",
                "count": 2,
                "adjusted": "true",
            }, retries=0) or {}
            candle_rows = candles.get("candles", []) if isinstance(candles, dict) else []
            if len(candle_rows) >= 1:
                latest = candle_rows[0] or {}
                latest_date = str(latest.get("timestamp", "") or "")[:10]
                today = _TIME.now().strftime("%Y-%m-%d")
                # 프리마켓/데이마켓에는 최신 일봉이 이미 전일 종가인 경우가 많다.
                # 최신 일봉 날짜가 오늘이면 두 번째 봉을 전일 종가로 쓰고, 아니면 최신 봉을 쓴다.
                if latest_date == today and len(candle_rows) >= 2:
                    prev_close = self._safe_float((candle_rows[1] or {}).get("closePrice"), price)
                else:
                    prev_close = self._safe_float(latest.get("closePrice"), price)
        except Exception:
            prev_close = price

        return {
            "symbol": symbol,
            "price": price,
            "prev_close": prev_close,
            "exchange": str(exchange or ""),
            "order_exchange": self._order_exchange(exchange),
            "source": "TOSS",
            "timestamp": row.get("timestamp", ""),
            "currency": row.get("currency", self._currency_for_symbol(symbol, exchange)),
        }

    def _get_usd_krw_rate_fallback(self):
        result = self._result("GET", "/api/v1/exchange-rate", params={
            "baseCurrency": "USD",
            "quoteCurrency": "KRW",
        }, retries=1) or {}
        rate = self._safe_float(result.get("rate") or result.get("exchangeRate") or result.get("price"), 0)
        return {"rate": rate, "source": "toss_exchange_rate"}

    # ------------------------------------------------------------------
    # Account / balance
    # ------------------------------------------------------------------
    def get_buying_power_info(self, symbol="", price=0, exchange="NASD"):
        currency = self._currency_for_symbol(symbol, exchange)
        result = self._result("GET", "/api/v1/buying-power", params={"currency": currency}, account_required=True, retries=1) or {}
        amount = self._safe_float(result.get("cashBuyingPower"), 0)
        price = self._safe_float(price, 0)
        qty = int(amount / price) if price > 0 else 0
        return {
            "ok": amount > 0,
            "source": "toss_cashBuyingPower",
            "currency": currency,
            "amount": amount,
            "broker_amount": amount,
            "broker_qty": qty,
            "executable_amount": amount,
            "executable_qty": qty,
            "estimated_amount": amount,
            "estimated_qty": qty,
            "qty": qty,
            "qty_source": "toss_cashBuyingPower",
            "auto_exchange_ready": True,
            "auto_exchange_usd": amount if currency == "USD" else 0,
            "krw_auto_exchange_estimate_usd": 0,
        }

    def get_balance(self):
        result = self._result("GET", "/api/v1/holdings", account_required=True, retries=1) or {}
        items = result.get("items", []) or []
        holdings = []
        total_eval = 0.0
        for item in items:
            currency = str(item.get("currency", "") or "")
            if currency != "USD":
                continue
            market_value = item.get("marketValue", {}) or {}
            profit_loss = item.get("profitLoss", {}) or {}
            qty = self._safe_int(item.get("quantity"), 0)
            eval_amount = self._safe_float(market_value.get("amount"), 0)
            total_eval += eval_amount
            holdings.append({
                "symbol": str(item.get("symbol", "") or "").upper(),
                "name": item.get("name", ""),
                "qty": qty,
                "avg_price": self._safe_float(item.get("averagePurchasePrice"), 0),
                "current_price": self._safe_float(item.get("lastPrice"), 0),
                "eval_amount": eval_amount,
                "profit_loss": self._safe_float(profit_loss.get("amount"), 0),
                "profit_rate": self._safe_float(profit_loss.get("rate"), 0) * 100,
                "exchange": "NASD",
                "broker": "toss",
            })
        try:
            usd_power = self.get_buying_power_info(symbol="AAPL", price=1, exchange="NASD")
            cash_balance = self._safe_float(usd_power.get("executable_amount"), 0)
        except Exception:
            cash_balance = 0.0
        return {"holdings": holdings, "total_eval": total_eval, "cash_balance": cash_balance}

    def get_domestic_balance(self):
        result = self._result("GET", "/api/v1/holdings", account_required=True, retries=1) or {}
        items = result.get("items", []) or []
        holdings = []
        total_eval = 0.0
        for item in items:
            currency = str(item.get("currency", "") or "")
            if currency != "KRW":
                continue
            market_value = item.get("marketValue", {}) or {}
            profit_loss = item.get("profitLoss", {}) or {}
            qty = self._safe_int(item.get("quantity"), 0)
            current_price = self._safe_float(item.get("lastPrice"), 0)
            eval_amount = self._safe_float(market_value.get("amount"), qty * current_price)
            total_eval += eval_amount
            holdings.append({
                "symbol": str(item.get("symbol", "") or ""),
                "name": item.get("name", ""),
                "qty": qty,
                "avg_price": self._safe_float(item.get("averagePurchasePrice"), 0),
                "current_price": current_price,
                "eval_amount": eval_amount,
                "profit_loss": self._safe_float(profit_loss.get("amount"), 0),
                "profit_rate": self._safe_float(profit_loss.get("rate"), 0) * 100,
                "market": "KS",
                "broker": "toss",
            })
        try:
            krw_power = self.get_buying_power_info(symbol="005930", price=1, exchange="KRX")
            cash_balance = self._safe_float(krw_power.get("executable_amount"), 0)
        except Exception:
            cash_balance = 0.0
        return {"holdings": holdings, "total_eval": total_eval, "cash_balance": cash_balance}

    def get_present_balance(self):
        overseas = self.get_balance()
        domestic = self.get_domestic_balance()
        try:
            fx = self._safe_float(self._get_usd_krw_rate_fallback().get("rate"), 0)
        except Exception:
            fx = 0.0
        usd_eval = self._safe_float(overseas.get("total_eval"), 0)
        usd_cash = self._safe_float(overseas.get("cash_balance"), 0)
        krw_eval = self._safe_float(domestic.get("total_eval"), 0)
        krw_cash = self._safe_float(domestic.get("cash_balance"), 0)
        portfolio_eval_krw = krw_eval + (usd_eval * fx if fx > 0 else 0)
        cash_krw = krw_cash + (usd_cash * fx if fx > 0 else 0)
        return {
            "usd_krw": fx,
            "withdrawable_krw": krw_cash,
            "krw_balance": krw_cash,
            "usd_cash": usd_cash,
            "portfolio_eval_krw": portfolio_eval_krw,
            "total_asset_krw": portfolio_eval_krw + cash_krw,
            "unsettled_buy_krw": 0,
            "unsettled_sell_krw": 0,
            "meta": {"source": "toss_present_balance"},
        }

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------
    def _order_body(self, symbol, qty, price=0, side="BUY", order_type="LOC"):
        symbol = str(symbol or "").upper().strip()
        qty = int(qty)
        price = self._safe_float(price, 0)
        order_type = str(order_type or "LOC").upper()
        body = {
            "clientOrderId": self._client_order_id(symbol, side, qty, price, order_type),
            "symbol": symbol,
            "side": side,
            "quantity": str(qty),
            "confirmHighValueOrder": True,
        }
        if order_type in ("MARKET", "MKT"):
            body["orderType"] = "MARKET"
        else:
            body["orderType"] = "LIMIT"
            body["price"] = self._price_text(price)
            if order_type in ("LOC", "RESERVE_LOC"):
                body["timeInForce"] = "CLS"
            else:
                body["timeInForce"] = "DAY"
        return body

    def _client_order_id(self, symbol, side, qty, price, order_type):
        price_units = int(round(self._safe_float(price, 0) * 100))
        today = _TIME.now().strftime("%y%m%d")
        raw = f"IB{today}{symbol}{side[:1]}{order_type[:1]}{price_units}Q{int(qty)}"
        return "".join(ch for ch in raw if ch.isalnum() or ch in "-_")[:36]

    def _price_text(self, price):
        price = self._safe_float(price, 0)
        if price < 1:
            return f"{price:.4f}".rstrip("0").rstrip(".")
        return f"{price:.2f}".rstrip("0").rstrip(".")

    def buy_order(self, symbol, qty, price=0, order_type="LOC", exchange="NASD", allow_auto_exchange_attempt=None):
        body = self._order_body(symbol, qty, price=price, side="BUY", order_type=order_type)
        data = self._result("POST", "/api/v1/orders", body=body, account_required=True, retries=1) or {}
        order_no = data.get("orderId", "")
        return {
            "order_no": order_no,
            "reserve_order_no": order_no,
            "symbol": str(symbol or "").upper(),
            "qty": int(qty),
            "price": self._safe_float(price, 0),
            "order_type": "LOC" if str(order_type or "").upper() in ("LOC", "RESERVE_LOC") else str(order_type or "").upper(),
            "exchange": self._order_exchange(exchange),
            "reserved": str(order_type or "").upper() in ("LOC", "RESERVE_LOC"),
            "raw": data,
            "broker": "toss",
        }

    def buy_reservation_order(self, symbol, qty, price=0, order_type="LOC", exchange="NASD"):
        # 토스증권은 별도 예약주문 endpoint가 아니라 LIMIT+CLS LOC 주문을 직접 생성한다.
        return self.buy_order(symbol, qty, price=price, order_type=order_type, exchange=exchange)

    def sell_order(self, symbol, qty, price=0, order_type="MARKET", exchange="NASD"):
        body = self._order_body(symbol, qty, price=price, side="SELL", order_type=order_type)
        data = self._result("POST", "/api/v1/orders", body=body, account_required=True, retries=1) or {}
        order_no = data.get("orderId", "")
        return {
            "order_no": order_no,
            "symbol": str(symbol or "").upper(),
            "qty": int(qty),
            "price": self._safe_float(price, 0),
            "order_type": "LOC" if str(order_type or "").upper() in ("LOC", "RESERVE_LOC") else str(order_type or "").upper(),
            "exchange": self._order_exchange(exchange),
            "raw": data,
            "broker": "toss",
        }

    def get_overseas_reservation_orders(self, start_date=None, end_date=None, exchanges=None):
        params = {"status": "OPEN"}
        if start_date:
            params["from"] = self._date_yyyymmdd_to_iso(start_date)
        if end_date:
            params["to"] = self._date_yyyymmdd_to_iso(end_date)
        result = self._result("GET", "/api/v1/orders", params=params, account_required=True, retries=1) or {}
        orders = result.get("orders", []) if isinstance(result, dict) else []
        rows = []
        for item in orders:
            if str(item.get("currency", "") or "") != "USD":
                continue
            execution = item.get("execution", {}) or {}
            order_type = str(item.get("orderType", "") or "")
            tif = str(item.get("timeInForce", "") or "")
            rows.append({
                "reserve_order_no": item.get("orderId", ""),
                "order_no": item.get("orderId", ""),
                "symbol": str(item.get("symbol", "") or "").upper(),
                "exchange": "NASD",
                "receipt_date": self._display_trade_date(item.get("orderedAt", "")),
                "side": str(item.get("side", "") or "").upper(),
                "qty": self._safe_int(item.get("quantity"), 0),
                "price": self._safe_float(item.get("price"), 0),
                "filled_qty": self._safe_int(execution.get("filledQuantity"), 0),
                "filled_price": self._safe_float(execution.get("averageFilledPrice"), 0),
                "status_code": str(item.get("status", "") or ""),
                "status_name": str(item.get("status", "") or ""),
                "trade_status_name": f"{order_type}+{tif}",
                "cancel_yn": "N",
                "raw": item,
            })
        return rows

    def get_overseas_order_history(self, start_date=None, end_date=None, symbol="", exchanges=None):
        params = {
            "status": "CLOSED",
            "limit": 100,
        }
        if start_date:
            params["from"] = self._date_yyyymmdd_to_iso(start_date)
        if end_date:
            params["to"] = self._date_yyyymmdd_to_iso(end_date)
        if symbol:
            params["symbol"] = str(symbol or "").upper()
        result = self._result("GET", "/api/v1/orders", params=params, account_required=True, retries=1) or {}
        orders = result.get("orders", []) if isinstance(result, dict) else []
        rows = []
        for item in orders:
            if str(item.get("currency", "") or "") != "USD":
                continue
            execution = item.get("execution", {}) or {}
            filled_qty = self._safe_int(execution.get("filledQuantity"), 0)
            avg_price = self._safe_float(execution.get("averageFilledPrice"), 0)
            status = str(item.get("status", "") or "").upper()
            if status == "PARTIAL_FILLED":
                normalized = "PARTIAL"
            elif status == "FILLED":
                normalized = "FILLED"
            elif status in ("CANCELED", "REJECTED", "REPLACED") and filled_qty > 0:
                normalized = "PARTIAL"
            else:
                normalized = status
            rows.append({
                "order_no": item.get("orderId", ""),
                "symbol": str(item.get("symbol", "") or "").upper(),
                "side": str(item.get("side", "") or "").upper(),
                "action": str(item.get("side", "") or "").upper(),
                "status": normalized,
                "order_qty": self._safe_int(item.get("quantity"), 0),
                "order_price": self._safe_float(item.get("price"), 0),
                "filled_qty": filled_qty,
                "filled_price": avg_price,
                "filled_amount": self._safe_float(execution.get("filledAmount"), 0),
                "commission": self._safe_float(execution.get("commission"), 0),
                "tax": self._safe_float(execution.get("tax"), 0),
                "order_date": self._display_trade_date(item.get("orderedAt", "")),
                "filled_at": execution.get("filledAt", ""),
                "exchange": "NASD",
                "raw": item,
                "broker": "toss",
            })
        return rows


Model = TossApi
