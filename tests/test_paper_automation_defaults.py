"""A fresh PAPER database must start with every automation switch OFF."""
import ast
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'src/portal/trading/model/struct.py'

# Switches that make the worker place, reserve, or exit orders on their own.
AUTOMATION_KEYS = {
    'auto_trade_enabled', 'loc_auto_schedule_enabled', 'auto_start_next_cycle_enabled',
    'daytrade_auto_enabled', 'daytrade_exit_watch_enabled',
    'daytrade_us_auto_enabled', 'daytrade_us_exit_watch_enabled',
}


def _load(full_access=True):
    tree = ast.parse(SOURCE.read_text(encoding='utf-8-sig'))
    keys = next(n for n in tree.body if isinstance(n, ast.Assign)
                and any(getattr(t, 'id', '') == 'PAPER_AUTOMATION_DEFAULT_OFF_KEYS' for t in n.targets))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Struct')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_initialize_paper_full_access')
    env = {'PAPER_DAYTRADE_FULL_ACCESS': full_access}
    exec(compile(ast.Module(body=[keys, method], type_ignores=[]), str(SOURCE), 'exec'), env)
    return env


class ConfigDouble:
    def __init__(self, config=None):
        self.config = dict(config or {})
        self.writes = {}

    def get_config(self, key, default=None):
        return self.config.get(key, default)

    def _write_config_value(self, key, value, description='', is_secret=False):
        self.config[key] = str(value)
        self.writes[key] = str(value)


class PaperAutomationDefaultTests(unittest.TestCase):
    def test_constant_covers_every_automation_switch(self):
        self.assertEqual(set(_load()['PAPER_AUTOMATION_DEFAULT_OFF_KEYS']), AUTOMATION_KEYS)

    def test_fresh_paper_db_writes_automation_off_explicitly(self):
        env = _load()
        obj = ConfigDouble()
        env['_initialize_paper_full_access'](obj)
        for key in AUTOMATION_KEYS:
            # Explicit "false": some readers treat a missing value as ON.
            self.assertEqual(obj.writes.get(key), 'false', key)
        self.assertNotIn('true', {obj.writes[k] for k in AUTOMATION_KEYS})
        # Feature access, guards and budget defaults stay as before.
        self.assertEqual(obj.writes['daytrade_feature_enabled'], 'true')
        self.assertEqual(obj.writes['daytrade_daily_loss_halt_enabled'], 'true')
        self.assertEqual(obj.writes['paper_full_access_initialized_v2'], 'true')

    def test_existing_db_keeps_user_toggles(self):
        env = _load()
        config = {k: 'true' for k in AUTOMATION_KEYS}
        config.update(paper_full_access_initialized_v2='true', paper_dynamic_allocation_initialized_v1='true')
        obj = ConfigDouble(config)
        env['_initialize_paper_full_access'](obj)
        self.assertEqual(obj.writes, {})
        self.assertTrue(all(obj.config[k] == 'true' for k in AUTOMATION_KEYS))

    def test_hard_locked_or_live_writes_nothing(self):
        env = _load(full_access=False)
        obj = ConfigDouble()
        env['_initialize_paper_full_access'](obj)
        self.assertEqual(obj.writes, {})


if __name__ == '__main__':
    unittest.main()
