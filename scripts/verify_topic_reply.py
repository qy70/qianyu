"""独立实例 + 原生核心 + 模拟模型/QQ；只验证调度与提示传递，不声称真实语义质量。"""
from unittest.mock import patch

import asyncio
import json
import re
import time
import traceback
import tomlkit

from aiohttp import web

from fatfish.core import ROOT, FishManager, atomic_text

BOT, USER, GROUP = 100000021, 100000022, 123456789


async def main():
    manager = FishManager(instance_name="topic-reply-fixture")
    await asyncio.to_thread(manager.initialize)
    await asyncio.to_thread(manager.save, {
        "api_base": "http://127.0.0.1:19491/v1", "api_key": "topic-fixture-only", "model": "local-test-model",
        "qq_account": str(BOT), "groups": [str(GROUP)], "group_scope": "selected", "private_scope": "off",
        "qq_port": 19492, "group_reply_frequency": 0.8, "memory_enabled": False, "collect_emoji": False,
    })
    atomic_text(manager.instance / "social/topic-reply.json", json.dumps({
        "enabled": True, "keywords": ["测试鱼", "大肥鱼"], "unrelated_probability": 0,
    }, ensure_ascii=False))
    original_apply = manager.apply_config

    def isolated_apply(data):
        original_apply(data)
        path = manager.instance / "config/bot_config.toml"
        doc = tomlkit.parse(path.read_text(encoding="utf-8"))
        doc["http"]["port"] = 18052
        atomic_text(path, tomlkit.dumps(doc))

    manager.apply_config = isolated_apply
    connections, outbound, decisions, requests = set(), [], [], []
    base = int(time.time()) * 100
    expected = {}
    slow_generation = asyncio.Event()
    release_generation = asyncio.Event()
    report = {"real_qq_test_messages": 0, "paid_model_test_requests": 0}

    async def model(request):
        body = await request.json()
        requests.append(body)
        if len(requests) > 60:
            return web.json_response({"error": {"message": "fixture request limit"}}, status=429)
        system = "\n".join(str(item.get("content", "")) for item in body.get("messages", []) if item.get("role") == "system")
        calls = None
        if "CURRENT_MESSAGE_IDS" in system:
            match = re.search(r'\{"CURRENT_MESSAGE_IDS":.*', system)
            assert match, system[-1000:]
            controls = json.loads(match.group(0))
            identifiers = controls["CURRENT_MESSAGE_IDS"]
            indices = [int(identifier) - base for identifier in identifiers]
            assert all(index in expected for index in indices), indices
            names = [tool["function"]["name"] for tool in body.get("tools", [])]
            assert "reply" in names and "wait" not in names, names
            decisions.append({"indices": indices, "controls": controls, "tools": names, "time": time.monotonic()})
            reply = any(expected[index] for index in indices)
            name = "reply" if reply else "stop"
            arguments = {"msg_id": identifiers[-1], "reply_reference": "围绕当前新消息自然回应"} if reply else {}
            calls = [{"id": "fixture-" + str(len(requests)), "type": "function",
                      "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}]
            if 8 in indices:
                calls.append({"id": "duplicate-" + str(len(requests)), "type": "function",
                              "function": {"name": "reply", "arguments": json.dumps(arguments, ensure_ascii=False)}})
            message = {"role": "assistant", "content": None, "tool_calls": calls}
        else:
            # 第一次 Replyer 请求期间继续发消息，验证后到者独立处理且不改变当前目标。
            if not slow_generation.is_set():
                slow_generation.set()
                await asyncio.wait_for(release_generation.wait(), 20)
            message = {"role": "assistant", "content": "这一条收到啦"}
        return web.json_response({"id": "topic-local", "object": "chat.completion", "created": int(time.time()),
            "model": "local-test-model", "choices": [{"index": 0, "message": message,
            "finish_reason": "tool_calls" if calls else "stop"}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 5, "total_tokens": 55}})

    async def qq(request):
        if request.headers.get("Authorization") != "Bearer " + manager.settings(private=True)["qq_token"]:
            return web.Response(status=401)
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        connections.add(ws)
        try:
            async for incoming in ws:
                if incoming.type != web.WSMsgType.TEXT:
                    continue
                body = json.loads(incoming.data)
                action, params = body.get("action"), body.get("params", {})
                result = {}
                if action == "get_version_info":
                    result = {"app_name": "NapCat", "app_version": "fixture", "protocol_version": "v11"}
                elif action == "get_login_info":
                    result = {"user_id": BOT, "nickname": "测试鱼"}
                elif action == "get_status":
                    result = {"online": True, "good": True}
                elif action in {"get_group_info", "get_group_list"}:
                    result = {"group_id": GROUP, "group_name": "隔离话题测试群", "member_count": 4, "max_member_count": 200}
                    if action == "get_group_list":
                        result = [result]
                elif action in {"get_group_member_info", "get_stranger_info"}:
                    result = {"group_id": GROUP, "user_id": params.get("user_id", USER), "nickname": "模拟群友",
                              "card": "", "role": "member", "sex": "unknown", "age": 0}
                elif action in {"get_friend_list", "get_group_member_list"}:
                    result = []
                elif action in {"send_group_msg", "send_msg"}:
                    outbound.append(params)
                    result = {"message_id": 920000 + len(outbound)}
                await ws.send_json({"status": "ok", "retcode": 0, "data": result, "echo": body.get("echo")})
        finally:
            connections.discard(ws)
        return ws

    app = web.Application()
    app.router.add_post("/v1/chat/completions", model)
    app.router.add_get("/", qq)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 19491).start()
    await web.TCPSite(runner, "127.0.0.1", 19492).start()

    async def wait_until(predicate, seconds=20):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if predicate():
                return
            if not manager.running():
                raise RuntimeError("隔离核心退出")
            await asyncio.sleep(0.1)
        raise TimeoutError("话题隔离验收超时")

    async def send(index, text, *, reply=False, user=USER):
        expected[index] = reply
        event = {"time": int(time.time()), "self_id": BOT, "post_type": "message", "message_type": "group",
                 "sub_type": "normal", "message_id": base + index, "group_id": GROUP, "user_id": user,
                 "message": [{"type": "text", "data": {"text": text}}], "raw_message": text, "font": 0,
                 "sender": {"user_id": user, "nickname": "模拟群友", "card": "", "role": "member"}}
        for ws in list(connections):
            await ws.send_json(event)

    try:
        with patch("fatfish.core.tcp_open", return_value=False):
            await asyncio.to_thread(manager.start)
        await wait_until(lambda: manager.boot_ready and connections, 70)
        for index in (1, 2):
            sent_at = time.monotonic()
            await send(index, "别人在聊自己的晚饭")
            await wait_until(lambda: any(index in item["indices"] for item in decisions))
            assert time.monotonic() - sent_at < 5
            await asyncio.sleep(0.3)
        assert len(outbound) == 0
        report["unrelated_messages_decided_individually_without_backlog_or_backoff"] = True

        await send(3, "大肥鱼你觉得先关掉再开有用吗", reply=True)
        await asyncio.wait_for(slow_generation.wait(), 20)
        await send(4, "那如果换成手机，刚才那个办法还适用吗", reply=True, user=USER + 1)
        await send(5, "我和他约了今晚去吃烧烤", user=USER + 2)
        release_generation.set()
        await wait_until(lambda: len(outbound) == 2 and any(5 in item["indices"] for item in decisions))
        await asyncio.sleep(0.5)
        assert next(item for item in decisions if 3 in item["indices"])["controls"]["DIRECT_CALL"]
        followup = next(item for item in decisions if 4 in item["indices"])["controls"]
        assert not followup["DIRECT_CALL"] and followup["RECENT_OWN_TOPIC"] and not followup["ALLOW_UNRELATED"]
        assert all(len(item["indices"]) == 1 for item in decisions)
        report["keyword_call_immediate_and_queued_topics_kept_separate"] = True
        report["semantic_followup_gets_recent_actual_bot_topic"] = True
        report["unrelated_after_reply_has_no_insertion_opportunity"] = True

        await send(6, "刚才那一步我补充一下", reply=True)
        await send(7, "我用的是另外一台手机", reply=True)
        await wait_until(lambda: len(outbound) == 3)
        assert next(item for item in decisions if 6 in item["indices"])["indices"] == [6, 7]
        report["same_author_fragments_get_one_reply"] = True

        await send(8, "大肥鱼这次只接这一句", reply=True)
        await wait_until(lambda: len(outbound) == 4)
        await asyncio.sleep(1)
        assert len(outbound) == 4
        report["duplicate_reply_in_single_tool_batch_blocked"] = True
        assert len(decisions) == 7, [item["indices"] for item in decisions]
        report["no_second_planner_sweep_after_reply"] = True

        await asyncio.to_thread(manager.save_group_reply_frequency, {"group_reply_frequency": 0})
        await asyncio.sleep(1.5)
        before = len(requests)
        await send(9, "大肥鱼静默时也不回复", reply=True)
        await asyncio.sleep(1.5)
        assert len(requests) == before and len(outbound) == 4
        report["zero_stays_silent_even_for_keyword"] = True

        await asyncio.to_thread(manager.save_group_reply_frequency, {"group_reply_frequency": 1})
        await asyncio.sleep(1.5)
        await send(10, "逐条模式第一句", user=USER + 1)
        await send(11, "逐条模式第二句", user=USER + 2)
        await wait_until(lambda: len(outbound) == 6)
        assert len(decisions) == 7
        report["one_keeps_native_each_message_behavior"] = True
        await asyncio.to_thread(manager.save_group_reply_frequency, {"group_reply_frequency": 0.8})
        await asyncio.sleep(1.5)
        await send(12, "大肥鱼切回话题模式了", reply=True)
        await wait_until(lambda: len(outbound) == 7)
        assert next(item for item in decisions if 12 in item["indices"])["controls"]["DIRECT_CALL"]
        report["hot_reload_back_to_topic_mode"] = True
        before = len(requests)
        await send(13, "大肥鱼这是自身回声", user=BOT)
        await asyncio.sleep(1)
        assert len(requests) == before and len(outbound) == 7
        report["self_echo_does_not_trigger"] = True
        report["mock_planner_requests"] = len(decisions)
        report["mock_total_model_requests"] = len(requests)
        report["mock_outbound_messages"] = len(outbound)
    except Exception:
        report["error"] = traceback.format_exc()
        raise
    finally:
        release_generation.set()
        report["shutdown"] = await asyncio.to_thread(manager.stop)
        await runner.cleanup()
        atomic_text(ROOT / "verification/topic-reply-acceptance.json", json.dumps(report, ensure_ascii=False, indent=2))
        atomic_text(ROOT / "verification/topic-reply-fixture-core.log", "\n".join(manager.logs))
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
