"""LIVE coin worker body (struct._ensure_live_coin_worker.coin_job) with fakes:
OFF / non-admin / missing owner never build an engine or touch Upbit; ON runs
the engine under the owner's session; a second process (no file lock) never trades."""
import ast
import datetime
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import flask


class Stop(BaseException):
    pass


class Wake:
    def __init__(self, rounds):
        self.rounds, self.waits = rounds, []

    def wait(self, delay):
        self.waits.append(delay)
        if len(self.waits) >= self.rounds:
            raise Stop()

    def clear(self):
        pass


def _coin_job():
    tree = ast.parse((Path(__file__).resolve().parents[1] / "src/portal/trading/model/struct.py").read_text(encoding="utf-8-sig"))
    outer = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_ensure_live_coin_worker")
    return next(n for n in ast.walk(outer) if isinstance(n, ast.FunctionDef) and n.name == "coin_job")


class LiveCoinWorkerTests(unittest.TestCase):
    fake_sys = type("FakeSys", (), {})()

    def run_job(self, policies, admin=True, owner_exists=True, lock=True, rounds=None, step_errors=()):
        app = flask.Flask("coin-worker-test")
        app.secret_key = "test-only"
        sessions = []
        engine = Mock()
        errors = list(step_errors)

        def step():
            sessions.append(flask.session.get("id"))
            if errors:
                raise errors.pop(0)
            return {"next_delay": 3}

        engine.step.side_effect = step
        trading = NS(coin_build_engine=Mock(return_value=engine))
        policy_iter = iter(policies)
        fake_self = NS(
            coin_policy_read=lambda: next(policy_iter),
            orm=NS(use=lambda name: NS(get=lambda id: {"id": id} if owner_exists else None)),
            _current_user_is_admin=lambda uid: admin,
            _coin_process_lock=lambda: object() if lock else None,
        )
        registry = {"status": "starting", "error": "", "wake": Wake(rounds or len(policies))}
        scope = {"self": fake_self, "registry": registry, "wiz": NS(server=NS(app=NS(flask=app))), "_sys": self.fake_sys,
                 "Struct": lambda: trading, "_kst_now": lambda: datetime.datetime(2026, 10, 22, 9)}
        exec(compile(ast.Module(body=[_coin_job()], type_ignores=[]), "<coin-worker>", "exec"), scope)
        try:
            scope["coin_job"]()
        except Stop:
            pass
        return trading, engine, registry, sessions

    def policy(self, mode, owner="admin-1", fp="abc"):
        return {"mode": mode, "owner_user_id": owner, "account_fp": fp, "markets": ["KRW-BTC"], "seed_krw": 1000000}

    def test_off_never_builds_an_engine(self):
        trading, engine, registry, _ = self.run_job([self.policy("off"), self.policy("off")])
        trading.coin_build_engine.assert_not_called()
        self.assertEqual(registry["status"], "off")

    def test_off_closes_a_stop_watch_stream_left_from_on(self):
        stream = Mock()
        self.fake_sys = type("FakeSys", (), {})()
        self.fake_sys.__dict__["_stock8_upbit_trade_stream"] = stream
        self.run_job([self.policy("off")])
        stream.watch.assert_called_with([])

    def test_non_admin_or_deleted_owner_is_off(self):
        for kwargs in ({"admin": False}, {"owner_exists": False}):
            with self.subTest(**kwargs):
                trading, engine, registry, _ = self.run_job([self.policy("live")], **kwargs)
                trading.coin_build_engine.assert_not_called()
                self.assertEqual(registry["status"], "off")
        trading, _, registry, _ = self.run_job([self.policy("shadow", owner="")])
        trading.coin_build_engine.assert_not_called()

    def test_on_runs_under_the_owner_session_and_reuses_the_engine(self):
        trading, engine, registry, sessions = self.run_job([self.policy("shadow")] * 3)
        self.assertEqual(sessions, ["admin-1"] * 3)
        trading.coin_build_engine.assert_called_once()
        self.assertEqual(registry["status"], "shadow")
        self.assertEqual(registry["wake"].waits, [3.0, 3.0, 3.0])

    def test_mode_or_key_change_rebuilds_and_off_drops_the_engine(self):
        trading, engine, registry, _ = self.run_job([
            self.policy("shadow"), self.policy("live"), self.policy("live", fp="other"), self.policy("off")])
        self.assertEqual(trading.coin_build_engine.call_count, 3)
        self.assertEqual(engine.step.call_count, 3)
        self.assertEqual(registry["status"], "off")

    def test_engine_error_is_reported_and_retried_with_a_fresh_engine(self):
        trading, engine, registry, _ = self.run_job([self.policy("shadow")] * 2, step_errors=[RuntimeError("boom")])
        self.assertEqual(registry["wake"].waits, [30.0, 3.0])  # back off, then recover
        self.assertEqual(trading.coin_build_engine.call_count, 2)
        self.assertEqual(registry["status"], "shadow")
        self.assertEqual(registry["error"], "")

    def test_second_process_without_the_lock_never_trades(self):
        trading, engine, registry, _ = self.run_job([self.policy("live")], lock=False, rounds=1)
        trading.coin_build_engine.assert_not_called()
        self.assertEqual(registry["status"], "locked_elsewhere")


if __name__ == "__main__":
    unittest.main()
