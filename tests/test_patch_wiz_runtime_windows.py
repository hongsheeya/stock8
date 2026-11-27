"""The Windows WIZ builder patch must apply once, stay idempotent and refuse unknown code."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/patch-wiz-runtime-windows.py'
spec = importlib.util.spec_from_file_location('patch_wiz_runtime_windows', SCRIPT)
patcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)

# Excerpt of the stock WIZ season 2.5.2 builder around both patched lines.
STOCK_BUILDER = (
    "class Model:\n"
    "    def _search(self, target_file, result=[], extension=None):\n"
    "        if fs.isdir(target_file):\n"
    "            files = fs.files(target_file)\n"
    "            for f in files:\n"
    "                self._search(os.path.join(target_file, f), result=result, extension=extension)\n"
    "            return result\n"
    "\n"
    "    def _prepare(self):\n"
    "        # build tailwindcss\n"
    "        if fs.exists(\"./build/node_modules/.bin/tailwindcss\"):\n"
    "            build_base_path = fs.abspath(\"build\")\n"
    "            Util.execute(f\"cd {build_base_path} && node_modules/.bin/tailwindcss -o tailwind.min.css --minify\", False)\n"
    "\n"
)


class PatchSourceTests(unittest.TestCase):
    def test_patches_both_posix_assumptions(self):
        patched, applied = patcher.patch_source(STOCK_BUILDER)
        self.assertEqual(applied, ['path separators', 'tailwind command'])
        self.assertIn('.replace("\\\\", "/")', patched)
        self.assertIn('tailwindcss.cmd', patched)
        # Non-Windows hosts keep the original command.
        self.assertIn('Util.execute(f"cd {build_base_path} && node_modules/.bin/tailwindcss', patched)
        compile(patched, 'builder.py', 'exec')

    def test_second_run_changes_nothing(self):
        patched, _ = patcher.patch_source(STOCK_BUILDER)
        again, applied = patcher.patch_source(patched)
        self.assertEqual(applied, [])
        self.assertEqual(again, patched)

    def test_unknown_builder_is_refused(self):
        with self.assertRaises(ValueError):
            patcher.patch_source(STOCK_BUILDER.replace('node_modules/.bin/tailwindcss -o', 'npx tailwindcss -o'))


class MainTests(unittest.TestCase):
    def test_patches_runtime_file_keeps_crlf_and_backup(self):
        with tempfile.TemporaryDirectory() as root:
            builder = Path(root, 'plugin/workspace/model/builder.py')
            builder.parent.mkdir(parents=True)
            builder.write_bytes(STOCK_BUILDER.replace('\n', '\r\n').encode('utf-8'))
            self.assertEqual(patcher.main(['x', root]), 0)
            data = builder.read_bytes()
            self.assertIn(b'tailwindcss.cmd', data)
            self.assertNotIn(b'\n', data.replace(b'\r\n', b''))
            backup = Path(str(builder) + '.stock8-orig')
            self.assertEqual(backup.read_bytes(), STOCK_BUILDER.replace('\n', '\r\n').encode('utf-8'))
            self.assertEqual(patcher.main(['x', root]), 0)
            self.assertEqual(builder.read_bytes(), data)

    def test_missing_runtime_fails(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(patcher.main(['x', root]), 1)


if __name__ == '__main__':
    unittest.main()
