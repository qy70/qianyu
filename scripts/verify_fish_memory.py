"""Native core against local QQ/model fixtures; never contacts real QQ or a paid model."""
from pathlib import Path
from unittest.mock import patch
import asyncio
import json
import re
import secrets
import threading
import time
import traceback

import tomlkit
from aiohttp import web
from playwright.sync_api import expect, sync_playwright
from fatfish.core import FishManager, ROOT, atomic_text
from fatfish.fish_identity import FishIdentityMemory, person_id
from fatfish.server import LocalServer

BOT, FISH, HUMAN, GROUP = 100000041, 100000042, 100000043, 123456791


def verify_ui(manager):
    server = LocalServer(("127.0.0.1", 0), manager)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1050})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}/#token={server.token}")
            page.get_by_role("button", name="✦ 人格与记忆", exact=True).click()
            expect(page.get_by_label("人物身份", exact=True)).to_have_value("fish")
            page.get_by_label("人物 QQ 号").fill("100000099")
            page.get_by_label("人物身份", exact=True).select_option("human")
            page.get_by_role("button", name="保存人物身份", exact=True).click()
            expect(page.locator("#fish-identities")).to_contain_text("100000099 · 真人")
            page.reload(); page.get_by_role("button", name="✦ 人格与记忆", exact=True).click()
            expect(page.locator("#fish-identities")).to_contain_text("100000099 · 真人")
            page.get_by_label("人物 QQ 号").fill("100000099")
            page.get_by_label("人物身份", exact=True).select_option("unknown")
            page.get_by_role("button", name="保存人物身份", exact=True).click()
            expect(page.locator("#fish-identities")).to_contain_text("100000099 · 待判断")
            toggle = page.locator('[name="shared_memory_enabled"]')
            expect(toggle).to_be_checked()
            toggle.uncheck(); page.get_by_role("button", name="保存人格与记忆设置", exact=True).click()
            expect(page.locator("#notice")).to_contain_text("设置已保存")
            page.reload(); page.get_by_role("button", name="✦ 人格与记忆", exact=True).click()
            expect(toggle).not_to_be_checked()
            toggle.check(); page.get_by_role("button", name="保存人格与记忆设置", exact=True).click()
            expect(page.locator("#notice")).to_contain_text("设置已保存")
            page.locator("#fish-identity-form").scroll_into_view_if_needed()
            page.screenshot(path=str(ROOT / "verification/fish-0314-ui.png"), full_page=True)
            page.set_viewport_size({"width":390,"height":844})
            assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)
    return {"manual_identity_correction_persists":True,"shared_memory_toggle_persists":True,"js_errors":errors}


