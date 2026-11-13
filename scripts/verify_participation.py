"""隔离浏览器 + 真实聊天核心 + 本机模拟模型/QQ，验证频率滑块与逐条回复。"""
from pathlib import Path
from unittest.mock import patch

import asyncio
import json
import threading
import time
import tomlkit

from aiohttp import web
from playwright.sync_api import sync_playwright

from fatfish.core import ROOT, FishManager, atomic_text
from fatfish.server import LocalServer

BOT, USER, GROUP = 100000011, 100000012, 123456788


def check_ui(url, values, screenshot=False):
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 950})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url)
        page.get_by_role("button", name="✦ 人格与记忆").click()
        slider = page.get_by_role("slider", name="主动接话频率")
        page.wait_for_function("Number.isFinite(saved.group_reply_frequency)")
        for value in values:
            page.get_by_label("名字", exact=True).fill("尚未保存的名字")
            # 用键盘操作原生滑块，覆盖真正的 input 事件与表单提交。
            slider.focus()
            slider.press("Home")
            for _ in range(round(value / 0.05)):
                slider.press("ArrowRight")
            assert abs(float(slider.input_value()) - value) < 0.00001
            assert page.locator("#reply-frequency-value").inner_text() == f"{value:.2f}"
            page.get_by_role("button", name="保存接话频率", exact=True).click()
            page.get_by_role("status").filter(has_text="接话频率已保存").wait_for()
            page.wait_for_function("value => saved.group_reply_frequency === value", arg=value)
            assert page.get_by_label("名字", exact=True).input_value() == "尚未保存的名字"
            page.reload()
            page.get_by_role("button", name="✦ 人格与记忆").click()
            page.wait_for_function("value => saved.group_reply_frequency === value", arg=value)
            assert abs(float(slider.input_value()) - value) < 0.00001
        if screenshot:
            page.screenshot(path=str(ROOT / "verification/participation-desktop.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
            page.screenshot(path=str(ROOT / "verification/participation-mobile.png"), full_page=True)
        assert not errors, errors
        browser.close()
    return {"saved_values": values, "reload_persisted": True, "js_errors": errors}


async def main():
    output = ROOT / "verification"
    output.mkdir(exist_ok=True)
    manager = FishManager(instance_name="participation-fixture")
    await asyncio.to_thread(manager.initialize)
    await asyncio.to_thread(manager.save, {
        "api_base": "http://127.0.0.1:19481/v1", "api_key": "participation-fixture-only",
        "model": "local-test-model", "qq_account": str(BOT), "groups": [str(GROUP)],
        "private_scope": "off", "users": [], "qq_port": 19482,
        "group_reply_frequency": 0.5, "memory_enabled": False, "collect_emoji": False,
    })
    # 仅隔离测试更换 HTTP 端口，正式千鱼与 QQ 保持在线。
    original_apply = manager.apply_config
    def isolated_apply(data):
        original_apply(data)
        path = manager.instance / "config/bot_config.toml"
        doc = tomlkit.parse(path.read_text(encoding="utf-8"))
        doc["http"]["port"] = 18051
        atomic_text(path, tomlkit.dumps(doc))
    manager.apply_config = isolated_apply
    server = LocalServer(("127.0.0.1", 0), manager)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/#token={server.token}"
    outbound, requests, connections = [], [], set()
    login_ready = asyncio.Event()
    first_generation = asyncio.Event()
    report = {"real_qq_messages": 0, "paid_model_requests": 0}

    async def model(request):
        body = await request.json()
        requests.append(body)
        if len(requests) > 25:
            return web.json_response({"error": {"message": "fixture request cap"}}, status=429)
        first_generation.set()
        await asyncio.sleep(0.2)
        return web.json_response({"id": "participation-local", "object": "chat.completion", "created": int(time.time()),
            "model": "local-test-model", "choices": [{"index": 0, "message": {"role": "assistant", "content": "收到啦"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 5, "total_tokens": 55}})

    async def ws_handler(request):
        if request.headers.get("Authorization") != "Bearer " + manager.settings(private=True)["qq_token"]:
            return web.Response(status=401)
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        connections.add(ws)
        try:
            async for message in ws:
                if message.type != web.WSMsgType.TEXT:
                    continue
                body = json.loads(message.data)
                action, params = body.get("action"), body.get("params", {})
                result = {}
                if action == "get_version_info":
                    result = {"app_name": "NapCat", "app_version": "fixture", "protocol_version": "v11"}
                elif action == "get_login_info":
                    result = {"user_id": BOT, "nickname": "测试鱼"}
                    login_ready.set()
                elif action == "get_status":
                    result = {"online": True, "good": True}
                elif action in {"get_group_info", "get_group_list"}:
                    result = {"group_id": GROUP, "group_name": "隔离频率测试群", "member_count": 2, "max_member_count": 200}
                    if action == "get_group_list":
                        result = [result]
                elif action in {"get_group_member_info", "get_stranger_info"}:
                    result = {"group_id": GROUP, "user_id": params.get("user_id", USER), "nickname": "模拟群友", "card": "", "role": "member", "sex": "unknown", "age": 0}
                elif action in {"get_friend_list", "get_group_member_list"}:
                    result = []
                elif action in {"send_group_msg", "send_msg"}:
                    outbound.append(params)
                    result = {"message_id": 910000 + len(outbound)}
                elif action == "get_msg":
                    result = {"message_id": params.get("message_id"), "message": [], "sender": {"user_id": USER}}
                await ws.send_json({"status": "ok", "retcode": 0, "data": result, "echo": body.get("echo")})
        finally:
            connections.discard(ws)
        return ws

    app = web.Application()
    app.router.add_post("/v1/chat/completions", model)
    app.router.add_get("/", ws_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 19481).start()
    await web.TCPSite(runner, "127.0.0.1", 19482).start()
    message_base = int(time.time()) * 10
    async def send(index, text, user=USER):
        event = {"time": int(time.time()), "self_id": BOT, "post_type": "message", "message_type": "group",
            "sub_type": "normal", "message_id": message_base + index, "group_id": GROUP, "user_id": user,
            "message": [{"type": "text", "data": {"text": text}}], "raw_message": text, "font": 0,
            "sender": {"user_id": user, "nickname": "模拟群友", "card": "", "role": "member"}}
        for ws in list(connections):
            await ws.send_json(event)

    async def wait_until(predicate, seconds=30):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if predicate():
                return
            if not manager.running():
                raise RuntimeError("隔离核心退出")
            await asyncio.sleep(0.1)
        raise TimeoutError("隔离验收等待超时")

    try:
        report["ui"] = await asyncio.to_thread(check_ui, url, [0, 0.35, 1, 0.5], True)
        with patch("fatfish.core.tcp_open", return_value=False):
            await asyncio.to_thread(manager.start)
        await wait_until(lambda: manager.boot_ready and login_ready.is_set(), 70)
        report["runtime_ui"] = await asyncio.to_thread(check_ui, url, [1])
        await wait_until(lambda: any("配置热重载完成" in line for line in manager.logs))
        await send(1, "今天下雨了")
        await asyncio.wait_for(first_generation.wait(), timeout=30)
        # 回复生成期间连发两条，不能只回应最后一条。
        await send(2, "我刚吃完晚饭")
        await send(3, "准备去看电影")
        await wait_until(lambda: len(outbound) >= 3)
        await asyncio.sleep(1)
        assert len(outbound) == 3, len(outbound)
        report["three_unmentioned_messages_three_replies"] = True
        await send(4, "这是机器人自身的回声", user=BOT)
        await asyncio.sleep(1)
        assert len(outbound) == 3, "机器人回复了自身消息"
        report["self_echo_did_not_loop"] = True
        await asyncio.to_thread(check_ui, url, [0])
        await asyncio.sleep(1)
        calls_before, sent_before = len(requests), len(outbound)
        await send(5, "关闭频率后的消息")
        await asyncio.sleep(2)
        assert len(outbound) == sent_before and len(requests) == calls_before
        report["zero_consumes_without_reply_or_model_request"] = True
        await asyncio.to_thread(check_ui, url, [1])
        await asyncio.sleep(1)
        await send(6, "重新开启逐条回复")
        await wait_until(lambda: len(outbound) == 4)
        report["live_zero_to_one_resumed"] = True
        assert all(str(item.get("group_id")) == str(GROUP) for item in outbound)
        report["mock_outbound_count"] = len(outbound)
        report["mock_model_requests"] = len(requests)
    finally:
        report["shutdown"] = await asyncio.to_thread(manager.stop)
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        await runner.cleanup()
        (output / "participation-acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (output / "participation-fixture-core.log").write_text("\n".join(manager.logs), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
