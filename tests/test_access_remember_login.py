"""Login page: '로그인 유지' makes the session cookie persistent; unchecked it
ends when the browser closes. Offline: no server, no user DB."""
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1] / "src"


class Status(Exception):
    def __init__(self, code, data):
        super().__init__(code)
        self.code, self.data = code, data


def _status(code=200, **data):
    raise Status(code, data)


class _FlaskSession(dict):
    permanent = False


def _login(query, user=None):
    flask_session = _FlaskSession()
    user = user if user is not None else {"id": "u1", "email": "a@b.co", "name": "A", "role": "user"}
    session_model = NS(use=lambda: NS(set=lambda **kw: flask_session.update(kw), clear=flask_session.clear))
    struct = NS(user=NS(authenticate=lambda email, password: user or None))
    wiz = NS(model=lambda name: session_model if name == "portal/season/session" else struct,
             request=NS(query=lambda key, default="": query.get(key, default)),
             response=NS(status=_status),
             server=NS(package=NS(flask=NS(session=flask_session))))
    env = {"wiz": wiz, "__name__": "access_api"}
    exec(compile((ROOT / "app" / "page.access" / "api.py").read_text(encoding="utf-8"), "api.py", "exec"), env)
    try:
        env["login"]()
    except Status as status:
        return status.code, flask_session
    raise AssertionError("login() did not respond")


class RememberLoginTests(unittest.TestCase):
    def test_checked_keeps_the_session_after_the_browser_closes(self):
        for value in ("true", "1", "on"):
            code, session = _login({"email": "a@b.co", "password": "pw123456", "remember": value})
            self.assertEqual(code, 200)
            self.assertTrue(session.permanent, value)
            self.assertEqual(session["id"], "u1")

    def test_unchecked_or_missing_ends_with_the_browser(self):
        for query in ({"remember": "false"}, {"remember": ""}, {}):
            code, session = _login(dict(query, email="a@b.co", password="pw123456"))
            self.assertEqual(code, 200)
            self.assertFalse(session.permanent, query)

    def test_failed_login_sets_nothing(self):
        code, session = _login({"email": "a@b.co", "password": "wrong", "remember": "true"}, user={})
        self.assertEqual(code, 401)
        self.assertFalse(session.permanent)
        self.assertNotIn("id", session)

    def test_login_page_has_the_checkbox_bound_to_remember(self):
        pug = (ROOT / "app" / "page.access" / "view.pug").read_text(encoding="utf-8")
        ts = (ROOT / "app" / "page.access" / "view.ts").read_text(encoding="utf-8")
        self.assertIn('[(ngModel)]="loginData.remember"', pug)
        self.assertIn("로그인 유지", pug)
        self.assertIn("remember: this.loginData.remember ? 'true' : 'false'", ts)


if __name__ == "__main__":
    unittest.main()
