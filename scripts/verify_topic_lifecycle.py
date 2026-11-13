"""真实核心接模拟 QQ/模型，检验三入口、话题关闭和概率 UI；不发真实消息。"""
from unittest.mock import patch

import asyncio
import json
import re
import threading
import time
import traceback
import tomlkit

from aiohttp import web
from playwright.sync_api import sync_playwright

from fatfish.core import ROOT, FishManager, atomic_text
from fatfish.server import LocalServer

BOT, USER, GROUP = 100000031, 100000032, 123456790


def verify_ui(manager):
    server = LocalServer(("127.0.0.1", 0), manager)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1240, "height": 900})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}/#token={server.token}")
            page.get_by_role("button", name="✦ 人格与记忆", exact=True).click()
            page.wait_for_function("Number.isFinite(saved.group_reply_frequency)")
            slider = page.get_by_role("slider", name="新话题触发概率")
            for value in (0, 0.25, 1, 0):
                slider.focus()
                slider.press("Home")
                for _ in range(round(value * 100)):
                    slider.press("ArrowRight")
                assert abs(float(slider.input_value()) - value) < 0.00001
                assert page.locator("#reply-frequency-value").inner_text() == f"{value * 100:.0f}%"
                page.get_by_role("button", name="保存新话题概率", exact=True).click()
                page.wait_for_function("v => saved.group_reply_frequency === v", arg=value)
                page.reload()
                page.get_by_role("button", name="✦ 人格与记忆", exact=True).click()
                page.wait_for_function("v => saved.group_reply_frequency === v", arg=value)
            assert "仍会回应呼叫" in page.locator("#reply-frequency-hint").inner_text()
            page.locator("#participation-form").screenshot(path=str(ROOT / "verification/topic-lifecycle-control.png"))
            page.set_viewport_size({"width": 390, "height": 844})
            assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    return {"saved_probabilities": [0, 0.25, 1], "percentage_display": True, "reload_persisted": True, "js_errors": errors}


