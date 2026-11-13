from pathlib import Path
from contextlib import closing
import json
import sqlite3
import tempfile
import unittest

from fatfish.shared_memory import recent_reference


class SharedMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "data").mkdir()
        (self.root / "fatfish.json").write_text(json.dumps({"memory_enabled": True}))
        with closing(sqlite3.connect(self.root / "data/MaiBot.db")) as db:
            db.execute('''CREATE TABLE mai_messages (session_id TEXT, timestamp TEXT, platform TEXT,
                account_id TEXT, user_id TEXT, group_id TEXT, group_name TEXT, user_nickname TEXT,
                processed_plain_text TEXT, message_id TEXT, is_command BOOL, is_notify BOOL)''')
            for session, uid, group, text, account, minute in (
                    ("g", "10001", "90001", "group-memory-evidence", "", 1),
                    ("g", "99999", "90001", "fish-reply-evidence", "", 2),
                    ("p", "10001", "", "private-memory-evidence", "", 3),
                    ("p-other", "10002", "", "other-private-secret", "", 4),
                    ("g-other-account", "10001", "90001", "other-bot-secret", "other", 5)):
                db.execute('INSERT INTO mai_messages VALUES (?,?,?,?,?,?,?,?,?,?,0,0)',
                    (session,f"2026-11-05 12:0{minute}:00", "qq", account, uid, group, "群", "same-name", text, str(minute)))
            db.commit()

    def reference(self, session):
        return recent_reference(self.root,platform="qq",user_id="10001",session_id=session,bot_id="99999")

    def test_group_to_private_includes_actual_reply_before_summary(self):
        reference = self.reference("p")
        self.assertIn("group-memory-evidence", reference)
        self.assertIn("fish-reply-evidence", reference)
        self.assertNotIn("private-memory-evidence", reference)
        self.assertNotIn("other-private-secret", reference)
        self.assertNotIn("other-bot-secret", reference)

    def test_private_to_group_same_account_only_and_survives_reopen(self):
        reference = self.reference("g")
        self.assertIn("private-memory-evidence", reference)
        self.assertNotIn("other-private-secret", reference)
        self.assertIn("private-memory-evidence", self.reference("g"))

    def test_optout_and_automatic_memory_off_stop_shared_reads(self):
        for settings in ({"memory_enabled": False}, {"memory_enabled": True,"shared_memory_enabled": False}):
            (self.root / "fatfish.json").write_text(json.dumps(settings))
            self.assertEqual(self.reference("g"), "")
