from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import json
import tempfile
import threading
import unittest
import zipfile
from unittest.mock import patch

from fatfish.core import ROOT, FishManager
from fatfish.server import LocalServer
from scripts.build_release import DIRECTORIES, DISTRIBUTION_FILES, FILES, build


class InstanceSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manager = FishManager(instance_name="verification-fixture")
        cls.manager.initialize()
        cls.server = LocalServer(("127.0.0.1", 0), cls.manager)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def request(self, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        req = Request(self.base + path, data=data, headers=headers or {}, method="POST" if data else "GET")
        try:
            with urlopen(req, timeout=10) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def test_configuration_requires_session_token(self):
        code, _ = self.request("/api/settings")
        self.assertEqual(code, 401)
        code, _ = self.request("/api/qq-start", {})
        self.assertEqual(code, 401)

    def test_account_check_failure_does_not_start_core(self):
        data = {"has_api_key": True, "qq_account": "1234567", "groups": ["7654321"], "users": []}
        with patch.object(self.manager, "settings", return_value=data), patch.object(self.manager, "check_qq", side_effect=ValueError("登录账号不一致")), patch.object(self.manager, "start") as start:
            code, _ = self.request("/api/start", {}, {"X-Fatfish-Token": self.server.token})
            self.assertEqual(code, 400)
            start.assert_not_called()

    def test_dns_rebinding_and_foreign_origin_rejected(self):
        for headers in ({"Host": "attacker.invalid"}, {"Origin": "https://attacker.invalid"}):
            code, _ = self.request("/api/settings", headers={"X-Fatfish-Token": self.server.token, **headers})
            self.assertEqual(code, 403)

    def test_secret_saved_but_not_exposed_and_blank_preserves(self):
        headers = {"X-Fatfish-Token": self.server.token}
        secret = "verification-only-secret-not-real"
        code, data = self.request("/api/settings", {"api_key": secret}, headers)
        self.assertEqual(code, 200, data)
        self.assertTrue(data["has_api_key"])
        self.assertNotIn(secret, json.dumps(data))
        code, _ = self.request("/api/settings", {"api_key": ""}, headers)
        self.assertEqual(code, 200)
        self.assertEqual(self.manager.settings(private=True)["api_key"], secret)
        self.assertNotIn(secret, self.manager.redact("key=" + secret))

    def test_bad_setting_does_not_partially_overwrite_persona(self):
        original = self.manager.settings()["persona"]
        code, _ = self.request("/api/settings", {"groups": ["not-a-number"], "persona": "should-not-be-saved"}, {"X-Fatfish-Token": self.server.token})
        self.assertEqual(code, 400)
        self.assertEqual(self.manager.settings()["persona"], original)

    def test_path_traversal_cannot_read_personal_files(self):
        code, _ = self.request("/api/../../instances/my-fish/fatfish.json", headers={"X-Fatfish-Token": self.server.token})
        self.assertEqual(code, 404)

    def test_no_key_or_target_prevents_accidental_start(self):
        with patch.object(FishManager, "settings", return_value={"has_api_key": False}), self.assertRaises(ValueError):
            FishManager(instance_name="my-fish").start()


class CleanReleaseTests(unittest.TestCase):
    def test_personal_data_cannot_enter_release(self):
        with tempfile.TemporaryDirectory(prefix="fatfish-package-") as temporary:
            root = Path(temporary)
            for name in FILES:
                (root / name).write_text("program", encoding="utf-8")
            for name in DIRECTORIES:
                directory = root / name
                directory.mkdir(parents=True, exist_ok=True)
                (directory / "program.py").write_text("pass", encoding="utf-8")
            for name in DISTRIBUTION_FILES:
                path = root / "templates" / "distribution" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("clean", encoding="utf-8")
            (root / "templates/persona.md").write_text("", encoding="utf-8")
            (root / "layout.json").write_text('{"layout":"flat-install"}', encoding="utf-8")
            for name in ("instances/my-fish/key.txt", "instances/my-fish/qq/data/login.txt", ".external/NapCat/config/private.json", "backups/private.zip", ".runtime/local.json", "engine/MaiBot/data/private.txt", "components/qq-connector/config.toml"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("PERSONAL_SECRET_MARKER", encoding="utf-8")
            output = build(root)
            with zipfile.ZipFile(output) as archive:
                self.assertIsNone(archive.testzip())
                self.assertTrue(archive.namelist())
                for name in archive.namelist():
                    self.assertNotIn(b"PERSONAL_SECRET_MARKER", archive.read(name))
                    self.assertNotIn("/instances/", name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