async def main():
    manager = FishManager(instance_name="topic-lifecycle-fixture")
    await asyncio.to_thread(manager.initialize)
    await asyncio.to_thread(manager.save, {"api_base": "http://127.0.0.1:19501/v1", "api_key": "lifecycle-fixture-only",
        "model": "local-test-model", "qq_account": str(BOT), "groups": [str(GROUP)], "group_scope": "selected",
        "private_scope": "off", "qq_port": 19502, "group_reply_frequency": 0, "memory_enabled": False, "collect_emoji": False})
    atomic_text(manager.instance / "social/topic-reply.json", json.dumps({"enabled": True, "keywords": ["大肥鱼"]}, ensure_ascii=False))
    original_apply = manager.apply_config
    def isolated_apply(data):
        original_apply(data)
        path = manager.instance / "config/bot_config.toml"
        doc = tomlkit.parse(path.read_text(encoding="utf-8"))
        doc["http"]["port"] = 18053
        atomic_text(path, tomlkit.dumps(doc))
    manager.apply_config = isolated_apply
    connections, outbound, requests, decisions, planners = set(), [], [], [], []
    base = int(time.time()) * 100
    generation_started, release_generation = asyncio.Event(), asyncio.Event()
    report = {"real_qq_test_messages": 0, "paid_model_test_requests": 0}

    async def model(request):
        body = await request.json()
        requests.append(body)
        if len(requests) > 70:
            return web.json_response({"error": {"message": "fixture request cap"}}, status=429)
        texts = "\n".join(str(item.get("content", "")) for item in body.get("messages", []))
        calls = None
        if "TOPIC_DECISION_V2" in texts:
            payload = json.loads(next(line for line in texts.splitlines() if line.startswith('{"topic_active":')))
            indices = [int(item["id"]) - base for item in payload["new_messages"]]
            decisions.append({"indices": indices, "context": payload})
            index = next((candidate for candidate in (2, 3, 8, 9, 10) if candidate in indices), indices[-1])
            relation = "direct" if index in (2, 8) else "new" if index == 9 else "continuation"
            action = "reply" if index in (2, 3, 8, 9, 10) else "end" if index in (6, 12) else "skip"
            if action == "skip":
                relation = "unrelated"
            keep = index not in (6, 8, 12)
            decision = {"action": action, "relation": relation, "target_message_id": str(base + index), "keep_open": keep,
                        "topic_summary": "手机设置的讨论", "reply_direction": f"case-{index} 简短回答，不反问"}
            message = {"role": "assistant", "content": json.dumps(decision, ensure_ascii=False)}
        elif "CURRENT_MESSAGE_IDS" in texts:
            match = re.search(r'\{"CURRENT_MESSAGE_IDS":.*', texts)
            payload = json.loads(match.group(0))
            index = int(payload["CURRENT_MESSAGE_IDS"][0]) - base
            planners.append(index)
            names = [tool["function"]["name"] for tool in body.get("tools", [])]
            assert "reply" in names and "wait" not in names, names
            args = json.dumps({"msg_id": str(base + index), "reply_reference": f"case-{index} 回答当前问题"}, ensure_ascii=False)
            calls = [{"id": f"reply-{len(requests)}", "type": "function", "function": {"name": "reply", "arguments": args}}]
            if index == 9:
                calls.append({"id": f"duplicate-{len(requests)}", "type": "function", "function": {"name": "reply", "arguments": args}})
            message = {"role": "assistant", "content": None, "tool_calls": calls}
        else:
            if not generation_started.is_set():
                generation_started.set()
                await asyncio.wait_for(release_generation.wait(), 20)
            message = {"role": "assistant", "content": "先试一下这个设置"}
        return web.json_response({"id": "lifecycle-local", "object": "chat.completion", "created": int(time.time()),
            "model": "local-test-model", "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if calls else "stop"}],
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
                    result = {"group_id": GROUP, "group_name": "隔离话题生命周期群", "member_count": 4, "max_member_count": 200}
                    if action == "get_group_list":
                        result = [result]
                elif action in {"get_group_member_info", "get_stranger_info"}:
                    result = {"group_id": GROUP, "user_id": params.get("user_id", USER), "nickname": "模拟群友",
                              "card": "", "role": "member", "sex": "unknown", "age": 0}
                elif action in {"get_friend_list", "get_group_member_list"}:
                    result = []
                elif action in {"send_group_msg", "send_msg"}:
                    outbound.append(params)
                    result = {"message_id": 930000 + len(outbound)}
                await ws.send_json({"status": "ok", "retcode": 0, "data": result, "echo": body.get("echo")})
        finally:
            connections.discard(ws)
        return ws

    app = web.Application()
    app.router.add_post("/v1/chat/completions", model)
    app.router.add_get("/", qq)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 19501).start()
    await web.TCPSite(runner, "127.0.0.1", 19502).start()
    async def wait_until(predicate, seconds=20):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if predicate():
                return
            if not manager.running():
                raise RuntimeError("隔离核心退出")
            await asyncio.sleep(0.1)
        raise TimeoutError("生命周期验收超时")
    async def send(index, text, user=USER):
        event = {"time": int(time.time()), "self_id": BOT, "post_type": "message", "message_type": "group", "sub_type": "normal",
                 "message_id": base + index, "group_id": GROUP, "user_id": user,
                 "message": [{"type": "text", "data": {"text": text}}], "raw_message": text, "font": 0,
                 "sender": {"user_id": user, "nickname": "模拟群友", "card": "", "role": "member"}}
        for ws in list(connections):
            await ws.send_json(event)
    def saw(index):
        return any(index in item["indices"] for item in decisions)

    try:
        report["ui"] = await asyncio.to_thread(verify_ui, manager)
        with patch("fatfish.core.tcp_open", return_value=False):
            await asyncio.to_thread(manager.start)
        await wait_until(lambda: manager.boot_ready and connections, 70)
        await send(1, "别人讨论自己的晚饭")
        await asyncio.sleep(1.5)
        assert not requests and not outbound
        report["zero_no_call_no_topic_makes_no_model_request"] = True
        await send(2, "大肥鱼帮我看看手机设置")
        await asyncio.wait_for(generation_started.wait(), 20)
        await send(3, "你刚说的那一步怎么设置")
        await send(4, "我和另一个人要去吃饭", user=USER + 1)
        await asyncio.sleep(0.3)
        release_generation.set()
        await wait_until(lambda: len(outbound) == 2)
        followup = next(item for item in decisions if 3 in item["indices"])
        assert followup["context"]["topic_active"] and not followup["context"]["allow_new_topic"]
        assert planners[:2] == [2, 3]
        report["zero_still_answers_call_and_continues_open_topic"] = True
        report["busy_context_does_not_produce_reply_for_each_message"] = True

        await send(5, "他刚买的新手机多少钱", user=USER + 2)
        await wait_until(lambda: saw(5))
        await asyncio.sleep(0.5)
        assert len(outbound) == 2
        report["same_subject_others_chat_can_be_skipped"] = True
        await send(6, "好，明白了，不用继续了")
        await wait_until(lambda: saw(6))
        await asyncio.sleep(0.5)
        before = len(decisions)
        await send(7, "刚才也是在说手机设置")
        await asyncio.sleep(1.5)
        assert len(decisions) == before and len(outbound) == 2
        report["ended_topic_does_not_revive_from_history_or_emit_farewell"] = True

        await send(8, "大肥鱼最后确认一下这个选项")
        await wait_until(lambda: len(outbound) == 3)
        await asyncio.to_thread(manager.save_group_reply_frequency, {"group_reply_frequency": 1})
        await asyncio.sleep(1.5)
        await send(9, "今天怎么选手机设置比较合适")
        await wait_until(lambda: len(outbound) == 4)
        assert next(item for item in decisions if 9 in item["indices"])["context"]["allow_new_topic"]
        await send(10, "你刚才提到的那个方法呢")
        await wait_until(lambda: len(outbound) == 5)
        await send(11, "另两个人也在聊手机", user=USER + 2)
        await wait_until(lambda: saw(11))
        await asyncio.sleep(0.5)
        assert len(outbound) == 5
        report["one_is_new_topic_probability_not_each_message_mode"] = True
        report["random_opening_can_continue_as_active_topic"] = True
        report["duplicate_reply_in_one_tool_batch_blocked"] = True
        await send(12, "谢谢，已经解决了")
        await wait_until(lambda: saw(12))
        await asyncio.to_thread(manager.save_group_reply_frequency, {"group_reply_frequency": 0})
        await asyncio.sleep(1.5)
        before = len(decisions)
        await send(13, "回忆一下刚才的手机")
        await asyncio.sleep(1.5)
        assert len(decisions) == before and len(outbound) == 5
        report["second_topic_ends_and_no_followup_is_forced"] = True
        assert planners == [2, 3, 8, 9, 10], planners
        report["planner_runs_only_after_reply_admission"] = True
        report["mock_decision_count"] = len(decisions)
        report["mock_visible_replies"] = len(outbound)
    except Exception:
        report["error"] = traceback.format_exc()
        raise
    finally:
        release_generation.set()
        report["shutdown"] = await asyncio.to_thread(manager.stop)
        await runner.cleanup()
        atomic_text(ROOT / "verification/topic-lifecycle-acceptance.json", json.dumps(report, ensure_ascii=False, indent=2))
        atomic_text(ROOT / "verification/topic-lifecycle-fixture-core.log", "\n".join(manager.logs))
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
