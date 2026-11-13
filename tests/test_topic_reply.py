"""呼叫、话题结束点和百分比准入；不调用远程模型或 QQ。"""
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import importlib.util
import json
import sys
import tempfile
import unittest

_path = Path(__file__).resolve().parents[1] / "engine/MaiBot/src/maisaka/turn_trigger/topic_policy.py"
_spec = importlib.util.spec_from_file_location("topic_policy_tested", _path)
_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _module
_spec.loader.exec_module(_module)
TopicReplyPolicy, ActiveTopic = _module.TopicReplyPolicy, _module.ActiveTopic
EPOCH = 1800000000.0


def message(identifier, author="a", received=100.0, direct=False):
    return SimpleNamespace(message_id=identifier, message_info=SimpleNamespace(user_info=SimpleNamespace(user_id=author)),
                           received_at=datetime.fromtimestamp(EPOCH + received), is_at=direct, is_mentioned=False,
                           processed_plain_text="当前发言", reply_to=None, is_notify=False, is_command=False)


def verdict(action="reply", relation="direct", target="1", keep=True):
    return json.dumps({"action": action, "relation": relation, "target_message_id": target, "keep_open": keep,
                       "topic_summary": "讨论手机设置", "reply_direction": "回答当前问题，不反问"}, ensure_ascii=False)


class TopicReplyTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch.object(_module.time, "time", return_value=EPOCH + 100)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def test_only_explicit_instance_enables_policy_and_legacy_multiplier_is_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertFalse(TopicReplyPolicy.load(root).enabled)
            (root / "social").mkdir()
            (root / "social/topic-reply.json").write_text(json.dumps({
                "enabled": True, "keywords": ["千羽", "大肥鱼"], "unrelated_probability": 0.01,
                "unrelated_cooldown_seconds": 999,
            }), encoding="utf-8")
            policy = TopicReplyPolicy.load(root)
            self.assertTrue(policy.called_by_keyword("大肥鱼你怎么看"))
            self.assertFalse(policy.called_by_keyword("今天吃鱼"))
            with patch.object(_module.random, "random", return_value=0.24):
                self.assertTrue(policy.prepare_turn([message("1")], [], 0.25))

    def test_zero_disables_only_new_topics_but_still_admits_calls(self):
        policy = TopicReplyPolicy()
        self.assertFalse(policy.prepare_turn([message("1")], [], 0))
        self.assertTrue(policy.prepare_turn([message("2", direct=True)], [], 0))
        policy.apply_decision(verdict(target="2"))
        self.assertIsNone(policy.active_topic)
        policy.record_visible_reply()
        self.assertIsNotNone(policy.active_topic)

    def test_probability_is_exact_slider_percentage(self):
        policy = TopicReplyPolicy()
        for index, (chance, draw, expected) in enumerate(((0.25, 0.249, True), (0.25, 0.25, False), (0.5, 0.49, True), (0.5, 0.51, False))):
            with self.subTest(chance=chance, draw=draw), patch.object(_module.random, "random", return_value=draw):
                self.assertEqual(policy.prepare_turn([message(str(index))], [], chance), expected)
        with patch.object(_module.random, "random") as draw:
            self.assertTrue(policy.prepare_turn([message("new")], [], 1))
            draw.assert_not_called()

    def test_open_topic_continues_at_zero_without_sampling_new_topics(self):
        policy = TopicReplyPolicy(active_topic=ActiveTopic("手机设置", {"a"}, EPOCH + 90))
        with patch.object(_module.random, "random") as draw:
            self.assertTrue(policy.prepare_turn([message("2")], [], 0))
            draw.assert_not_called()
        policy.apply_decision(verdict(relation="continuation", target="2"))
        policy.record_visible_reply()
        self.assertIsNotNone(policy.active_topic)
        self.assertFalse(policy.allow_new_topic)

    def test_related_message_can_be_skipped_even_at_one(self):
        topic = ActiveTopic("手机设置", {"a"}, EPOCH + 90)
        policy = TopicReplyPolicy(active_topic=topic)
        self.assertTrue(policy.prepare_turn([message("1")], [], 1))
        decision = policy.apply_decision(verdict("skip", "unrelated"))
        self.assertEqual(decision.action, "skip")
        self.assertIs(policy.active_topic, topic)
        self.assertIsNone(policy.pending_decision)
        with self.assertRaises(ValueError):
            policy.planner_prompt("zh-CN")

    def test_end_silently_closes_and_history_cannot_resurrect_topic(self):
        policy = TopicReplyPolicy(active_topic=ActiveTopic("手机设置", {"a"}, EPOCH + 90))
        policy.prepare_turn([message("1")], [], 0)
        policy.apply_decision(verdict("end", "continuation", keep=False))
        self.assertIsNone(policy.active_topic)
        old = SimpleNamespace(source="guided_reply", processed_plain_text="刚才讨论过手机", timestamp=datetime.fromtimestamp(EPOCH + 95))
        self.assertFalse(policy.prepare_turn([message("2")], [old], 0))
        with self.assertRaises(ValueError):
            policy.apply_decision(verdict(relation="continuation", target="2"))

    def test_complete_answer_still_opens_three_followup_messages(self):
        topic = ActiveTopic("手机设置", {"a"}, EPOCH + 90)
        policy = TopicReplyPolicy(active_topic=topic)
        policy.prepare_turn([message("1")], [], 0)
        policy.apply_decision(verdict(relation="continuation", keep=False))
        self.assertIs(policy.active_topic, topic)
        policy.record_visible_reply("这一步已经设置好了")
        self.assertIsNotNone(policy.active_topic)
        self.assertEqual(policy.active_topic.remaining_messages, 3)
        self.assertTrue(policy.active_topic.last_answer_complete)
        self.assertEqual(policy.active_topic.last_bot_text, "这一步已经设置好了")
        self.assertTrue(policy.visible_reply_sent)

    def test_complete_direct_answer_does_not_block_metaphorical_followup(self):
        policy = TopicReplyPolicy()
        question = message("food", direct=True)
        question.processed_plain_text = "你晚饭吃什么"
        policy.prepare_turn([question], [], 0)
        policy.apply_decision(verdict(target="food", keep=False))
        policy.record_visible_reply("我靠算力，不用吃米饭")
        followup = message("usage")
        followup.processed_plain_text = "那一顿得花几个token"
        self.assertTrue(policy.prepare_turn([followup], [], 0))
        context = policy._context
        self.assertFalse(context["allow_new_topic"])
        self.assertFalse(context["direct_message_ids"])
        self.assertEqual(context["active_topic"]["last_exchange"], {
            "user_id": "a", "user": "你晚饭吃什么", "bot": "我靠算力，不用吃米饭",
        })
        self.assertTrue(context["active_topic"]["last_answer_complete"])
        policy.apply_decision(verdict(relation="continuation", target="usage", keep=False))
        policy.record_visible_reply("这顿按实际用量算")
        self.assertEqual(policy.active_topic.remaining_messages, 3)
        self.assertEqual(policy.active_topic.window_anchor_message_id, "usage")

    def test_complete_answer_keeps_elliptical_followup_context(self):
        policy = TopicReplyPolicy()
        first = message("math", direct=True)
        first.processed_plain_text = "两加两是多少"
        policy.prepare_turn([first], [], 0)
        policy.apply_decision(verdict(target="math", keep=False))
        policy.record_visible_reply("四")
        second = message("more")
        second.processed_plain_text = "再算一个呢"
        self.assertTrue(policy.prepare_turn([second], [], 0))
        self.assertEqual(policy._context["active_topic"]["last_exchange"]["bot"], "四")
        self.assertEqual(policy.active_topic.remaining_messages, 2)

    def test_skip_complete_flag_does_not_cancel_followup_window(self):
        policy = TopicReplyPolicy(active_topic=ActiveTopic("手机设置", {"a"}, EPOCH + 90))
        policy.prepare_turn([message("1")], [], 0)
        policy.apply_decision(verdict("skip", "unrelated", keep=False))
        self.assertIsNotNone(policy.active_topic)
        self.assertEqual(policy.active_topic.remaining_messages, 2)
        self.assertTrue(policy.prepare_turn([message("2")], [], 0))
        policy.apply_decision(verdict(relation="continuation", target="2", keep=False))
        policy.record_visible_reply("当前答案已完整")
        self.assertEqual(policy.active_topic.remaining_messages, 3)

    def test_random_open_becomes_followup_then_can_end(self):
        policy = TopicReplyPolicy()
        policy.prepare_turn([message("1")], [], 1)
        policy.apply_decision(verdict(relation="new"))
        policy.record_visible_reply()
        policy.prepare_turn([message("2")], [], 0)
        policy.apply_decision(verdict(relation="continuation", target="2"))
        policy.record_visible_reply()
        policy.prepare_turn([message("3")], [], 0)
        policy.apply_decision(verdict("end", "continuation", target="3", keep=False))
        self.assertIsNone(policy.active_topic)

    def test_hallucinated_gate_or_old_target_is_rejected(self):
        policy = TopicReplyPolicy()
        policy.prepare_turn([message("1")], [], 0)
        for payload in (verdict(relation="new"), verdict(relation="continuation"), verdict(target="old"), verdict(relation="unrelated")):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                policy.apply_decision(payload)
        with self.assertRaises((ValueError, TypeError)):
            policy.apply_decision('{"action":"reply"}')
        self.assertIsNone(policy.active_topic)

    def test_idle_expires_without_reopening_from_history(self):
        policy = TopicReplyPolicy(active_topic=ActiveTopic("旧话题", {"a"}, EPOCH - 100))
        self.assertFalse(policy.prepare_turn([message("1")], [], 0))
        self.assertIsNone(policy.active_topic)

    def test_busy_burst_is_not_replied_to_one_by_one_but_calls_are_kept(self):
        policy = TopicReplyPolicy()
        cache = [message("1"), message("2", author="b"), message("3", direct=True), message("4", direct=True)]
        self.assertEqual(policy.collect_end(cache, 0), 1)
        self.assertEqual(policy.collect_end(cache, 3), 4)
        self.assertEqual(policy.collect_end(cache[:2], 0), 1)

    def test_three_misses_stop_old_topic_before_fourth_message(self):
        policy = TopicReplyPolicy(active_topic=ActiveTopic("手机设置", {"a"}, EPOCH + 90))
        for index in range(1, 4):
            self.assertTrue(policy.prepare_turn([message(str(index))], [], 0))
            policy.apply_decision(verdict("skip", "unrelated", target=str(index)))
        self.assertIsNone(policy.active_topic)
        self.assertFalse(policy.prepare_turn([message("4")], [], 0))

    def test_first_second_or_third_hit_replaces_window_without_adding_leftovers(self):
        for hit in (1, 2, 3):
            with self.subTest(hit=hit):
                policy = TopicReplyPolicy(active_topic=ActiveTopic("手机设置", {"a"}, EPOCH + 90))
                for index in range(1, hit):
                    policy.prepare_turn([message(str(index))], [], 0)
                    policy.apply_decision(verdict("skip", "unrelated", target=str(index)))
                trigger = str(hit)
                self.assertTrue(policy.prepare_turn([message(trigger)], [], 0))
                policy.apply_decision(verdict(relation="continuation", target=trigger))
                self.assertEqual(policy.active_topic.remaining_messages, 3)
                self.assertEqual(policy.active_topic.window_anchor_message_id, trigger)
                policy.record_visible_reply()
                for offset in (1, 2, 3):
                    identifier = str(hit + offset)
                    self.assertTrue(policy.prepare_turn([message(identifier)], [], 0))
                    policy.apply_decision(verdict("skip", "unrelated", target=identifier))
                self.assertIsNone(policy.active_topic)
                self.assertFalse(policy.prepare_turn([message(str(hit + 4))], [], 0))

    def test_already_queued_b_c_d_are_new_window_after_a_hits(self):
        policy = TopicReplyPolicy(active_topic=ActiveTopic("手机设置", {"a"}, EPOCH + 90))
        cache = [message(identifier) for identifier in ("A", "B", "C", "D", "E")]
        start = 0
        judged = []
        while start < len(cache):
            end = policy.collect_end(cache, start)
            batch = cache[start:end]
            if policy.prepare_turn(batch, [], 0):
                identifier = batch[-1].message_id
                judged.append(identifier)
                self.assertEqual(len(policy._context["new_messages"]), 1)
                if identifier == "A":
                    policy.apply_decision(verdict(relation="continuation", target="A"))
                    policy.record_visible_reply()
                else:
                    policy.apply_decision(verdict("skip", "unrelated", target=identifier))
            policy.finish_turn()
            start = end
        self.assertEqual(judged, ["A", "B", "C", "D"])

    def test_retry_command_notice_and_self_echo_do_not_spend_window(self):
        policy = TopicReplyPolicy(active_topic=ActiveTopic("手机设置", {"a"}, EPOCH + 90))
        notice, command, echo = message("notice"), message("command"), message("echo", author="bot")
        notice.is_notify = True
        command.is_command = True
        self.assertFalse(policy.prepare_turn([notice, command], [], 0))
        self.assertEqual(policy.active_topic.remaining_messages, 3)
        cache = [notice, command, echo, message("A"), message("B")]
        end = policy.collect_end(cache, 0, lambda m: policy.is_countable(m) and m.message_info.user_info.user_id != "bot")
        self.assertEqual(end, 4)
        policy.prepare_turn([message("A")], [], 0)
        policy.apply_decision(verdict("skip", "unrelated", target="A"))
        self.assertEqual(policy.active_topic.remaining_messages, 2)
        self.assertFalse(policy.prepare_turn([message("A")], [], 0))
        self.assertEqual(policy.active_topic.remaining_messages, 2)

    def test_duplicate_delivery_callback_does_not_reset_window_again(self):
        policy = TopicReplyPolicy()
        policy.prepare_turn([message("A", direct=True)], [], 0)
        policy.apply_decision(verdict(target="A"))
        policy.record_visible_reply()
        policy.active_topic.remaining_messages = 2
        policy.record_visible_reply()
        self.assertEqual(policy.active_topic.remaining_messages, 2)

    def test_decision_errors_spend_at_most_three_followup_attempts(self):
        policy = TopicReplyPolicy(active_topic=ActiveTopic("手机设置", {"a"}, EPOCH + 90))
        for index in range(3):
            self.assertTrue(policy.prepare_turn([message(str(index))], [], 0))
            with self.assertRaises(ValueError):
                policy.apply_decision("invalid-json")
            policy.finish_turn()
        self.assertFalse(policy.prepare_turn([message("after")], [], 0))

    def test_direct_call_and_speaker_change_do_not_wait(self):
        policy = TopicReplyPolicy()
        self.assertAlmostEqual(policy.quiet_remaining([message("1")]), 0.8, places=5)
        self.assertEqual(policy.quiet_remaining([message("1", direct=True)]), 0)
        self.assertEqual(policy.quiet_remaining([message("1"), message("2", author="b")]), 0)


if __name__ == "__main__":
    unittest.main()
