"""真实 MaiBot 与官方 QQ 连接器的本机模拟联调，不使用真实账号或付费 API。"""

from pathlib import Path

import asyncio
import json
import sqlite3
import time

from aiohttp import web

from fatfish.core import ROOT, FishManager

BOT = 100000001
USER = 100000002
GROUP = 123456789
BLOCKED = 223456789


async def main():
    message_base = int(time.time()) * 10
    allowed_id = str(message_base + 2)
    blocked_id = str(message_base + 1)
    manager = FishManager(instance_name="integration-test")
    await asyncio.to_thread(manager.initialize)
    await asyncio.to_thread(manager.save, {"api_base": "http://127.0.0.1:19381/v1", "api_key": "local-test-only",
                                          "model": "local-test-model", "qq_account": str(BOT),
                                          "groups": [str(GROUP)], "users": [], "qq_port": 19382})
    outbound, calls, requests = [], [], []
    connections = set()
    login_ready = asyncio.Event()

    async def model(request):
        data = await request.json()
        requests.append(data)
        if len(requests) > 15:
            return web.json_response({"error": {"message": "test request cap"}}, status=429)
        message = {"role": "assistant", "content": "本地联调成功，我已经收到这条群消息。"}
        tool_names = [tool.get("function", {}).get("name") for tool in data.get("tools", [])]
        if "reply" in tool_names and not any(m.get("role") == "tool" for m in data.get("messages", [])):
            message = {"role": "assistant", "content": None, "tool_calls": [{"id": "call-local-reply", "type": "function", "function": {
                "name": "reply", "arguments": json.dumps({"msg_id": allowed_id, "reply_reference": "群友正在做本地联调，简短确认已经收到消息。"}, ensure_ascii=False)}}]}
        return web.json_response({"id": "local-test", "object": "chat.completion", "created": int(time.time()),
                                  "model": "local-test-model", "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if "tool_calls" in message else "stop"}],
                                  "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}})

    async def ws_handler(request):
        expected = manager.settings(private=True)["qq_token"]
        if request.headers.get("Authorization") != "Bearer " + expected:
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
                calls.append(action)
                result = {}
                if action == "get_version_info":
                    result = {"app_name": "NapCat", "app_version": "test", "protocol_version": "v11"}
                elif action == "get_login_info":
                    result = {"user_id": BOT, "nickname": "测试鱼"}
                    login_ready.set()
                elif action == "get_status":
                    result = {"online": True, "good": True}
                elif action in {"get_group_info", "get_group_list"}:
                    result = {"group_id": GROUP, "group_name": "本地模拟测试群", "member_count": 2, "max_member_count": 200}
                    if action == "get_group_list":
                        result = [result]
                elif action in {"get_group_member_info", "get_stranger_info"}:
                    result = {"group_id": GROUP, "user_id": params.get("user_id", USER), "nickname": "模拟群友", "card": "", "role": "member", "sex": "unknown", "age": 0}
                elif action in {"get_friend_list", "get_group_member_list"}:
                    result = []
                elif action in {"send_group_msg", "send_msg"}:
                    outbound.append(params)
                    result = {"message_id": 900001 + len(outbound)}
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
    await web.TCPSite(runner, "127.0.0.1", 19381).start()
    await web.TCPSite(runner, "127.0.0.1", 19382).start()
    report = {}
    try:
        manager.start()
        deadline = time.monotonic() + 70
        while time.monotonic() < deadline:
            if not manager.running():
                raise RuntimeError("核心提前退出：\n" + "\n".join(manager.logs)[-4000:])
            if manager.boot_ready and login_ready.is_set():
                break
            await asyncio.sleep(0.5)
        else:
            raise TimeoutError("核心或 QQ 适配器未就绪")
        await asyncio.sleep(1)
        report["qq_login_check"] = (await asyncio.to_thread(manager.check_qq))["message"]
        for group, message_id in ((BLOCKED, int(blocked_id)), (GROUP, int(allowed_id))):
            event = {"time": int(time.time()), "self_id": BOT, "post_type": "message", "message_type": "group",
                     "sub_type": "normal", "message_id": message_id, "group_id": group, "user_id": USER,
                     "message": [{"type": "at", "data": {"qq": str(BOT)}}, {"type": "text", "data": {"text": " 大肥鱼，本地联调测试，请回一句话"}}],
                     "raw_message": f"[CQ:at,qq={BOT}] 大肥鱼，本地联调测试，请回一句话", "font": 0,
                     "sender": {"user_id": USER, "nickname": "模拟群友", "card": "", "role": "member"}}
            for ws in list(connections):
                await ws.send_json(event)
        deadline = time.monotonic() + 65
        while time.monotonic() < deadline and not outbound:
            if not manager.running():
                raise RuntimeError("收发过程中核心退出")
            await asyncio.sleep(0.5)
        report["outbound"] = outbound
        report["model_calls"] = len(requests)
        report["actions"] = sorted(set(calls))
        with sqlite3.connect(manager.instance / "data" / "MaiBot.db") as db:
            report["allowed_received"] = db.execute("SELECT count(*) FROM mai_messages WHERE message_id=?", (allowed_id,)).fetchone()[0]
            report["blocked_received"] = db.execute("SELECT count(*) FROM mai_messages WHERE message_id=?", (blocked_id,)).fetchone()[0]
        report["reply_received"] = bool(outbound)
        report["persona_in_model_request"] = any("你叫大肥鱼" in json.dumps(r, ensure_ascii=False) for r in requests)
        assert report["allowed_received"] >= 1, "允许群的消息未入库"
        assert report["blocked_received"] == 0, "未允许群的消息被处理"
        assert outbound, "没有收到官方连接器发出的回复"
        assert all(str(p.get("group_id")) == str(GROUP) for p in outbound), "回复目标群错误"
        assert report["persona_in_model_request"], "模型请求缺少大肥鱼人格"
    finally:
        report["shutdown"] = (await asyncio.to_thread(manager.stop))["message"]
        report["exit_code"] = manager.process.returncode if manager.process else None
        output = ROOT / "verification"
        output.mkdir(exist_ok=True)
        (output / "integration-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (output / "integration-core.log").write_text("\n".join(manager.logs), encoding="utf-8")
        (output / "integration-model-requests.json").write_text(json.dumps(requests, ensure_ascii=False, indent=2), encoding="utf-8")
        await runner.cleanup()
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
