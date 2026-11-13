"""Verify actual MaiBot-generated configuration stays neutral and editable."""
from pathlib import Path
import json
import os
import shutil
import tempfile
import unittest
import tomlkit
from fatfish.core import FishManager, ROOT


class NeutralProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_temp = tempfile.TemporaryDirectory(prefix="qianyu-neutral-base-")
        cls.fixture_root = Path(cls.fixture_temp.name)
        for relative in ("engine/MaiBot", "components/qq-connector", "components/qianyu-style", "components/qianyu-social"):
            shutil.copytree(ROOT / relative, cls.fixture_root / relative, ignore=shutil.ignore_patterns("__pycache__", ".git", "*.pyc"))
        for relative in ("templates/persona.md", "templates/topic-reply.json"):
            target = cls.fixture_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
        manager = FishManager(cls.fixture_root)
        original = manager.env
        def fixture_env():
            env = original()
            env["PYTHONPATH"] = os.pathsep.join((str(ROOT / ".runtime/site-packages"), str(cls.fixture_root / "engine/MaiBot"), str(cls.fixture_root)))
            return env
        manager.env = fixture_env
        manager.initialize()

    @classmethod
    def tearDownClass(cls):
        cls.fixture_temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="qianyu-neutral-test-")
        self.addCleanup(self.temp.cleanup)
        self.manager = FishManager(Path(self.temp.name))
        shutil.copytree(self.fixture_root / "instances", self.manager.root / "instances")

    def bot(self):
        return tomlkit.parse((self.manager.instance / "config/bot_config.toml").read_text(encoding="utf-8"))

    def test_new_profile_has_no_role_style_personal_data_or_automatic_memory(self):
        settings = self.manager.settings(private=True)
        self.assertEqual(settings["persona"], "")
        self.assertEqual(settings["manual_memory"], "")
        self.assertEqual(settings["nickname"], "DeepSeek")
        self.assertFalse(settings["memory_enabled"])
        self.assertFalse(settings["collect_emoji"])
        self.assertEqual(settings["qq_account"], "")
        self.assertEqual((self.manager.instance / "memory/notes/00-核心记忆.md").read_text(), "")
        self.assertFalse((self.manager.instance / "persona/style-pack/manifest.json").exists())
        self.assertEqual(list((self.manager.instance / "knowledge").glob("[!_]*")), [])
        bot = self.bot()
        self.assertEqual(bot["bot"]["alias_names"], [])
        self.assertEqual(bot["personality"]["personality"], "你是一个 AI 助手。")
        for key in ("reply_style", "behavior_style", "selected_profile"):
            self.assertEqual(bot["personality"][key], "")
        for key in ("multiple_reply_style", "profiles"):
            self.assertEqual(bot["personality"][key], [])
        self.assertEqual(bot["chat"]["reply_style"]["group_chat_prompt"], "")
        self.assertEqual(bot["chat"]["reply_style"]["private_chat_prompts"], "")
        self.assertTrue(json.loads((self.manager.instance / "persona/default-profile.json").read_text())["initialized"])

    def test_later_user_style_and_aliases_survive_normal_save(self):
        path = self.manager.instance / "config/bot_config.toml"
        bot = self.bot()
        bot["personality"].update(reply_style="user style", behavior_style="user behavior", multiple_reply_style=["user alternate"])
        bot["bot"]["alias_names"] = ["user alias"]
        path.write_text(tomlkit.dumps(bot), encoding="utf-8")
        self.manager.save({"persona": "User chosen personality", "manual_memory": "User chosen fact"})
        bot = self.bot()
        self.assertEqual(bot["personality"]["reply_style"], "user style")
        self.assertEqual(bot["personality"]["behavior_style"], "user behavior")
        self.assertEqual(bot["personality"]["multiple_reply_style"], ["user alternate"])
        self.assertEqual(bot["bot"]["alias_names"], ["user alias"])
        self.assertIn("User chosen fact", bot["personality"]["personality"])


if __name__ == "__main__":
    unittest.main()
