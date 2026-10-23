"""10-23 LIVE: a LOC buy line short of USD must not re-query buying power and
re-log the same skip on every ~40 s pass; it is re-checked after a pause."""
import unittest

import test_infinitebuy_loc_schedule_regressions as base

engine_module = base.engine_module

SHORT = {"executable_amount": 0, "executable_qty": 0, "broker_amount": 0, "broker_qty": 0}


class LocShortfallRecheckTests(unittest.TestCase):
    def _engine(self, info):
        engine, kis_api, logs = base.InfiniteBuyLocScheduleRegressionTests._engine(
            None, buying_power_info=info,
            watchlist_rows=[{"id": "w1", "symbol": "TQQQ", "exchange": "NASD", "is_active": True}],
            cycle_rows=[{"id": "c1", "symbol": "TQQQ", "status": "ACTIVE"}])
        calls = []
        original = kis_api.get_buying_power_info

        def counted(**kw):
            calls.append(kw)
            if isinstance(info, Exception):
                raise info
            return original(**kw)
        kis_api.get_buying_power_info = counted
        clock = [1000.0]
        engine._loc_clock = lambda: clock[0]
        return engine, kis_api, logs, calls, clock

    def test_short_line_is_rechecked_quietly_then_after_the_pause(self):
        engine, kis_api, logs, calls, clock = self._engine(SHORT)
        first = engine.schedule_loc_buys()
        self.assertEqual(len(calls), 1)
        self.assertEqual(first["error_count"], 1)
        logged = len(logs)
        clock[0] += 40
        second = engine.schedule_loc_buys()
        self.assertEqual(len(calls), 1)  # no buying-power query
        self.assertEqual(len([l for l in logs[logged:] if l["event_type"].startswith("LOC_BUY_")]), 0)
        self.assertEqual(second["skipped_count"], 1)
        self.assertIn("재확인", second["skipped"][0]["reason"])
        self.assertFalse(engine_module.Engine.__dict__.get("_loc_buy_recheck"))  # per instance only
        clock[0] += engine_module.LOC_SHORTFALL_RECHECK_SEC
        engine.schedule_loc_buys()
        self.assertEqual(len(calls), 2)
        self.assertEqual(kis_api.buy_calls, [])

    def test_rate_limited_query_waits_briefly(self):
        engine, _kis, _logs, calls, clock = self._engine(RuntimeError("USD 주문 가능액 조회 실패: rt_cd=1, msg=초당 거래건수를 초과하였습니다."))
        engine.schedule_loc_buys()
        engine.schedule_loc_buys()
        self.assertEqual(len(calls), 1)
        clock[0] += engine_module.LOC_RATE_LIMIT_RECHECK_SEC + 1
        engine.schedule_loc_buys()
        self.assertEqual(len(calls), 2)

    def test_a_fresh_engine_rechecks_at_once(self):
        engine, _kis, _logs, calls, _clock = self._engine(SHORT)
        engine.schedule_loc_buys()
        again, _k, _l, calls2, _c = self._engine(SHORT)
        again.schedule_loc_buys()
        self.assertEqual(len(calls2), 1)


if __name__ == "__main__":
    unittest.main()
