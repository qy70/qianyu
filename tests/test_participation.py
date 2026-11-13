"""频率设置的边界、旧值迁移及运行时保存；不连接真实 QQ 或模型。"""
from pathlib import Path
from unittest.mock import patch

import json
import tempfile
import unittest
import tomlkit

from fatfish.core import FishManager, ROOT


class ParticipationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = FishManager(instance_name="participation-fixture")
        cls.fixture.initialize()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="qianyu-frequency-")
        self.addCleanup(self.temp.cleanup)
        self.manager = FishManager(root=Path(self.temp.name))
        import shutil
        for relative in ("config/bot_config.toml", "config/model_config.toml", "persona/identity.md", "memory/manual.md", "fatfish.json"):
            target = self.manager.instance / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.fixture.instance / relative, target)

    def test_invalid_values_leave_files_unchanged(self):
        originals = {p: p.read_bytes() for p in self.manager.instance.rglob("*") if p.is_file()}
        for value in (-0.1, 1.1, float("nan"), float("inf"), True, "0.5", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.manager.save_group_reply_frequency({"group_reply_frequency": value})
        for p, original in originals.items():
            self.assertEqual(p.read_bytes(), original)

    def test_runtime_save_changes_only_frequency_and_keeps_private_config(self):
        bot_path = self.manager.instance / "config/bot_config.toml"
        original = tomlkit.parse(bot_path.read_text(encoding="utf-8")).unwrap()
        original_settings = json.loads((self.manager.instance / "fatfish.json").read_text(encoding="utf-8"))
        model_bytes = (self.manager.instance / "config/model_config.toml").read_bytes()
        with patch.object(self.manager, "running", return_value=True):
            for value in (0, 0.35, 1, 0.5):
                result = self.manager.save_group_reply_frequency({"group_reply_frequency": value})
                self.assertEqual(result["group_reply_frequency"], value)
                self.assertNotIn("qq_token", result)
                after = tomlkit.parse(bot_path.read_text(encoding="utf-8")).unwrap()
                expected = json.loads(json.dumps(original))
                expected["chat"]["reply_timing"].update(talk_value=value, reply_each_message=False, enable_talk_value_rules=False)
                self.assertEqual(after, expected)
                stored = json.loads((self.manager.instance / "fatfish.json").read_text(encoding="utf-8"))
                self.assertEqual(stored, {**original_settings, "group_reply_frequency": value})
                self.assertEqual((self.manager.instance / "config/model_config.toml").read_bytes(), model_bytes)

    def test_old_full_day_rule_is_migrated_and_restart_keeps_slider(self):
        path = self.manager.instance / "fatfish.json"
        stored = json.loads(path.read_text(encoding="utf-8"))
        stored.pop("group_reply_frequency", None)
        path.write_text(json.dumps(stored), encoding="utf-8")
        bot_path = self.manager.instance / "config/bot_config.toml"
        doc = tomlkit.parse(bot_path.read_text(encoding="utf-8"))
        doc["chat"]["reply_timing"].update(talk_value=0.25, enable_talk_value_rules=True, talk_value_rules=[{"platform":"", "item_id":"", "rule_type":"group", "time":"*", "value":0.5}])
        bot_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
        self.assertEqual(self.manager.settings()["group_reply_frequency"], 0.5)
        self.manager.save_group_reply_frequency({"group_reply_frequency": 0.75})
        # 普通保存和启动使用相同的 apply_config，不能把滑块恢复为旧参与档位。
        self.manager.apply_config(self.manager.settings(private=True))
        timing = tomlkit.parse(bot_path.read_text(encoding="utf-8"))["chat"]["reply_timing"]
        self.assertEqual(timing["talk_value"], 0.75)
        self.assertFalse(timing["enable_talk_value_rules"])
        self.assertFalse(timing["reply_each_message"])


if __name__ == "__main__":
    unittest.main()
