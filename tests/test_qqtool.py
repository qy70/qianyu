from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile

from fatfish.qqtool import QQTool, OwnedProcess, extract_checked


class QQToolTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="fatfish-qq-")
        self.root = Path(self.temporary.name)
        self.config = {"qq_host": "127.0.0.1", "qq_port": 39876, "qq_token": "fixture-onebot-token", "qq_account": "1234567"}
        self.manager = SimpleNamespace(root=self.root, instance=self.root / "instances" / "fixture",
                                       settings=lambda **kw: self.config.copy(), redact=lambda s: s)
        self.q = QQTool(self.manager)

    def tearDown(self):
        self.q.stop()
        self.temporary.cleanup()

    def test_configuration_is_isolated_and_loopback_only(self):
        with patch("fatfish.qqtool.tcp_open", return_value=False), patch.dict(os.environ, {"NAPCAT_QUICK_PASSWORD": "unrelated-environment-secret"}):
            env = self.q._configure()
        self.assertTrue(Path(env["NAPCAT_QQ_DATA_DIR"]).is_relative_to(self.manager.instance))
        self.assertNotIn("NAPCAT_QUICK_PASSWORD", env)
        web = json.loads((self.q.work / "config/webui.json").read_text())
        self.assertEqual(web["host"], "127.0.0.1")
        ob = json.loads((self.q.work / "config/onebot11_1234567.json").read_text())
        self.assertEqual(ob["network"]["websocketServers"][0]["token"], self.config["qq_token"])
        self.assertNotIn(web["token"], json.dumps(self.q.snapshot()))
        with patch("fatfish.qqtool.tcp_open", return_value=True):
            with self.assertRaisesRegex(ValueError, "占用"):
                self.q._configure()

    def test_mock_login_qr_confirmation_account_and_offline(self):
        outer = self
        state = {"isLogin": False, "loginPhase": "waiting_qrcode", "qrcodeurl": "https://example.invalid/fixture-only-qr"}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                if self.path == "/api/auth/login":
                    outer.assertEqual(body["hash"], hashlib.sha256(b"fixture-secret.napcat").hexdigest())
                    data = {"Credential": "fixture-credential"}
                else:
                    outer.assertEqual(self.headers["Authorization"], "Bearer fixture-credential")
                    data = {"uin": "1234567"} if self.path.endswith("GetQQLoginInfo") else state
                content = json.dumps({"code": 0, "data": data}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.q.port, self.q.web_token = server.server_port, "fixture-secret"
        try:
            self.q._poll()
            self.assertEqual(self.q.snapshot()["phase"], "waiting_qr")
            self.assertTrue(self.q.snapshot()["qr"].startswith("data:image/svg+xml;base64,"))
            state["loginPhase"] = "qrcode_scanned"
            self.q._poll()
            self.assertEqual(self.q.snapshot()["phase"], "confirming")
            state["isLogin"] = True
            self.q._poll()
            self.assertEqual(self.q.snapshot()["phase"], "online")
            self.assertEqual(self.q.snapshot()["qr"], "")
            self.config["qq_account"] = "7654321"
            self.q._poll()
            self.assertEqual(self.q.snapshot()["phase"], "mismatch")
            state["isLogin"] = False
            self.q._poll()
            self.assertEqual(self.q.snapshot()["phase"], "confirming")
        finally:
            server.shutdown()
            server.server_close()

    def test_install_failure_does_not_loop_or_start_process(self):
        self.q._install = lambda: (_ for _ in ()).throw(ValueError("模拟下载失败"))
        with patch("fatfish.qqtool.OwnedProcess") as process:
            self.q.ensure()
            self.q.thread.join(timeout=3)
            self.assertFalse(self.q.thread.is_alive())
            self.assertEqual(self.q.snapshot()["phase"], "error")
            process.assert_not_called()

    def test_archive_traversal_rejected_before_any_extraction(self):
        archive = self.root / "bad.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("program", "okay")
            z.writestr("../escape", "bad")
        with self.assertRaises(ValueError):
            extract_checked(archive, self.root / "target")
        self.assertFalse((self.root / "escape").exists())
        self.assertFalse((self.root / "target/program").exists())

    def test_stopping_owned_job_keeps_unrelated_process_alive(self):
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        sentinel = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], creationflags=flags)
        try:
            owned = OwnedProcess([sys.executable, "-c", "import time; time.sleep(60)"])
            self.assertIsNone(owned.poll())
            owned.close()
            self.assertIsNotNone(owned.poll())
            self.assertIsNone(sentinel.poll())
        finally:
            sentinel.terminate()
            sentinel.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
