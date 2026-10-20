"""PAPER's shared day-trade state is admin-only (10-20 isolation test)."""
import unittest
from unittest.mock import MagicMock, patch

from test_daytrade_engine_regressions import _StructStub, daytrade_engine


def _engine(uid, admin):
    struct = _StructStub()
    struct._current_user_id = lambda: uid
    struct._current_user_is_admin = lambda _uid=None: admin
    engine = daytrade_engine.DomesticDaytradeEngine(struct)
    fs = MagicMock()
    fs.exists.return_value = True
    fs.read.json.return_value = {"233740.KS": {"position_qty": 54}}
    engine._fs = lambda: fs
    type(engine)._STATE_VISIBILITY_CACHE.clear()
    return engine, fs


class PaperStateIsolationTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(daytrade_engine, "_PAPER_MODE", True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_admin_and_workers_read_and_write(self):
        for uid in ("admin-id", ""):
            engine, fs = _engine(uid, admin=True)
            self.assertIn("233740.KS", engine._load_state_map())
            engine._save_state_map({"x": {}})
            fs.write.json.assert_called_once()

    def test_a_regular_user_neither_sees_nor_overwrites_it(self):
        engine, fs = _engine("test-user", admin=False)
        self.assertEqual(engine._load_state_map(), {})
        with self.assertRaises(RuntimeError):
            engine._save_state_map({})
        fs.write.json.assert_not_called()

    def test_live_files_are_per_account_and_not_gated(self):
        with patch.object(daytrade_engine, "_PAPER_MODE", False):
            engine, _ = _engine("test-user", admin=False)
            engine.struct.live_data_scope = "scope"
            self.assertIn("233740.KS", engine._load_state_map())


if __name__ == "__main__":
    unittest.main()
