from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
import asyncio
import json
import tempfile
import unittest

from fatfish.fish_identity import FishIdentityMemory, FishIdentityObserver, FishReplyBudget, person_id
from test_topic_reply import TopicReplyPolicy, message, verdict


class FishIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.memory = FishIdentityMemory(self.root)

    def observe(self, result, text="我是大肥鱼，本鱼最喜欢聊天了", user="10001"):
        m = NS(platform="qq", processed_plain_text=text, message_info=NS(user_info=NS(user_id=user, user_nickname="同名")))
        async def vision(prompt, encoded):
            return json.dumps(result)
        asyncio.run(FishIdentityObserver(self.root, self.root, "group-a").observe(m,
            fetch_avatar=lambda *_: ("fake-image", "avatar-sha"), vision=vision))

    def result(self, **overrides):
        return dict(avatar_matches=True, persona_matches=True, confidence=.95,
                    persona_quote="我是大肥鱼", reason="头像和自称均匹配", **overrides)

    def test_both_evidence_persist_by_account(self):
        self.observe(self.result())
        self.assertEqual(self.memory.get("qq", "10001")["status"], "fish")
        self.assertIn("对方", self.memory.reference(person_id("qq", "10001")))
        self.assertEqual(self.memory.get("qq", "10002"), {})

    def test_one_evidence_or_low_confidence_or_forged_quote_never_confirms(self):
        for i, changed in enumerate(({"avatar_matches": False}, {"persona_matches": False},
                {"confidence": .84}, {"confidence": True}, {"persona_quote": "我叫大肥鱼"},
                {"persona_quote": "大肥鱼"})):
            with self.subTest(changed=changed):
                result = self.result(); result.update(changed)
                user = str(11000 + i); self.observe(result, user=user)
                self.assertNotEqual(self.memory.get("qq", user).get("status"), "fish")

    def test_addressing_bot_does_not_trigger_avatar_request(self):
        self.observe(self.result(), "大肥鱼你还记得吗")
        self.assertEqual(self.memory.rows(), {})

    def test_quoted_role_and_unrelated_blue_avatar_declined_by_vision(self):
        result = self.result(); result.update(persona_matches=False)
        self.observe(result, '别人说“我是大肥鱼”，这是引用')
        self.assertEqual(self.memory.get("qq", "10001")["status"], "unknown")

    def test_manual_human_wins_and_reset_can_identify_again(self):
        self.memory.correct("10001", "human")
        self.observe(self.result())
        self.assertEqual(self.memory.get("qq", "10001")["status"], "human")
        self.memory.correct("10001", "unknown")
        self.observe(self.result())
        self.assertEqual(self.memory.get("qq", "10001")["status"], "fish")

    def test_check_cooldown_and_service_failure_preserve_unknown(self):
        m = NS(platform="qq", processed_plain_text="我是大肥鱼", message_info=NS(user_info=NS(user_id="10001")))
        calls = []
        def fetch(*_):
            calls.append(1); raise OSError("offline")
        observer = FishIdentityObserver(self.root, self.root, "x")
        async def vision(*_): return "invalid"
        with self.assertRaises(OSError):
            asyncio.run(observer.observe(m, fetch_avatar=fetch, vision=vision))
        asyncio.run(observer.observe(m, fetch_avatar=fetch, vision=vision))
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.memory.get("qq", "10001")["status"], "unknown")

    def test_ambiguous_names_not_merged(self):
        self.observe(self.result(), user="10001"); self.observe(self.result(), user="10002")
        self.assertEqual(self.memory.resolve_reference(name="同名"), "")
        self.assertIn("10001", self.memory.resolve_reference(name="10001"))


class FishBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.memory = FishIdentityMemory(self.root)
        self.memory.correct("10001", "fish")
        self.budget = FishReplyBudget(self.root, "group-a")

    def test_three_deliveries_then_at_probability_one_restart_cannot_bypass(self):
        policy = TopicReplyPolicy(fish_budget=self.budget)
        for i in range(1, 4):
            self.assertTrue(policy.prepare_turn([message(str(i), author="10001", direct=True)], [], 1))
            policy.apply_decision(verdict(target=str(i), keep=False))
            policy.record_visible_reply("第一段\n第二段")
            policy.record_visible_reply("重试回调")
            policy.active_topic = None
        self.assertFalse(policy.prepare_turn([message("4", author="10001", direct=True)], [], 1))
        restarted = TopicReplyPolicy(fish_budget=FishReplyBudget(self.root, "group-a"))
        self.assertFalse(restarted.prepare_turn([message("5", author="10001", direct=True)], [], 1))
        self.assertTrue(FishReplyBudget(self.root, "group-b").allowed("qq", "10001"))

    def test_no_delivery_no_count_unknown_and_human_not_limited(self):
        policy = TopicReplyPolicy(fish_budget=self.budget)
        policy.prepare_turn([message("1", author="10001", direct=True)], [], 1)
        policy.apply_decision(verdict()); policy.finish_turn()
        self.assertEqual(self.budget.rows[person_id("qq", "10001")]["count"], 0)
        for user in ("10002", "10003"):
            for _ in range(8): self.budget.sent("qq", user)
            self.assertTrue(self.budget.allowed("qq", user))

    def test_newly_identified_fish_inherits_count_and_manual_correction_is_immediate(self):
        for _ in range(3): self.budget.sent("qq", "10002")
        self.memory.correct("10002", "fish")
        self.assertFalse(self.budget.allowed("qq", "10002"))
        self.memory.correct("10002", "human")
        self.assertTrue(self.budget.allowed("qq", "10002"))

    def test_continuous_messages_extend_quiet_period(self):
        with patch("fatfish.fish_identity.time.time", return_value=1000):
            self.budget.observe("qq", "10001")
            for _ in range(3): self.budget.sent("qq", "10001")
        for now in (1500, 2000, 2500):
            with patch("fatfish.fish_identity.time.time", return_value=now):
                self.budget.observe("qq", "10001")
                self.assertFalse(self.budget.allowed("qq", "10001"))
        with patch("fatfish.fish_identity.time.time", return_value=3100):
            self.budget.observe("qq", "10001")
            self.assertTrue(self.budget.allowed("qq", "10001"))

    def test_fish_claiming_new_topic_does_not_reset_but_nonfish_can(self):
        for _ in range(3): self.budget.sent("qq", "10001", human_new_topic=True)
        self.assertFalse(self.budget.allowed("qq", "10001"))
        self.budget.sent("qq", "10002", human_new_topic=True)
        self.assertTrue(self.budget.allowed("qq", "10001"))
