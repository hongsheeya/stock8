"""11-05: a bare '@' in template text is Angular block syntax (@if/@for).

'{{qty}}주 @ {{price}}' on the dashboard failed JIT compilation and left the
whole /dashboard blank. Text must use '&#64;' (or another character);
'@' inside quoted attribute values (placeholder="name@example.com") is fine.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
QUOTED = re.compile(r'"[^"]*"|\'[^\']*\'')


def bare_at_lines(text):
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        if "@" in QUOTED.sub("", line):
            found.append((number, stripped))
    return found


class TemplateAtSignTests(unittest.TestCase):
    def test_no_bare_at_in_pug_templates(self):
        problems = []
        for path in sorted((ROOT / "src" / "app").glob("*/view.pug")):
            for number, line in bare_at_lines(path.read_text(encoding="utf-8")):
                problems.append(f"{path.relative_to(ROOT)}:{number}: {line}")
        self.assertEqual(problems, [], "use &#64; instead of a bare @ in template text")

    def test_detector(self):
        self.assertEqual(len(bare_at_lines("span {{q}}주 @ {{p}}")), 1)
        self.assertEqual(bare_at_lines('input(placeholder="name@example.com")'), [])
        self.assertEqual(bare_at_lines("//- note @ here"), [])


if __name__ == "__main__":
    unittest.main()
