"""Upbit public trade stream for the coin stop watch (10-24).

The SPEC's primary feed: every trade of the held markets over
wss://api.upbit.com/websocket/v1 (no key). The engine reads, per market, the
last price and the LOWEST price since its previous read, so a dip below the
stop between two engine passes is never missed (the backtest stops on the
candle low; a 3 s REST poll of the last price can miss a short wick).

One stream per process (shared()); it connects only while the engine asks
for markets and disconnects when nothing is held. healthy() is False while
disconnected or when a market has had no trade for STALE_SEC: the engine
then falls back to its REST ticker poll.
"""
import json
import sys
import threading
import time
import uuid

URL = "wss://api.upbit.com/websocket/v1"
STALE_SEC = 30.0  # a quiet market can go 10+ s without a trade
BACKOFF_MAX_SEC = 30.0


def _default_connect(url):
    from websockets.sync.client import connect
    return connect(url, open_timeout=6, ping_interval=20, ping_timeout=20, close_timeout=2, max_size=2 ** 20)


def subscription(markets):
    return json.dumps([{"ticket": f"stock8-{uuid.uuid4().hex[:12]}"},
                       {"type": "trade", "codes": sorted(markets), "is_only_realtime": True},
                       {"format": "SIMPLE"}])


def parse(message):
    """-> (market, price, trade_ms) or None. Upbit sends JSON as binary frames."""
    if isinstance(message, (bytes, bytearray)):
        message = message.decode("utf-8", "replace")
    try:
        row = json.loads(message)
    except (TypeError, ValueError):
        return None
    if not isinstance(row, dict) or row.get("error"):
        return None
    market = row.get("cd") or row.get("code")
    price = row.get("tp") if "tp" in row else row.get("trade_price")
    if not market or price is None:
        return None
    return str(market), float(price), int(row.get("ttms") or row.get("trade_timestamp") or 0)


class TradeStream:
    def __init__(self, connect=None, clock=None, sleep=None):
        self.connect = connect or _default_connect
        self.clock = clock or time.time
        self.sleep = sleep or time.sleep
        self.lock = threading.Lock()
        self.changed = threading.Event()
        self.want = frozenset()
        self.last = {}        # market -> (price, local_ts)
        self.low = {}         # market -> lowest price since the last read
        self.connected = False
        self.connected_at = 0.0
        self.error = ""
        self.reconnects = 0
        self.thread = None

    # ------------------------------------------------------------ engine side
    def watch(self, markets):
        markets = frozenset(markets or ())
        with self.lock:
            if markets == self.want:
                return
            self.want = markets
            for m in list(self.last):
                if m not in markets:
                    self.last.pop(m, None)
                    self.low.pop(m, None)
        self.changed.set()
        if markets:
            self._ensure_thread()

    def read(self, markets):
        """{market: {"price", "low", "age"}}; low is the minimum trade price
        since the previous read (then reset)."""
        now = self.clock()
        out = {}
        with self.lock:
            for m in markets:
                last = self.last.get(m)
                if not last:
                    continue
                low = self.low.pop(m, None)
                out[m] = {"price": last[0], "low": last[0] if low is None else min(low, last[0]), "age": now - last[1]}
        return out

    def healthy(self, markets):
        if not self.connected:
            return False
        now = self.clock()
        with self.lock:
            return all(m in self.last and now - self.last[m][1] < STALE_SEC for m in markets)

    def status(self):
        return {"connected": self.connected, "markets": sorted(self.want), "error": self.error,
                "reconnects": self.reconnects, "connected_at": int(self.connected_at)}

    # ------------------------------------------------------------ stream side
    def on_trade(self, market, price):
        if price <= 0:
            return
        with self.lock:
            if market not in self.want:
                return
            self.last[market] = (price, self.clock())
            prev = self.low.get(market)
            self.low[market] = price if prev is None else min(prev, price)

    def _ensure_thread(self):
        if self.thread is not None and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._run, daemon=True, name="stock8-upbit-ws")
        self.thread.start()

    def _run(self):
        backoff = 1.0
        while True:
            want = self.want
            if not want:
                self.changed.wait(5)
                self.changed.clear()
                continue
            try:
                self.run_once(want)
                backoff = 1.0
            except Exception as exc:
                self.error = str(exc)[:160]
                self.reconnects += 1
                self.sleep(backoff)
                backoff = min(BACKOFF_MAX_SEC, backoff * 2)
            finally:
                self.connected = False

    def run_once(self, want):
        """One connection for one market set; returns when the set changes."""
        self.changed.clear()
        with self.connect(URL) as ws:
            ws.send(subscription(want))
            self.connected = True
            self.connected_at = self.clock()
            self.error = ""
            while not self.changed.is_set():
                try:
                    message = ws.recv(timeout=1)
                except TimeoutError:
                    continue
                trade = parse(message)
                if trade:
                    self.on_trade(trade[0], trade[1])


def shared():
    inst = sys.__dict__.get("_stock8_upbit_trade_stream")
    if inst is None:
        inst = TradeStream()
        sys.__dict__["_stock8_upbit_trade_stream"] = inst
    return inst


class UpbitWs:
    TradeStream = TradeStream
    shared = staticmethod(shared)
    parse = staticmethod(parse)
    subscription = staticmethod(subscription)
    STALE_SEC = STALE_SEC


Model = UpbitWs
