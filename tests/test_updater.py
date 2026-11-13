"""Isolated upgrade transactions, synthetic accounts and databases only."""
from pathlib import Path
import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import tomlkit

from fatfish.updater import ACTIVE, Upgrade, load, save, sha, stop_existing, value_sha
from scripts.install_or_upgrade import install


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


class UpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="qianyu-upgrade-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.source, self.home = self.base / "来源", self.base / "旧安装"
        self.factory_files = {"manifest.json": '{"enabled":true}', "persona.md": "factory voice"}
        signatures = {"identity_sha256": [hashlib.sha256(b"factory identity").hexdigest()],
                      "style_files": {k: hashlib.sha256(v.encode()).hexdigest() for k, v in self.factory_files.items()},
                      "default_nicknames": ["千羽"], "old_default_aliases": ["肥鱼"],
                      "factory_values": {"PersonalityConfig.behavior_style": [value_sha("factory behavior")],
                                         "PersonalityConfig.reply_style": [value_sha("factory reply")],
                                         "PersonalityConfig.multiple_reply_style": [value_sha(["factory alternate"])],
                                         "ChatReplyStyleConfig.group_chat_prompt": [value_sha("factory group")],
                                         "ChatReplyStyleConfig.private_chat_prompts": [value_sha("factory private")]}}
        put(self.source / "程序/fatfish/core.py", "new program")
        put(self.source / "程序/layout.json", '{"layout":"personal-home/program"}')
        put(self.source / "程序/启动千鱼.cmd", "program entry")
        put(self.source / "启动千鱼.cmd", "outer entry")
        save(self.source / "程序/templates/migrations/factory-default-digests.json", signatures)
        self.manifest()

    def manifest(self, version="0.3.13"):
        files = {p.relative_to(self.source).as_posix(): sha(p) for p in self.source.rglob("*") if p.is_file() and p.name != "release-manifest.json"}
        save(self.source / "release-manifest.json", {"personal_data": False, "version": version, "files": files})

    def old(self, *, flat=False, custom=False, native_custom=False):
        self.program = self.home if flat else self.home / "程序"
        put(self.program / "fatfish/core.py", "old program")
        self.instance = self.program / "instances/my-fish"
        put(self.instance / "persona/identity.md", "my identity" if custom else "factory identity")
        for name, value in self.factory_files.items():
            put(self.instance / "persona/style-pack" / name, value)
            put(self.program / "templates/style-packs/qianyu-tieba" / name, value)
        if custom:
            put(self.instance / "persona/style-pack/persona.md", "my chosen voice")
        save(self.instance / "fatfish.json", {"nickname": "MyFish" if custom else "千羽", "qq_account": "1234567", "qq_token": "synthetic-token"})
        put(self.instance / "config/model_config.toml", 'api_key = "synthetic-api-key"')
        identity = "my identity" if custom else "factory identity"
        suffix = '\n\n主人当前选择的性格与语气（本段优先于旧设定中冲突的语气要求，保留背景事实；当前昵称为“' + ("MyFish" if custom else "千羽") + '”）：\n' + ("my chosen voice" if custom else "factory voice")
        bot = {"bot": {"nickname": "MyFish" if custom else "千羽", "alias_names": ["my alias"] if custom else ["肥鱼"]},
               "personality": {"personality": ("advanced custom identity" if native_custom else identity + suffix),
                               "behavior_style": "my behavior" if custom else "factory behavior",
                               "reply_style": "my reply" if custom else "factory reply",
                               "multiple_reply_style": ["factory alternate"], "multiple_probability": 0.5,
                               "selected_profile": "custom-profile" if native_custom else ""},
               "chat": {"reply_style": {"group_chat_prompt": "factory group", "private_chat_prompts": "factory private"}}}
        put(self.instance / "config/bot_config.toml", tomlkit.dumps(bot))
        put(self.instance / "memory/manual.md", "")
        put(self.instance / "memory/notes/memory.md", "synthetic shared memory")
        put(self.instance / "knowledge/article.md", "synthetic knowledge")
        db = self.instance / "data/MaiBot.db"
        db.parent.mkdir()
        with sqlite3.connect(db) as connection:
            connection.execute("CREATE TABLE memories (content TEXT)")
            connection.execute("INSERT INTO memories VALUES ('synthetic long term memory')")
        connection.close()
        return self.program

    def transaction(self):
        return Upgrade(self.source, self.home, stop=lambda root: {"core_was_running": True})

    def assert_memory(self):
        self.assertEqual((self.instance / "knowledge/article.md").read_text(), "synthetic knowledge")
        connection = sqlite3.connect(self.instance / "data/MaiBot.db")
        try:
            self.assertEqual(connection.execute("SELECT content FROM memories").fetchone()[0], "synthetic long term memory")
        finally:
            connection.close()
        self.assertEqual(load(self.instance / "fatfish.json")["qq_token"], "synthetic-token")
        self.assertIn("synthetic-api-key", (self.instance / "config/model_config.toml").read_text())

    def test_factory_upgrade_neutralizes_preserves_sqlite_and_has_full_backup(self):
        self.old()
        tx = self.transaction().apply()
        tx.migrate_defaults()
        result = tx.commit()
        self.assert_memory()
        self.assertEqual((self.instance / "persona/identity.md").read_text(), "")
        bot = tomlkit.parse((self.instance / "config/bot_config.toml").read_text(encoding="utf-8"))
        self.assertEqual(bot["personality"]["personality"], "你是一个 AI 助手。")
        self.assertEqual(bot["personality"]["reply_style"], "")
        self.assertEqual(bot["personality"]["multiple_reply_style"], [])
        self.assertFalse(list((self.instance / "persona/style-pack").iterdir()))
        self.assertFalse(list((self.program / "templates/style-packs/qianyu-tieba").iterdir()))
        self.assertTrue((Path(result["backup"]) / "user-data/instances/my-fish/data/MaiBot.db").is_file())
        self.assertFalse((self.home / ACTIVE).exists())
        self.assertTrue(result["resume_core"])

    def test_custom_content_and_native_advanced_fields_are_retained(self):
        self.old(custom=True, native_custom=True)
        originals = {p: p.read_bytes() for p in (self.instance / "persona/style-pack").iterdir()}
        tx = self.transaction().apply()
        tx.migrate_defaults()
        tx.commit()
        self.assert_memory()
        for path, content in originals.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertEqual((self.instance / "persona/identity.md").read_text(), "my identity")
        bot = tomlkit.parse((self.instance / "config/bot_config.toml").read_text(encoding="utf-8"))
        self.assertEqual(bot["personality"]["behavior_style"], "my behavior")
        self.assertEqual(bot["personality"]["reply_style"], "my reply")
        self.assertEqual(bot["personality"]["selected_profile"], "custom-profile")
        self.assertTrue(load(self.instance / "persona/default-profile.json")["preserve_native_personality"])

    def test_factory_style_with_custom_native_identity_is_not_discarded(self):
        self.old(native_custom=True)
        tx = self.transaction().apply()
        tx.migrate_defaults()
        tx.commit()
        bot = tomlkit.parse((self.instance / "config/bot_config.toml").read_text(encoding="utf-8"))
        self.assertEqual(bot["personality"]["personality"], "advanced custom identity")
        self.assertTrue(load(self.instance / "persona/default-profile.json")["preserve_native_personality"])

    def test_flat_install_keeps_existing_data_path_and_correct_entry(self):
        self.old(flat=True)
        tx = self.transaction().apply()
        tx.migrate_defaults()
        result = tx.commit()
        self.assert_memory()
        self.assertEqual(result["program_root"], str(self.home))
        self.assertEqual(load(self.home / "layout.json")["layout"], "flat-install")
        self.assertEqual((self.home / "启动千鱼.cmd").read_text(), "program entry")
        self.assertFalse((self.home / "程序/instances").exists())

    def test_failure_restores_program_config_dependencies_and_allows_retry(self):
        self.old()
        put(self.program / ".runtime/site-packages/old", "old dependency")
        original_bot = (self.instance / "config/bot_config.toml").read_bytes()
        tx = self.transaction().apply()
        previous = tx.backup / "dependencies/site-packages"
        previous.parent.mkdir()
        (self.program / ".runtime/site-packages").rename(previous)
        put(self.program / ".runtime/site-packages/new", "new dependency")
        save(tx.backup / "dependency-state.json", {"previous_packages": "dependencies/site-packages"})
        tx.migrate_defaults()
        tx.rollback()
        self.assertEqual((self.program / "fatfish/core.py").read_text(), "old program")
        self.assertEqual((self.instance / "config/bot_config.toml").read_bytes(), original_bot)
        self.assertEqual((self.program / ".runtime/site-packages/old").read_text(), "old dependency")
        self.assert_memory()
        retry = self.transaction().apply()
        retry.migrate_defaults()
        retry.commit()

    def test_abandoned_transaction_recovers_before_next_upgrade(self):
        self.old()
        interrupted = self.transaction().apply()
        interrupted.migrate_defaults()
        following = self.transaction().apply()
        self.assertEqual(load(interrupted.backup / "transaction.json")["phase"], "rolled_back")
        following.migrate_defaults()
        following.commit()
        self.assert_memory()

    def test_live_transaction_is_not_rolled_back(self):
        self.old()
        first = Upgrade(self.source, self.home, owner_pid=os.getpid(), stop=lambda root: {})
        first.apply()
        with self.assertRaises(RuntimeError):
            self.transaction().apply()
        self.assertTrue((self.home / ACTIVE).exists())
        first.rollback()

    def test_manifest_damage_path_escape_private_source_and_downgrade_rejected(self):
        self.old()
        put(self.source / "程序/fatfish/core.py", "tampered")
        with self.assertRaises(ValueError):
            self.transaction().apply()
        self.manifest()
        manifest = load(self.source / "release-manifest.json")
        for path in ("../escape", "程序/instances/secret", "程序/INSTANCES/secret"):
            altered = dict(manifest, files={path: "irrelevant"})
            save(self.source / "release-manifest.json", altered)
            with self.assertRaises(ValueError):
                self.transaction().apply()
        self.manifest("0.3.12")
        save(self.home / "release-manifest.json", {"version": "0.3.13"})
        with self.assertRaises(ValueError):
            self.transaction().apply()
        self.assertEqual((self.program / "fatfish/core.py").read_text(), "old program")

    def test_wrong_loopback_instance_and_remote_url_never_receive_quit(self):
        self.old()
        save(self.program / ".runtime/launcher.json", {"url": "http://other.invalid:12345/#token=synthetic", "port": 12345})
        with patch("fatfish.updater.urlopen") as request, self.assertRaises(ValueError):
            stop_existing(self.program)
        request.assert_not_called()
        save(self.program / ".runtime/launcher.json", {"url": "http://127.0.0.1:12345/#token=synthetic", "port": 12345})
        import io
        with patch("fatfish.updater.urlopen", return_value=io.BytesIO(json.dumps({"instance": str(self.base / "another/instances/my-fish")}).encode())) as request:
            with self.assertRaises(RuntimeError):
                stop_existing(self.program)
            self.assertEqual(request.call_count, 1)

    def test_driver_dependency_failure_rolls_back_without_losing_data(self):
        self.old()
        def fail(*args, **kwargs):
            raise RuntimeError("synthetic installation failure")
        with self.assertRaisesRegex(RuntimeError, "synthetic installation failure"):
            install(self.source, self.home, prepare_dependencies=fail)
        self.assertEqual((self.program / "fatfish/core.py").read_text(), "old program")
        self.assert_memory()

    def test_running_old_install_receives_authenticated_graceful_quit(self):
        self.old()
        save(self.program / ".runtime/launcher.json", {"url": "http://127.0.0.1:12345/#token=synthetic", "port": 12345, "pid": 987654})
        import io
        responses = [io.BytesIO(json.dumps({"instance": str(self.instance), "running": True}).encode()), io.BytesIO(b"{}")]
        with patch("fatfish.updater.urlopen", side_effect=responses) as request, patch("fatfish.updater.alive", return_value=False):
            result = stop_existing(self.program)
        self.assertTrue(result["core_was_running"])
        self.assertEqual(request.call_args_list[1].args[0].full_url, "http://127.0.0.1:12345/api/quit")
        self.assertEqual(request.call_args_list[1].args[0].get_header("X-fatfish-token"), "synthetic")

    def test_unreachable_live_old_install_is_not_overwritten(self):
        self.old()
        save(self.program / ".runtime/launcher.json", {"url": "http://127.0.0.1:12345/#token=synthetic", "port": 12345, "pid": 987654})
        with patch("fatfish.updater.urlopen", side_effect=OSError("unreachable")), patch("fatfish.updater.alive", return_value=True):
            with self.assertRaises(RuntimeError):
                stop_existing(self.program)
        self.assertEqual((self.program / "fatfish/core.py").read_text(), "old program")

    def test_fresh_failed_install_can_retry_in_same_directory(self):
        tx = self.transaction().apply()
        tx.rollback()
        retry = self.transaction().apply()
        retry.migrate_defaults()
        retry.commit()
        self.assertTrue((self.home / "程序/fatfish/core.py").exists())

    def test_commit_record_failure_still_allows_rollback(self):
        self.old()
        tx = self.transaction().apply()
        tx.migrate_defaults()
        with patch.object(tx, "journal", side_effect=OSError("synthetic journal failure")):
            with self.assertRaises(OSError):
                tx.commit()
        tx.rollback()
        self.assertEqual((self.program / "fatfish/core.py").read_text(), "old program")
        self.assert_memory()


if __name__ == "__main__":
    unittest.main()
