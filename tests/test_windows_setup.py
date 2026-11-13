"""Dependency transaction tests; no network, QQ, model or real installation."""
from pathlib import Path
from types import SimpleNamespace
import contextlib
import io
import json
import tempfile
import unittest
from unittest.mock import patch

from scripts import windows_setup as setup


class FakePip:
    def __init__(self, command, success=True, **kwargs):
        destination = Path(command[command.index("--target") + 1])
        (destination / "new-marker").write_text("new", encoding="utf-8")
        self.stdout = io.StringIO("dependency fixture\n")
        self.success = success

    def wait(self):
        return 0 if self.success else 1


class WindowsSetupTests(unittest.TestCase):
    def fixture(self, directory):
        root = Path(directory).resolve()
        (root / "requirements-windows.lock").write_text("fixture==1\n", encoding="utf-8")
        personal = root / "instances/my-fish/persona"
        personal.mkdir(parents=True)
        (personal / "identity.md").write_text("private fixture", encoding="utf-8")
        return root

    def prepare(self, root, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            setup.prepare(root, **kwargs)

    def test_fresh_install_commits_runtime_without_touching_persona(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.fixture(directory)
            with patch.object(setup.subprocess, "Popen", FakePip), patch.object(setup.subprocess, "run", return_value=SimpleNamespace(returncode=0)), patch.object(setup, "probe", return_value=True):
                self.prepare(root)
            self.assertTrue((root / ".runtime/site-packages/new-marker").exists())
            self.assertTrue(json.loads((root / ".runtime/local.json").read_text())["python"])
            self.assertEqual((root / "instances/my-fish/persona/identity.md").read_text(), "private fixture")

    def test_failed_download_preserves_old_dependencies_and_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.fixture(directory)
            old = root / ".runtime/site-packages"
            old.mkdir(parents=True)
            (old / "old-marker").write_text("old")
            (root / ".runtime/local.json").write_text('{"python":"original"}')
            with patch.object(setup.subprocess, "Popen", side_effect=lambda command, **kw: FakePip(command, success=False)), self.assertRaises(RuntimeError):
                self.prepare(root)
            self.assertEqual((old / "old-marker").read_text(), "old")
            self.assertEqual(json.loads((root / ".runtime/local.json").read_text())["python"], "original")
            self.assertFalse(list((root / ".runtime").glob("install-staging-*")))

    def test_post_install_validation_failure_restores_old_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.fixture(directory)
            old = root / ".runtime/site-packages"
            old.mkdir(parents=True)
            (old / "old-marker").write_text("old")
            with patch.object(setup.subprocess, "Popen", FakePip), patch.object(setup.subprocess, "run", return_value=SimpleNamespace(returncode=0)), patch.object(setup, "probe", return_value=False), self.assertRaises(RuntimeError):
                self.prepare(root)
            self.assertEqual((old / "old-marker").read_text(), "old")
            self.assertFalse((old / "new-marker").exists())

    def test_check_only_never_installs_or_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.fixture(directory)
            with patch.object(setup, "probe", return_value=True), patch.object(setup.subprocess, "Popen") as pip:
                self.prepare(root, check=True)
                pip.assert_not_called()
            self.assertFalse((root / ".runtime").exists())

    def test_cleanup_rejects_personal_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.fixture(directory)
            with self.assertRaises(RuntimeError):
                setup.clean_generated(root / "instances/my-fish", root / ".runtime")
            self.assertTrue((root / "instances/my-fish/persona/identity.md").exists())


if __name__ == "__main__":
    unittest.main()
