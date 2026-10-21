"""Upbit (KRW spot) REST client for the admin-only coin automation (10-21).

Docs: https://docs.upbit.com/kr/reference
Auth: JWT HS256 signed with the secret key; requests with parameters carry
query_hash = SHA512 of the url-encoded parameters. Keys must be issued with
the caller's IP registered on Upbit, or every private call fails.

Safety: every non-GET request (orders, cancels) calls `order_guard()` first
and is refused when no guard was given (fail-closed), the same idea as
kis_api's order_policy.assert_order. Rate limits are kept process-wide in
sys.__dict__ because WIZ re-executes model modules.

Limits (per second): quotation 10, exchange (accounts/orders) 30, order 8.
The minimum order is 5,000 KRW.
"""
import base64
import calendar
import hashlib
import hmac
import json
import sys
import threading
import time
import uuid
from decimal import Decimal, ROUND_DOWN
from urllib.parse import urlencode

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

BASE_URL = "https://api.upbit.com"
MIN_ORDER_KRW = 5000.0
_RATE = sys.__dict__.setdefault("_stock8_upbit_rate", {
    "lock": threading.Lock(), "quote": 0.0, "exchange": 0.0, "order": 0.0,
})
_MIN_GAP = {"quote": 0.12, "exchange": 0.05, "order": 0.15}


