"""Per-trade verification (11-04): every KIS order checked against the broker."""
import datetime
import importlib.util
import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import Mock

from test_kis_api_buying_power import kis_api, _StructStub

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("trade_verifier", ROOT / "src/portal/trading/model/trade_verifier.py")
tv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tv)

KST = datetime.timezone(datetime.timedelta(hours=9))
KS_PATH = "/uapi/domestic-stock/v1/trading/order-cash"
US_PATH = "/uapi/overseas-stock/v1/trading/order"


def kst(*args):
    return datetime.datetime(*args, tzinfo=KST).timestamp()


def ks_body(symbol="005930", qty=10, price=70000):
    return {"PDNO": symbol, "ORD_QTY": str(qty), "ORD_UNPR": str(price), "ORD_DVSN": "00", "EXCG_ID_DVSN_CD": "SOR"}


def us_body(symbol="TQQQ", qty=5, price=50.5):
    return {"PDNO": symbol, "ORD_QTY": str(qty), "OVRS_ORD_UNPR": str(price), "ORD_DVSN": "00", "OVRS_EXCG_CD": "NASD"}


def accepted(order_no="0000123456"):
    return {"rt_cd": "0", "msg1": "주문 전송 완료", "output": {"ODNO": order_no, "ORD_TMD": "100000"}}


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class Broker:
    def __init__(self):
        self.rows = []
        self.held = {}
        self.orders_error = None
        self.holdings_error = None
        self.calls = []

    def orders(self, market, symbol, ts):
        self.calls.append(("orders", market, symbol))
        if self.orders_error:
            raise RuntimeError(self.orders_error)
        return [r for r in self.rows if r["symbol"] == symbol]

    def holdings(self, market):
        self.calls.append(("holdings", market))
        if self.holdings_error:
            raise RuntimeError(self.holdings_error)
        return dict(self.held)


def fill(order_no="123456", symbol="005930", side="BUY", ord_qty=10, filled=10, price=69900, status=None):
    if status is None:
        status = "FILLED" if filled >= ord_qty else ("PARTIAL" if filled else "OPEN")
    return {"order_no": order_no, "symbol": symbol, "side": side, "ord_qty": ord_qty,
            "filled_qty": filled, "filled_price": price, "status": status}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "acct.json")
        self.clock = Clock(kst(2026, 11, 4, 10, 0))
        self.broker = Broker()
        self.local = {}
        self.alerts = []
        self.v = tv.Verifier(self.path, broker=self.broker, local=lambda no: self.local.get(tv.norm_order_no(no), 0),
                             notify=self.alerts.append, clock=self.clock)

    def later(self, sec):
        self.clock.now += sec

    def records(self):
        with open(self.path, encoding="utf-8") as handle:
            return json.load(handle)["records"]

    def status(self, index=-1):
        return self.records()[index]["status"]


class RecordTests(Base):
    def test_only_regular_orders_are_recorded(self):
        self.assertIsNone(tv.build_record("/uapi/overseas-stock/v1/trading/order-resv", "TTTT3014U", us_body(), accepted()))
        self.assertIsNone(tv.build_record("/uapi/domestic-stock/v1/trading/order-rvsecncl", "TTTC0013U", ks_body(), accepted()))
        rec = tv.build_record(KS_PATH, "TTTC0012U", ks_body(), accepted())
        self.assertEqual((rec["market"], rec["symbol"], rec["side"], rec["qty"], rec["price"]), ("KS", "005930", "BUY", 10, 70000.0))
        self.assertEqual((rec["outcome"], rec["order_no"], rec["status"]), ("ACCEPTED", "0000123456", "PENDING"))
        rec = tv.build_record(US_PATH, "TTTT1006U", us_body(), accepted("99"))
        self.assertEqual((rec["market"], rec["side"], rec["price"]), ("US", "SELL", 50.5))

    def test_outcomes(self):
        rejected = tv.build_record(KS_PATH, "TTTC0012U", ks_body(), {"rt_cd": "1", "msg_cd": "APBK0013", "msg1": "주문가능금액 초과"})
        self.assertEqual((rejected["outcome"], rejected["status"]), ("REJECTED", "REJECTED"))
        self.assertIn("APBK0013", rejected["broker_message"])
        unknown = tv.build_record(KS_PATH, "TTTC0012U", ks_body(), error=TimeoutError("read timeout"), sent=True)
        self.assertEqual((unknown["outcome"], unknown["status"]), ("UNKNOWN", "PENDING"))
        self.assertIsNone(tv.build_record(KS_PATH, "TTTC0012U", ks_body(), error=RuntimeError("OFF"), sent=False))
        no_number = tv.build_record(KS_PATH, "TTTC0012U", ks_body(), {"rt_cd": "0", "output": {}})
        self.assertEqual(no_number["outcome"], "UNKNOWN")

    def test_rejection_is_verified_without_broker_reads(self):
        self.v.record(KS_PATH, "TTTC0012U", ks_body(), {"rt_cd": "1", "msg1": "거절"})
        self.later(30)
        self.v.verify_due()
        self.assertEqual(self.status(), "REJECTED")
        self.assertEqual(self.broker.calls, [])
        self.assertIsNone(self.v.hold_for("005930"))


