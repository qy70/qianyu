"""场景语气随实例风格包选择，旧包保持兼容。"""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "style_scenes_under_test", ROOT / "components" / "qianyu-style" / "style_library.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SceneStyleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="style-scenes-")
        self.base = Path(self.temp.name).resolve()
        self.addCleanup(self.temp.cleanup)

    def library(self, name, scene_rules=None):
        folder = self.base / name
        self.assertTrue(folder.resolve().is_relative_to(self.base))
        folder.mkdir()
        manifest = {"enabled": True, "max_examples": 1, "scene_rules": scene_rules}
        (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (folder / "natural-chat.md").write_text("按当前声线自然回应。", encoding="utf-8")
        (folder / "dialogue-distill.md").write_text("示例不是真实经历。", encoding="utf-8")
        (folder / "examples.jsonl").write_text("", encoding="utf-8")
        return MODULE.StyleLibrary(folder)

    def test_selected_pack_overrides_only_its_own_scene(self):
        custom = self.library("custom", {"comfort": "用当前角色的声线回应眼前的事。"})
        legacy = self.library("legacy")
        prompt, _ = custom.build("我很难过")
        self.assertIn("本轮场景：用当前角色的声线回应眼前的事。", prompt)
        self.assertNotIn("这次收起嘲讽、脏话和地狱梗", prompt)
        prompt, _ = legacy.build("我很难过")
        self.assertIn("根据对方表达的处境与需要回应", prompt)
        prompt, _ = custom.build("报错怎么修")
        self.assertIn("先回应实际问题", prompt)

    def test_empty_or_malformed_override_keeps_default(self):
        for i, rules in enumerate(([], "text", {"comfort": True}, {"comfort": "  "})):
            with self.subTest(rules=rules):
                prompt, _ = self.library(str(i), rules).build("我很难过")
                self.assertIn("根据对方表达的处境与需要回应", prompt)


if __name__ == "__main__":
    unittest.main()