def _b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _jwt(access_key, secret_key, params=None):
    payload = {"access_key": access_key, "nonce": str(uuid.uuid4())}
    if params:
        query = urlencode(params, doseq=True).encode("utf-8")
        payload["query_hash"] = hashlib.sha512(query).hexdigest()
        payload["query_hash_alg"] = "SHA512"
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = _b64url(json.dumps(header, separators=(",", ":")).encode()) + "." + \
        _b64url(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(secret_key.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return signing_input + "." + _b64url(signature)


def format_volume(volume, decimals=8):
    """Truncate (never round up) to the exchange's 8 decimals, no exponent."""
    q = Decimal(1).scaleb(-decimals)
    text = format(Decimal(str(volume)).quantize(q, rounding=ROUND_DOWN), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


class UpbitError(Exception):
    # Errors after which retrying cannot help until a person fixes something.
    FATAL = {"no_authorization_ip", "invalid_access_key", "jwt_verification", "expired_access_key",
             "nonce_used", "out_of_scope", "invalid_query_payload", "order_guard"}

    def __init__(self, message, status=0, name=""):
        super().__init__(message)
        self.status = status
        self.name = name

    @property
    def fatal(self):
        return self.name in self.FATAL


class UpbitApi:
    def __init__(self, access_key="", secret_key="", timeout=8.0, order_guard=None, session=None):
        self.access_key = str(access_key or "").strip()
        self.secret_key = str(secret_key or "").strip()
        self.timeout = timeout
        self.order_guard = order_guard
        if session is not None:
            self._session = session
        else:
            self._session = requests.Session() if requests is not None else None

    @property
    def configured(self):
        return bool(self.access_key and self.secret_key)

    def _throttle(self, kind):
        with _RATE["lock"]:
            wait = _MIN_GAP[kind] - (time.monotonic() - _RATE[kind])
            if wait > 0:
                time.sleep(wait)
            _RATE[kind] = time.monotonic()

    def _request(self, method, path, params=None, private=False, guard_info=None):
        if self._session is None:
            raise UpbitError("requests 라이브러리가 없습니다.")
        if method != "GET":
            # Fail closed: no guard, no order.
            if not callable(self.order_guard):
                raise UpbitError("주문 안전장치가 없어 주문을 보내지 않았습니다.", 0, "order_guard")
            try:
                self.order_guard(method, path, dict(params or {}), dict(guard_info or {}))
            except UpbitError:
                raise
            except Exception as exc:
                raise UpbitError(f"주문 차단: {exc}", 0, "order_guard")
        self._throttle("order" if path == "/v1/orders" and method == "POST" else ("exchange" if private else "quote"))
        headers = {"Accept": "application/json"}
        if private:
            if not self.configured:
                raise UpbitError("업비트 API 키가 설정되지 않았습니다.", 0, "invalid_access_key")
            headers["Authorization"] = "Bearer " + _jwt(self.access_key, self.secret_key, params)
        kwargs = {"headers": headers, "timeout": self.timeout}
        if method == "POST":
            kwargs["json"] = params or {}
        elif params:
            kwargs["params"] = params
        res = self._session.request(method, BASE_URL + path, **kwargs)
        try:
            data = res.json()
        except ValueError:
            data = {}
        if res.status_code >= 400:
            error = (data or {}).get("error", {}) if isinstance(data, dict) else {}
            name = str(error.get("name") or ("too_many_requests" if res.status_code == 429 else ""))
            raise UpbitError(str(error.get("message") or f"HTTP {res.status_code}"), res.status_code, name)
        return data

    # -- quotation (no key)
    def ticker(self, markets):
        markets = [markets] if isinstance(markets, str) else list(markets)
        rows = self._request("GET", "/v1/ticker", {"markets": ",".join(markets)})
        return {row["market"]: row for row in rows or []}

    def orderbook(self, markets):
        """{market: {"bid": best bid, "ask": best ask}}"""
        markets = [markets] if isinstance(markets, str) else list(markets)
        rows = self._request("GET", "/v1/orderbook", {"markets": ",".join(markets)})
        out = {}
        for row in rows or []:
            units = row.get("orderbook_units") or [{}]
            out[row["market"]] = {"bid": float(units[0].get("bid_price", 0) or 0),
                                  "ask": float(units[0].get("ask_price", 0) or 0)}
        return out

    def minute_candles(self, market, unit=60, count=200, to=None):
        """Oldest first; each row has epoch "t" (UTC bar start) and o/h/l/c/v."""
        params = {"market": market, "count": int(count)}
        if to:
            params["to"] = to
        rows = self._request("GET", f"/v1/candles/minutes/{int(unit)}", params)
        out = []
        for row in reversed(rows or []):
            stamp = str(row.get("candle_date_time_utc", ""))
            t = calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%S")) if stamp else 0
            out.append({"t": t, "o": float(row["opening_price"]), "h": float(row["high_price"]),
                        "l": float(row["low_price"]), "c": float(row["trade_price"]),
                        "v": float(row.get("candle_acc_trade_volume", 0) or 0)})
        return out

    # -- exchange (key)
    def accounts(self):
        return self._request("GET", "/v1/accounts", private=True)

    def balances(self):
        """{currency: {"balance", "locked", "avg_buy_price"}} as floats."""
        out = {}
        for row in self.accounts() or []:
            out[str(row.get("currency", ""))] = {
                "balance": float(row.get("balance", 0) or 0),
                "locked": float(row.get("locked", 0) or 0),
                "avg_buy_price": float(row.get("avg_buy_price", 0) or 0),
            }
        return out

    def order_chance(self, market):
        return self._request("GET", "/v1/orders/chance", {"market": market}, private=True)

    def buy_market_krw(self, market, krw_amount, identifier=""):
        """Market buy for a KRW amount (ord_type=price); the fee is charged on top."""
        amount = int(float(krw_amount))
        if amount < MIN_ORDER_KRW:
            raise UpbitError(f"최소 주문금액(5,000원) 미만: {amount:,}원", 0, "under_min_total")
        params = {"market": market, "side": "bid", "price": str(amount), "ord_type": "price"}
        if identifier:
            params["identifier"] = str(identifier)
        return self._request("POST", "/v1/orders", params, private=True,
                             guard_info={"market": market, "side": "bid", "krw": float(amount)})

    def sell_market(self, market, volume, identifier="", ref_price=0.0):
        """Market sell of a coin quantity (ord_type=market)."""
        text = format_volume(volume)
        if Decimal(text) <= 0:
            raise UpbitError("매도 수량이 0입니다.", 0, "under_min_total")
        params = {"market": market, "side": "ask", "volume": text, "ord_type": "market"}
        if identifier:
            params["identifier"] = str(identifier)
        return self._request("POST", "/v1/orders", params, private=True,
                             guard_info={"market": market, "side": "ask", "krw": float(text) * float(ref_price or 0)})

    def get_order(self, order_uuid="", identifier=""):
        params = {"uuid": order_uuid} if order_uuid else {"identifier": identifier}
        return self._request("GET", "/v1/order", params, private=True)

    def cancel_order(self, order_uuid):
        return self._request("DELETE", "/v1/order", {"uuid": order_uuid}, private=True,
                             guard_info={"side": "cancel"})


UpbitApi.Error = UpbitError
UpbitApi.format_volume = staticmethod(format_volume)

Model = UpbitApi