class VerifyTests(Base):
    def place(self, body=None, tr_id="TTTC0012U", data=None, path=KS_PATH):
        return self.v.record(path, tr_id, body or ks_body(), data if data is not None else accepted())

    def test_filled_buy_passes_every_check(self):
        self.place()
        self.v.verify_due()
        self.assertEqual(self.broker.calls, [], "first check waits for KIS to list the order")
        self.later(30)
        self.broker.rows = [fill()]
        self.broker.held = {"005930": 10}
        self.local["123456"] = 10
        self.v.verify_due()
        record = self.records()[-1]
        self.assertEqual(record["status"], "PASS")
        self.assertEqual({c["key"]: c["ok"] for c in record["checks"]},
                         {"accepted": True, "listed": True, "final": True, "price": True, "holdings": True, "local": True})
        self.assertEqual((record["filled_qty"], record["filled_price"]), (10, 69900))
        self.assertEqual(self.alerts, [])
        self.later(3600)
        self.broker.calls.clear()
        self.assertEqual(self.v.verify_due()["checked"], 0, "a passed trade is not read again")

    def test_open_order_waits_until_filled_or_session_end(self):
        self.place()
        self.later(30)
        self.broker.rows = [fill(filled=4)]
        self.broker.held = {"005930": 4}
        self.local["123456"] = 4
        self.v.verify_due()
        self.assertEqual(self.status(), "PENDING")
        self.assertIsNone(self.v.hold_for("005930"))
        self.clock.now = kst(2026, 11, 4, 20, 15)  # day order expired with 4 filled
        self.v.verify_due()
        self.assertEqual(self.status(), "PASS")

    def test_quantity_mismatch_holds_buys_until_acknowledged(self):
        self.place()
        self.later(30)
        self.broker.rows = [fill(ord_qty=100, filled=100)]
        self.v.verify_due()
        self.assertEqual(self.status(), "FAIL")
        self.assertIn("수량 10주→KIS 100주", self.records()[-1]["reason"])
        self.assertEqual(len(self.alerts), 1)
        self.assertIn("005930 신규 매수 보류", self.alerts[0])
        with self.assertRaisesRegex(RuntimeError, "거래 검증 불일치"):
            self.v.assert_buy_allowed("005930")
        self.v.assert_buy_allowed("000660")  # other symbols trade normally
        self.assertEqual(self.v.acknowledge(symbol="005930", user="u1"), 1)
        self.v.assert_buy_allowed("005930")
        self.assertEqual(self.status(), "FAIL", "the record stays for review")
        self.later(3600)
        self.broker.calls.clear()
        self.v.verify_due()
        self.assertEqual(self.broker.calls, [], "acknowledged records are not re-read")

    def test_local_record_gets_a_grace_period_then_fails_and_recovers(self):
        self.place()
        self.later(30)
        self.broker.rows = [fill()]
        self.broker.held = {"005930": 10}
        self.v.verify_due()
        self.assertEqual(self.status(), "PENDING")
        self.assertIn("로컬 기록", self.records()[-1]["reason"])
        self.later(tv.LOCAL_GRACE_SEC["KS"] + 60)
        self.v.verify_due()
        self.assertEqual(self.status(), "FAIL")
        self.assertIsNotNone(self.v.hold_for("005930"))
        self.local["123456"] = 10  # the fill sync caught up
        self.v.verify_due()
        self.assertEqual(self.status(), "FAIL", "failed records are re-read every 10 minutes")
        self.later(tv.FAIL_RECHECK_SEC)
        self.v.verify_due()
        self.assertEqual(self.status(), "PASS")
        self.assertIsNone(self.v.hold_for("005930"))
        self.assertIn("복구", self.alerts[-1])

    def test_double_recorded_fill_is_a_mismatch(self):
        self.place()
        self.later(30)
        self.broker.rows = [fill()]
        self.broker.held = {"005930": 10}
        self.local["123456"] = 20
        self.v.verify_due()
        self.assertEqual(self.status(), "PENDING", "the grace starts when the order is first seen final")
        self.later(tv.LOCAL_GRACE_SEC["KS"])
        self.v.verify_due()
        self.assertEqual(self.status(), "FAIL")
        self.assertIn("로컬 기록 20주 ≠ KIS 체결 10주", self.records()[-1]["reason"])

    def test_fill_price_beyond_limit_fails(self):
        self.place(ks_body(price=70000))
        self.later(30)
        self.broker.rows = [fill(price=71000)]
        self.broker.held = {"005930": 10}
        self.local["123456"] = 10
        self.v.verify_due()
        self.assertEqual(self.status(), "FAIL")
        self.assertIn("지정가", self.records()[-1]["reason"])

    def test_market_order_skips_price_check(self):
        self.place(ks_body(price=0))
        self.later(30)
        self.broker.rows = [fill(price=75000)]
        self.broker.held = {"005930": 10}
        self.local["123456"] = 10
        self.v.verify_due()
        self.assertEqual(self.status(), "PASS")

    def test_holdings_shortfall_counts_later_sells(self):
        self.place()
        self.later(5)
        self.place(ks_body(qty=6), tr_id="TTTC0011U", data=accepted("0000123457"))
        self.later(30)
        self.broker.rows = [fill(), fill(order_no="123457", side="SELL", ord_qty=6, filled=6, price=70100)]
        self.broker.held = {"005930": 4}
        self.local.update({"123456": 10, "123457": 6})
        self.v.verify_due()
        self.assertEqual([r["status"] for r in self.records()], ["PASS", "PASS"])

    def test_holdings_missing_after_fill_fails(self):
        self.place()
        self.later(30)
        self.broker.rows = [fill()]
        self.broker.held = {"005930": 3}  # sold outside the program
        self.local["123456"] = 10
        self.v.verify_due()
        self.assertEqual(self.status(), "FAIL")
        self.assertIn("KIS 보유 3주", self.records()[-1]["reason"])

    def test_unclear_send_is_found_in_kis_list(self):
        self.v.record(KS_PATH, "TTTC0012U", ks_body(), error=TimeoutError("read timeout"), sent=True)
        self.later(30)
        self.broker.rows = [fill()]
        self.broker.held = {"005930": 10}
        self.local["123456"] = 10
        self.v.verify_due()
        record = self.records()[-1]
        self.assertEqual((record["order_no"], record["outcome"], record["status"]), ("123456", "ACCEPTED", "PENDING"),
                         "local record is compared on the next pass, never skipped")
        self.later(60)
        self.v.verify_due()
        self.assertEqual(self.status(), "PASS")

    def test_unclear_send_does_not_claim_another_records_order(self):
        self.place()  # owns 123456
        self.v.record(KS_PATH, "TTTC0012U", ks_body(), error=TimeoutError("timeout"), sent=True)
        self.later(30)
        self.broker.rows = [fill()]
        self.broker.held = {"005930": 10}
        self.local["123456"] = 10
        self.v.verify_due()
        self.assertEqual(self.records()[-1]["order_no"], "")
        self.later(tv.NOT_LISTED_SEC)
        self.v.verify_due()
        self.assertEqual(self.status(), "NOT_ACCEPTED")
        self.assertIsNone(self.v.hold_for("005930"), "nothing is at the broker, so nothing to hold")
        self.assertIn("미접수", self.alerts[-1])

    def test_order_number_missing_from_kis_fails_after_ten_minutes(self):
        self.place()
        self.later(30)
        self.v.verify_due()
        self.assertEqual(self.status(), "PENDING")
        self.later(tv.NOT_LISTED_SEC)
        self.v.verify_due()
        self.assertEqual(self.status(), "FAIL")

    def test_lookup_failures_become_unconfirmed_after_thirty_minutes(self):
        self.place()
        self.broker.orders_error = "EGW00201 초당 거래건수 초과"
        for _ in range(3):
            self.later(600)
            self.v.verify_due()
        self.assertEqual(self.status(), "PENDING")
        self.later(600)
        self.v.verify_due()
        self.assertEqual(self.status(), "UNCONFIRMED")
        self.assertIsNotNone(self.v.hold_for("005930"))
        self.broker.orders_error = None
        self.broker.rows = [fill()]
        self.broker.held = {"005930": 10}
        self.local["123456"] = 10
        self.later(tv.FAIL_RECHECK_SEC)
        self.v.verify_due()
        self.assertEqual(self.status(), "PASS")

    def test_us_sell_with_cumulative_rows(self):
        self.place(us_body(), tr_id="TTTT1006U", path=US_PATH, data=accepted("0030001"))
        self.later(30)
        row = fill(order_no="30001", symbol="TQQQ", side="SELL", ord_qty=5, filled=5, price=50.6)
        self.broker.rows = [row, dict(row)]  # repeated cumulative rows are not two fills
        self.local["30001"] = 5
        self.v.verify_due()
        record = self.records()[-1]
        self.assertEqual((record["status"], record["filled_qty"]), ("PASS", 5))
        self.assertNotIn(("holdings", "US"), self.broker.calls, "sells need no holdings read")

    def test_us_open_order_is_final_after_the_session(self):
        self.place(us_body(), tr_id="TTTT1002U", path=US_PATH, data=accepted("0030002"))
        self.later(30)
        self.broker.rows = [fill(order_no="30002", symbol="TQQQ", ord_qty=5, filled=0, price=0)]
        self.local["30002"] = 0
        self.v.verify_due()
        self.assertEqual(self.status(), "PENDING")
        self.later(tv.NOT_LISTED_SEC)
        self.v.verify_due()
        self.broker.calls.clear()
        self.later(tv.RECHECK_SEC)
        self.v.verify_due()
        self.assertEqual(self.broker.calls, [], "a long-open order is read every 5 minutes, not every minute")
        self.later(tv.US_SESSION_SEC)
        self.v.verify_due()
        self.assertEqual(self.status(), "PASS")

    def test_summary_and_cap(self):
        for _ in range(tv.MAX_RECORDS + 5):
            self.place()
        summary = self.v.summary(limit=3)
        self.assertEqual(summary["total"], tv.MAX_RECORDS)
        self.assertEqual(len(summary["recent"]), 3)
        self.assertEqual(summary["recent"][0]["status_label"], "검증 대기")

    def test_corrupt_ledger_is_kept_aside(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{broken")
        self.place()
        self.assertTrue(os.path.exists(self.path + ".corrupt"))
        self.assertEqual(len(self.records()), 1)

    def test_alert_failure_never_breaks_verification(self):
        self.v.notify = Mock(side_effect=RuntimeError("discord down"))
        self.place()
        self.later(tv.NOT_LISTED_SEC + 30)
        self.v.verify_due()
        self.assertEqual(self.status(), "FAIL")


class LocalReaderTests(unittest.TestCase):
    def test_counts_fills_not_pending_or_error_rows(self):
        class DB:
            def __init__(self, rows, field):
                self.data, self.field = rows, field

            def rows(self, **kw):
                return [r for r in self.data if r.get(self.field) == kw[self.field]]
        log = DB([
            {"id": "a", "order_no": "0000123456", "action": "PENDING", "event_type": "DT_KS_BUY1_PENDING", "filled_qty": 0},
            {"id": "b", "order_no": "0000123456", "action": "BUY", "event_type": "DT_KS_BUY1", "filled_qty": 10},
            {"id": "c", "order_no": "123456", "action": "ERROR", "event_type": "DT_KS_BUY1_ERROR", "filled_qty": 0},
        ], "order_no")
        cycles = DB([{"id": "x", "broker_order_no": "777", "filled_qty": 3}], "broker_order_no")
        read = tv.local_filled_reader(log, cycles)
        self.assertEqual(read("0000123456"), 10)
        self.assertEqual(read("777"), 3)
        self.assertEqual(read("999"), 0)


class KisBoundaryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.verifier = tv.Verifier(os.path.join(tmp.name, "acct.json"), broker=Broker())
        struct = _StructStub()
        struct.trade_verifier = self.verifier
        self.api = kis_api.KisApi(struct)
        self.api._rate_limit_wait = Mock()
        self.api._session = Mock()
        self.api._assert_safe_request = Mock()
        self.api.get_token = Mock(return_value="token")

    def response(self, data):
        return Mock(headers={}, json=Mock(return_value=data))

    def test_every_order_is_recorded(self):
        self.api._session.post.return_value = self.response(accepted())
        self.api._request("POST", KS_PATH, "TTTC0012U", body=ks_body())
        self.api._session.post.return_value = self.response({"rt_cd": "1", "msg1": "거절"})
        self.api._request("POST", US_PATH, "TTTT1006U", body=us_body())
        records = self.verifier.ledger.load()["records"]
        self.assertEqual([(r["market"], r["side"], r["outcome"]) for r in records],
                         [("KS", "BUY", "ACCEPTED"), ("US", "SELL", "REJECTED")])

    def test_transport_error_after_send_is_unknown_not_dropped(self):
        self.api._session.post.side_effect = kis_api.requests.exceptions.ReadTimeout("timeout")
        with self.assertRaises(Exception):
            self.api._request("POST", KS_PATH, "TTTC0012U", body=ks_body())
        records = self.verifier.ledger.load()["records"]
        self.assertEqual(records[-1]["outcome"], "UNKNOWN")

    def test_blocked_before_send_is_not_recorded(self):
        self.api._assert_safe_request = Mock(side_effect=RuntimeError("OFF"))
        with self.assertRaises(RuntimeError):
            self.api._request("POST", KS_PATH, "TTTC0012U", body=ks_body())
        self.assertEqual(self.verifier.ledger.load()["records"], [])
        self.api._session.post.assert_not_called()

    def test_hold_refuses_buys_before_send_but_never_sells(self):
        state = {"records": [dict(tv.build_record(KS_PATH, "TTTC0012U", ks_body(), accepted()), status="FAIL", reason="수량 불일치")]}
        self.verifier.ledger.save(state)
        with self.assertRaisesRegex(RuntimeError, "신규 매수를 보류"):
            self.api._request("POST", KS_PATH, "TTTC0012U", body=ks_body())
        self.api._session.post.assert_not_called()
        self.api._session.post.return_value = self.response(accepted("0000999"))
        self.api._request("POST", KS_PATH, "TTTC0011U", body=ks_body())  # exit still goes out
        self.assertEqual(self.api._session.post.call_count, 1)

    def test_reads_and_unconfigured_accounts_pass_through(self):
        self.api._session.get.return_value = self.response({"rt_cd": "0"})
        self.api._request("GET", "/uapi/domestic-stock/v1/trading/inquire-balance", "TTTC8434R")
        self.assertEqual(self.verifier.ledger.load()["records"], [])
        plain = kis_api.KisApi(_StructStub())
        plain._rate_limit_wait = Mock()
        plain._session = Mock()
        plain._assert_safe_request = Mock()
        plain.get_token = Mock(return_value="token")
        plain._session.post.return_value = self.response(accepted())
        self.assertEqual(plain._request("POST", KS_PATH, "TTTC0012U", body=ks_body())["rt_cd"], "0")


if __name__ == "__main__":
    unittest.main()
