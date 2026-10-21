"""deploy/web_hooks.py: IDE exposure, security headers, absolute og: URLs."""
import importlib.util
import os
import unittest
from pathlib import Path

try:
    import flask
except ImportError:
    flask = None

HOOKS = Path(__file__).resolve().parents[1] / "deploy" / "web_hooks.py"


def _hooks():
    spec = importlib.util.spec_from_file_location("stock8_web_hooks_test", HOOKS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INDEX = ('<html><head><meta property="og:image" content="/assets/brand/og-image.png">'
         '<meta property="og:url" content="/"></head></html>')


@unittest.skipIf(flask is None, "flask not installed")
class WebHookTests(unittest.TestCase):
    def setUp(self):
        self.hooks = _hooks()
        app = flask.Flask(__name__)
        hooks = self.hooks
        app.before_request(lambda: hooks.before_request(None))
        app.after_request(lambda response: hooks.after_request(None, response))
        app.add_url_rule("/", "index", lambda: INDEX)
        app.add_url_rule("/wiz/ide", "ide", lambda: "ide")
        app.add_url_rule("/wiz/ide/<path:p>", "ide_sub", lambda p: "ide")
        app.add_url_rule("/wiz/api/page.dashboard/load", "api", lambda: "api")
        self.client = app.test_client()
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in ("STOCK8_IDE_ENABLED", "STOCK8_PUBLIC_ORIGIN")])

    def test_ide_only_for_direct_loopback(self):
        self.assertEqual(self.client.get("/wiz/ide").status_code, 200)
        self.assertEqual(self.client.get("/wiz/ide/api/x/y", headers={"X-Forwarded-For": "1.2.3.4"}).status_code, 404)
        self.assertEqual(self.client.get("/wiz/ide", headers={"X-Real-IP": "1.2.3.4"}).status_code, 404)
        self.assertEqual(self.client.get("/wiz/ide", environ_base={"REMOTE_ADDR": "10.0.0.5"}).status_code, 404)
        os.environ["STOCK8_IDE_ENABLED"] = "false"
        self.assertEqual(self.client.get("/wiz/ide").status_code, 404)
        # The app's own API under /wiz/api stays reachable through a proxy.
        self.assertEqual(self.client.get("/wiz/api/page.dashboard/load", headers={"X-Forwarded-For": "1.2.3.4"}).status_code, 200)

    def test_security_headers_and_absolute_og_urls(self):
        res = self.client.get("/", headers={"X-Forwarded-Proto": "https", "Host": "stock8.example"})
        self.assertEqual(res.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(res.headers["X-Frame-Options"], "SAMEORIGIN")
        body = res.get_data(as_text=True)
        self.assertIn('content="https://stock8.example/assets/brand/og-image.png"', body)
        self.assertIn('property="og:url" content="https://stock8.example/"', body)
        os.environ["STOCK8_PUBLIC_ORIGIN"] = "https://stock8.kr/"
        self.assertIn('content="https://stock8.kr/assets/brand/og-image.png"', self.client.get("/").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
