"""Dividend management math and data merge (10-22)."""
import datetime as dt
import importlib.util
import unittest
from pathlib import Path

MODEL = Path(__file__).resolve().parents[1] / "src" / "portal" / "trading" / "model"


def _module(name):
    spec = importlib.util.spec_from_file_location(f"div_{name}", MODEL / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


D = _module("dividend").Dividend
data_mod = _module("dividend_data")
TODAY = dt.date(2026, 10, 22)


def quarterly(start, n, amount, lag=14):
    out = []
    day = start
    for i in range(n):
        out.append({"ex_date": day, "amount": amount(i) if callable(amount) else amount, "pay_date": day + dt.timedelta(days=lag)})
        day += dt.timedelta(days=91)
    return out


class DividendMathTests(unittest.TestCase):
    def test_quarterly_profile_and_projection(self):
        events = quarterly(dt.date(2024, 9, 13), 9, 0.51)  # last ex 2026-09-11
        p = D.analyze(events, TODAY)
        self.assertEqual((p["per_year"], p["frequency"]), (4, "분기"))
        self.assertAlmostEqual(p["ttm_dps"], 0.51 * 4)
        self.assertEqual(p["next"]["ex_date"], dt.date(2026, 12, 11))
        self.assertTrue(p["next"]["projected"])
        self.assertEqual(p["next"]["pay_date"], dt.date(2026, 12, 25))
        self.assertIsNone(p["cut"])

    def test_announced_event_wins_and_cut_is_detected(self):
        events = quarterly(dt.date(2024, 9, 13), 9, lambda i: 0.5 if i < 8 else 0.25)
        events.append({"ex_date": dt.date(2026, 12, 1), "amount": 0.25, "pay_date": dt.date(2026, 12, 15), "confirmed": True})
        p = D.analyze(events, TODAY)
        self.assertEqual(p["next"]["ex_date"], dt.date(2026, 12, 1))
        self.assertFalse(p["next"]["projected"])
        self.assertEqual(p["cut"]["pct"], -50.0)

    def test_quarterly_to_monthly_switch_is_not_a_cut(self):
        q = quarterly(dt.date(2025, 3, 20), 3, 0.75)                       # 2025-03..2025-09, 3.00/yr
        m = [{"ex_date": dt.date(2025, 10, 20) + dt.timedelta(days=30 * i), "amount": 0.25} for i in range(12)]
        p = D.analyze(q + m, TODAY)
        self.assertEqual(p["frequency"], "매월")
        self.assertIsNone(p["cut"])
        self.assertEqual(p["frequency_changed"], {"from": "분기", "to": "매월"})

    def test_covered_call_payouts_are_variable_not_cut(self):
        amounts = [0.40, 0.31, 0.45, 0.28, 0.39, 0.30, 0.44, 0.27, 0.41, 0.29, 0.46, 0.26, 0.30]
        events = [{"ex_date": dt.date(2025, 10, 1) + dt.timedelta(days=30 * i), "amount": a} for i, a in enumerate(amounts)]
        p = D.analyze(events, TODAY)
        self.assertTrue(p["variable"])
        self.assertIsNone(p["cut"])

    def test_buy_deadlines_follow_each_market_calendar(self):
        # US: ex-date Mon 2026-11-30 -> buy by Fri 11-27 (Thanksgiving 11-26 is closed, 11-27 open)
        self.assertEqual(D.buy_deadline("US", dt.date(2026, 11, 30)), dt.date(2026, 11, 27))
        self.assertEqual(D.buy_deadline("US", dt.date(2026, 11, 27)), dt.date(2026, 11, 25))
        # Korea: record date Thu 2026-12-31 is a KRX closing day; ex-date is the business day before it
        self.assertEqual(D.ex_date_from_record("KS", dt.date(2026, 12, 31)), dt.date(2026, 12, 30))
        self.assertEqual(D.buy_deadline("KS", dt.date(2026, 12, 30)), dt.date(2026, 12, 29))
        self.assertEqual(D.ex_date_from_record("US", dt.date(2026, 12, 1)), dt.date(2026, 12, 1))

    def test_holding_view_cashflow_and_financial_income(self):
        us = quarterly(dt.date(2025, 12, 1), 4, 1.0)   # ex 12-01, 03-02, 06-01, 08-31; next projected 11-30
        kr = [{"ex_date": dt.date(2025, 12, 29), "amount": 1000.0, "pay_date": dt.date(2026, 4, 20)},
              {"ex_date": dt.date(2026, 12, 30), "amount": 1200.0, "pay_date": dt.date(2027, 4, 20), "confirmed": True}]
        h_us = {"symbol": "KO", "market": "US", "qty": 10, "avg_price": 50.0, "current_price": 80.0}
        h_kr = {"symbol": "033780", "market": "KS", "qty": 100, "avg_price": 100000.0, "current_price": 125000.0}
        p_us, p_kr = D.analyze(us, TODAY), D.analyze(kr, TODAY)
        v = D.holding_view(h_us, p_us, TODAY, fx=1400.0)
        self.assertEqual(v["yield_pct"], 5.0)
        self.assertEqual(v["yoc_pct"], 8.0)
        self.assertEqual(v["annual_gross_krw"], 4 * 10 * 1400)
        self.assertEqual(v["annual_net_krw"], round(4 * 10 * 1400 * 0.85))
        flows = D.monthly_cashflow([(h_us, p_us, 1400.0), (h_kr, p_kr, 1400.0)], TODAY)
        self.assertEqual(len(flows), 12)
        self.assertEqual(flows[0]["month"], "2026-10")
        april = next(b for b in flows if b["month"] == "2027-04")
        self.assertEqual(april["net_krw"], round(1200 * 100 * 0.846))
        self.assertEqual(april["confirmed_krw"], april["net_krw"])
        fin = D.financial_income_year([(h_us, p_us, 1400.0), (h_kr, p_kr, 1400.0)], TODAY)
        self.assertEqual(fin["year"], 2026)
        self.assertGreater(fin["received_krw"], 100 * 1000)  # the April KR payment
        self.assertEqual(fin["limit_krw"], 20000000)


class SeasonalAndPendingTests(unittest.TestCase):
    def samsung_like(self):
        rows = []
        for year in (2024, 2025):
            for ex, amount, pay in ((f"{year}-03-28", 361, f"{year}-05-20"), (f"{year}-06-27", 361 if year == 2024 else 367, f"{year}-08-20"),
                                    (f"{year}-09-27", 361 if year == 2024 else 370, f"{year}-11-20"), (f"{year}-12-27", 361 if year == 2024 else 566, f"{year + 1}-04-17")):
                rows.append({"ex_date": dt.date.fromisoformat(ex), "amount": amount, "pay_date": dt.date.fromisoformat(pay)})
        rows.append({"ex_date": dt.date(2026, 3, 30), "amount": 372, "pay_date": dt.date(2026, 5, 29)})
        rows.append({"ex_date": dt.date(2026, 6, 29), "amount": 374, "pay_date": dt.date(2026, 8, 28)})
        return rows

    def test_unannounced_quarter_is_pending_and_year_end_follows_last_year(self):
        p = D.analyze(self.samsung_like(), TODAY)
        self.assertTrue(p["pending"]["unannounced"])
        self.assertGreaterEqual(p["pending"]["pay_date"], TODAY)          # Q3 (record 9/30) paid in November
        self.assertAlmostEqual(p["pending"]["amount"], 374 * 370 / 367, places=3)
        self.assertGreater(p["next"]["amount"], 500)                       # year-end slot ~ 374 x 566/367
        self.assertEqual(p["next"]["pay_date"].month, 4)                   # year-end dividends are paid in April
        self.assertEqual(p["pending"]["pay_date"].month, 11)               # Q3 within ~2 months
        flows = D.schedule(p, TODAY, 12)
        self.assertTrue(flows[0].get("unannounced"))
        self.assertEqual(flows[1]["ex_date"], p["next"]["ex_date"])

    def test_ex_date_passed_but_unpaid_is_still_expected(self):
        events = quarterly(dt.date(2025, 10, 15), 5, 0.5, lag=17)        # last ex 2026-10-14, paid 10-31
        p = D.analyze(events, TODAY)
        flows = D.schedule(p, TODAY, 12)
        self.assertEqual(flows[0]["ex_date"], dt.date(2026, 10, 14))
        self.assertEqual(flows[0]["pay_date"], dt.date(2026, 10, 31))
        self.assertTrue(flows[0]["confirmed"])
        fin = D.financial_income_year([({"symbol": "X", "market": "US", "qty": 10}, p, 1000.0)], TODAY)
        october = 0.5 * 10 * 1000
        self.assertEqual(fin["expected_krw"], october)  # 10-31 payment once; the next (2027-01) is next year


class ReinvestMathTests(unittest.TestCase):
    def test_received_counts_payments_in_the_window_after_tax(self):
        events = quarterly(dt.date(2026, 6, 1), 2, 1.0, lag=30)          # paid 07-01 and 09-30
        p = D.analyze(events, TODAY)
        got = D.received([({"symbol": "KO", "market": "US", "qty": 10}, p, 1400.0)], TODAY, days=30)
        self.assertEqual(got[0]["net"], 8.5)                              # 1.0 x 10 x 0.85, only 09-30
        self.assertEqual(got[0]["currency"], "USD")
        self.assertEqual(D.received([({"symbol": "KO", "market": "US", "qty": 10}, p, 1400.0)], TODAY, days=7), [])

    def test_krx_ticks_and_limit_prices(self):
        self.assertEqual([D.krx_tick(p) for p in (1999, 2000, 19990, 49950, 199900, 499500, 600000)], [1, 5, 10, 50, 100, 500, 1000])
        self.assertEqual(D.limit_price("KS", 194000), 194600.0)            # 194,582 rounded up to a 100 tick
        self.assertEqual(D.limit_price("US", 34.62), 34.73)


class FakeKis:
    def get_domestic_dividend_schedule(self, symbol, f, t):
        return [{"sht_cd": symbol, "record_date": "20261231", "per_sto_divi_amt": "1,200", "divi_pay_dt": "20270420", "divi_kind": "결산"},
                {"sht_cd": symbol, "record_date": "20260630", "per_sto_divi_amt": "0", "divi_kind": "주식"}]

    def get_overseas_rights_schedule(self, symbol, f="", t="", country="US"):
        return [{"ca_title": "현금배당", "div_lock_dt": "20261201", "record_dt": "20261201", "pay_dt": "20261215"},
                {"ca_title": "주식분할", "div_lock_dt": "20261105"}]


class DividendDataTests(unittest.TestCase):
    def setUp(self):
        data_mod._DIVIDEND_MODEL["model"] = D

    def test_kr_rows_use_record_minus_one_business_day(self):
        rows = data_mod.kis_kr_events(FakeKis(), "033780", TODAY)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ex_date"], "2026-12-30")
        self.assertEqual(rows[0]["amount"], 1200.0)
        self.assertEqual(rows[0]["pay_date"], "2027-04-20")

    def test_us_rows_take_the_yahoo_amount(self):
        yahoo = [{"ex_date": "2026-09-01", "amount": 0.51, "source": "yahoo", "confirmed": True}]
        merged = data_mod.merge("US", yahoo, data_mod.kis_us_events(FakeKis(), "KO", TODAY))
        self.assertEqual([e["ex_date"] for e in merged], ["2026-09-01", "2026-12-01"])
        self.assertEqual(merged[1]["amount"], 0.51)
        self.assertTrue(merged[1]["amount_estimated"])
        self.assertEqual(merged[1]["pay_date"], "2026-12-15")

    def test_kis_overrides_a_nearby_yahoo_row(self):
        yahoo = [{"ex_date": "2026-12-29", "amount": 1100.0, "source": "yahoo", "confirmed": True}]
        merged = data_mod.merge("KS", yahoo, data_mod.kis_kr_events(FakeKis(), "033780", TODAY))
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["amount"], 1200.0)
        self.assertEqual(merged[0]["source"], "kis")

    def test_symbols_and_dates(self):
        self.assertEqual(data_mod.yahoo_symbol("033780", "KS"), "033780.KS")
        self.assertEqual(data_mod.yahoo_symbol("brk.b", "US"), "BRK-B")
        self.assertIsNone(data_mod.to_date("00000000"))
        self.assertEqual(data_mod.to_date("2026-12-01"), dt.date(2026, 12, 1))


if __name__ == "__main__":
    unittest.main()