async def main():
    manager = FishManager(instance_name="fish-memory-0314-" + secrets.token_hex(4))
    await asyncio.to_thread(manager.initialize)
    await asyncio.to_thread(manager.save, {"api_base":"http://127.0.0.1:19531/v1","api_key":"fixture-only",
        "model":"local-test-model","qq_account":str(BOT),"groups":[str(GROUP)],"group_scope":"selected",
        "private_scope":"all","qq_port":19532,"group_reply_frequency":1,"memory_enabled":True,
        "collect_emoji":False,"vision_enabled":False})
    atomic_text(manager.instance / "social/topic-reply.json", json.dumps({"enabled":True,"keywords":["大肥鱼"]},ensure_ascii=False))
    FishIdentityMemory(manager.instance).correct(str(FISH), "fish")
    original_apply = manager.apply_config
    def isolated_apply(data):
        original_apply(data)
        path = manager.instance / "config/bot_config.toml"
        doc = tomlkit.parse(path.read_text("utf-8"))
        doc["http"]["port"] = 18056
        # The real long-term backend is tested separately with synthetic hits.
        # Disable it here so no embedding/download endpoints can be contacted.
        doc["a_memorix"]["plugin"]["enabled"] = False
        doc["response_splitter"]["mode"] = "rule"
        atomic_text(path, tomlkit.dumps(doc))
    manager.apply_config = isolated_apply
    connections, outbound, requests, decisions, failed_sends = set(), [], [], [], []
    base, current = int(time.time()) * 100, {"index":0}
    report = {"real_qq_messages":0,"paid_model_requests":0,"fixture":str(manager.instance)}

    async def model(request):
        body = await request.json(); requests.append(body)
        if len(requests)>100: return web.Response(status=429)
        texts = "\n".join(str(item.get("content", "")) for item in body.get("messages", []))
        calls = None
        if "TOPIC_DECISION_V2" in texts:
            payload=json.loads(next(line for line in texts.splitlines() if line.startswith('{"topic_active":')))
            target=payload["new_messages"][-1]["id"]; index=int(target)-base
            decisions.append(index)
            decision={"action":"reply","relation":"direct","target_message_id":target,"keep_open":False,
                "topic_summary":"回忆共同经历","reply_direction":"回答当前问题", "starts_new_topic":index==6}
            message={"role":"assistant","content":json.dumps(decision,ensure_ascii=False)}
        elif any(t.get("function",{}).get("name")=="reply" for t in body.get("tools", [])):
            index=current["index"]
            if index==10:
                assert "group-evidence-0314" in texts, "private planner did not recall group history"
                report["private_planner_received_group_history_before_summary"]=True
            if index==11:
                assert "private-evidence-0314" in texts, "group planner did not recall private history"
                report["group_planner_received_same_account_private_history"]=True
            args=json.dumps({"msg_id":str(base+index),"reply_reference":"自然回答当前问题"},ensure_ascii=False)
            calls=[{"id":"reply-"+str(len(requests)),"type":"function","function":{"name":"reply","arguments":args}}]
            if index==2: calls.append({**calls[0],"id":"duplicate-reply"})
            message={"role":"assistant","content":None,"tool_calls":calls}
        else:
            text = "这是已经送达的第一段。\n这是发送失败的第二段。" if current["index"]==3 else "这是隔离测试的可见回复"
            message={"role":"assistant","content":text}
        return web.json_response({"id":"fish-memory-fixture","object":"chat.completion","created":int(time.time()),
            "model":"local-test-model","choices":[{"index":0,"message":message,"finish_reason":"tool_calls" if calls else "stop"}],
            "usage":{"prompt_tokens":50,"completion_tokens":5,"total_tokens":55}})

    async def qq(request):
        if request.headers.get("Authorization")!="Bearer "+manager.settings(private=True)["qq_token"]: return web.Response(status=401)
        ws=web.WebSocketResponse(); await ws.prepare(request); connections.add(ws)
        try:
            async for incoming in ws:
                if incoming.type!=web.WSMsgType.TEXT: continue
                body=json.loads(incoming.data); action=body.get("action"); params=body.get("params",{}); data={}
                if action=="get_version_info": data={"app_name":"NapCat","app_version":"fixture","protocol_version":"v11"}
                elif action=="get_login_info": data={"user_id":BOT,"nickname":"测试鱼"}
                elif action=="get_status": data={"online":True,"good":True}
                elif action in {"get_group_info","get_group_list"}:
                    data={"group_id":GROUP,"group_name":"隔离测试群","member_count":4,"max_member_count":200}
                    if action=="get_group_list": data=[data]
                elif action in {"get_group_member_info","get_stranger_info"}:
                    data={"group_id":GROUP,"user_id":params.get("user_id",HUMAN),"nickname":"同名测试用户","card":"","role":"member","sex":"unknown","age":0}
                elif action in {"get_friend_list","get_group_member_list"}: data=[]
                elif action in {"send_group_msg","send_private_msg","send_msg"}:
                    if current["index"]==3 and any(item["case"]==3 for item in outbound):
                        failed_sends.append(3)
                        await ws.send_json({"status":"failed","retcode":100,"data":{},"echo":body.get("echo")})
                        continue
                    outbound.append({"case":current["index"],"params":params}); data={"message_id":940000+len(outbound)}
                await ws.send_json({"status":"ok","retcode":0,"data":data,"echo":body.get("echo")})
        finally: connections.discard(ws)
        return ws

    app=web.Application(); app.router.add_post("/v1/chat/completions",model); app.router.add_get("/",qq)
    runner=web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner,"127.0.0.1",19531).start(); await web.TCPSite(runner,"127.0.0.1",19532).start()
    async def wait_until(predicate,seconds=30):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            if predicate(): return
            if not manager.running(): raise RuntimeError("fixture core exited")
            await asyncio.sleep(.1)
        raise TimeoutError("fixture timeout; last log: "+"\n".join(list(manager.logs)[-12:]))
    async def start():
        with patch("fatfish.core.tcp_open",return_value=False): await asyncio.to_thread(manager.start)
        await wait_until(lambda:manager.boot_ready and connections,70)
    async def send(index,text,user=FISH,private=False):
        current["index"]=index
        event={"time":int(time.time()),"self_id":BOT,"post_type":"message","message_type":"private" if private else "group",
            "sub_type":"friend" if private else "normal","message_id":base+index,"user_id":user,
            "message":[{"type":"text","data":{"text":text}}],"raw_message":text,"font":0,
            "sender":{"user_id":user,"nickname":"同名测试用户","card":"","role":"member"}}
        if not private: event["group_id"]=GROUP
        for ws in list(connections): await ws.send_json(event)
    async def replied(index):
        await wait_until(lambda:any(item["case"]==index for item in outbound)); await asyncio.sleep(.6)
    try:
        report["ui"]=await asyncio.to_thread(verify_ui,manager)
        await start()
        for index in (1,2,3):
            await send(index,"大肥鱼继续回答同一问题"); await replied(index)
        await wait_until(lambda:bool(failed_sends))
        await asyncio.sleep(1)
        assert len([item for item in outbound if item["case"]==3])==1
        report["partially_delivered_third_round_counts_once"]=True
        for index in (4,):
            before=len(requests); await send(index,"大肥鱼 @你 继续同一问题"); await asyncio.sleep(2)
            assert len(requests)==before and not any(item["case"]==index for item in outbound)
        await asyncio.to_thread(manager.stop); await wait_until(lambda:not connections)
        await start()
        before=len(requests); await send(5,"大肥鱼重启以后继续同一问题"); await asyncio.sleep(2)
        assert len(requests)==before
        report["fourth_reply_blocked_across_restart_and_calls"]=True
        await send(6,"大肥鱼我们换个实质不同的新话题",user=HUMAN); await replied(6)
        await send(7,"大肥鱼回答新话题"); await replied(7)
        report["nonfish_new_topic_resets_budget"]=True
        assert len([item for item in outbound if item["case"]==2])==1
        report["duplicate_reply_tool_does_not_double_send"]=True
        await send(9,"大肥鱼记住 group-evidence-0314：我周末去看海",user=HUMAN); await replied(9)
        await send(10,"你记得我在群里说的安排吗？private-evidence-0314",user=HUMAN,private=True); await replied(10)
        await send(11,"大肥鱼你记得我刚刚私聊说什么吗",user=HUMAN); await replied(11)
        report["mock_visible_messages"]=len(outbound); report["mock_model_requests"]=len(requests)
        report["passed"]=True
    except Exception:
        report["error"]=traceback.format_exc(); raise
    finally:
        report["shutdown"]=await asyncio.to_thread(manager.stop)
        await runner.cleanup()
        atomic_text(ROOT/"verification/fish-0314-native.json",json.dumps(report,ensure_ascii=False,indent=2))
        atomic_text(ROOT/"verification/fish-0314-native.log","\n".join(manager.logs))
        atomic_text(ROOT/"verification/fish-0314-requests.json",json.dumps(requests,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=="__main__": asyncio.run(main())
