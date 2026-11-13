"""本轮隔离验证：真实图片请求结构、配置持久化与社交插件；外部接口全用本机模拟。"""
import asyncio
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
import logging
import os
from pathlib import Path
import shutil
import sys
import threading
from types import SimpleNamespace

from PIL import Image
import tomlkit

from fatfish.core import ROOT, FishManager, atomic_text


async def main():
    manager = FishManager(instance_name="vision-social-fixture")
    os.environ["MAIBOT_INSTANCE_DIR"] = str(manager.instance)
    os.environ["MAIBOT_INITIALIZE_ONLY"] = "1"
    manager.initialize()
    requests=[]
    class MockModel(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            data=json.dumps({"id":"fixture","object":"chat.completion","created":1,"model":"deepseek-flash","choices":[{"index":0,"message":{"role":"assistant","content":"本机模拟图片描述"},"finish_reason":"stop"}]}).encode()
            self.send_response(200);self.send_header("Content-Type","application/json");self.send_header("Content-Length",str(len(data)));self.end_headers();self.wfile.write(data)
    mock = ThreadingHTTPServer(("127.0.0.1",0),MockModel)
    thread = threading.Thread(target=mock.serve_forever,daemon=True);thread.start()
    checks=[]
    try:
        manager.save({"api_base":f"http://127.0.0.1:{mock.server_port}/v1","api_key":"fixture-not-a-real-key","model":"deepseek-flash","qq_account":"100000001","group_scope":"selected","groups":["123456789"],"vision_enabled":True,"collect_emoji":True})
        model_path=manager.instance/"config/model_config.toml"
        first=tomlkit.parse(model_path.read_text(encoding="utf-8"))
        assert first["model_task_config"]["vlm"]["model_list"]==["fatfish-chat"]
        assert next(m for m in first["models"] if m["name"]=="fatfish-chat")["visual"] is True
        manager.save({"nickname":"隔离验证鱼"})
        assert tomlkit.parse(model_path.read_text(encoding="utf-8"))["model_task_config"]["vlm"]["model_list"]==["fatfish-chat"]
        checks.append("视觉标记和视觉任务启用，普通保存后仍保留")
        from src.config.config import config_manager
        config_manager.initialize()
        from src.services.llm_service import LLMServiceClient
        stream=io.BytesIO();Image.new("RGB",(16,16),"green").save(stream,format="PNG")
        encoded=base64.b64encode(stream.getvalue()).decode()
        response=await LLMServiceClient(task_name="vlm",request_type="image").generate_response_for_image("描述图像",encoded,"png")
        assert response.response=="本机模拟图片描述"
        parts=[part for message in requests[-1]["messages"] if message["role"]=="user" for part in message["content"]]
        images=[p["image_url"]["url"] for p in parts if p.get("type")=="image_url"]
        assert images and images[0].startswith("data:image/")
        with Image.open(io.BytesIO(base64.b64decode(images[0].split(",",1)[1]))) as sent:
            red, green, blue=sent.convert("RGB").getpixel((0,0))
            assert green>red+40 and green>blue+40
        checks.append("上游真实 LLM 图片通路向本机模拟接口发送 user 图片块及可解码的正确图像")
        # Validate native declarations and tools; mock the QQ send/profile endpoints.
        from src.plugin_runtime.runner.manifest_validator import PluginManifest
        plugin_home=manager.instance/"plugins/qianyu-social"
        PluginManifest.model_validate(json.loads((plugin_home/"_manifest.json").read_text(encoding="utf-8")))
        spec=importlib.util.spec_from_file_location("qianyu_social_fixture",plugin_home/"plugin.py",submodule_search_locations=[str(plugin_home)])
        module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
        plugin=module.create_plugin()
        calls=[];mode={"fail":False,"wrong_login":False}
        async def api(name,**kwargs):
            calls.append((name,kwargs))
            if "get_login_info" in name:return {"user_id":"100000002" if mode["wrong_login"] else "100000001"}
            return {"status":"failed","retcode":1} if mode["fail"] else {"status":"ok","retcode":0}
        async def send(data,chat,**kwargs):calls.append(("send",chat));return True
        plugin._ctx=SimpleNamespace(logger=logging.getLogger("fixture"),api=SimpleNamespace(call=api),send=SimpleNamespace(emoji=send))
        await plugin.on_load()
        target=manager.instance/"data/emoji";target.mkdir(parents=True,exist_ok=True)
        from PIL import ImageDraw
        avatar_image=Image.new("RGB",(80,80),"white");ImageDraw.Draw(avatar_image).ellipse((12,10,68,72),fill="blue");avatar_image.save(target/"fixture.png")
        atomic_text(target/"catalog.json",json.dumps({"stickers":[{"id":"fixture/开心","file":"fixture.png","description":"开心的蓝鱼","tags":["开心"]}]}))
        assert "fixture/开心" in (await plugin.gallery("开心"))["content"]
        assert (await plugin.sticker(stream_id="fixture-chat",sticker_id="fixture/开心"))["stop_after_execution"]
        assert (await plugin.sticker(stream_id="fixture-chat",sticker_id="fixture/开心"))["stop_after_execution"]
        assert sum(name=="send" for name,args in calls)==1
        assert not (await plugin.profile(nickname="千鱼",reason="喜欢"))[0]
        home=manager.instance/"social"
        policy={"enabled":True,"owner_qq":"123456789","account_qq":"100000001","cooldown_hours":24}
        atomic_text(home/"preferences.json",json.dumps(policy))
        mode["wrong_login"]=True
        assert not (await plugin.profile(nickname="千鱼",reason="喜欢"))[0]
        mode["wrong_login"]=False;mode["fail"]=True
        assert not (await plugin.profile(nickname="千鱼",reason="喜欢"))[0]
        atomic_text(home/"profile-state.json","{}")
        mode["fail"]=False
        assert (await plugin.profile(nickname="千鱼·发呆",avatar_id="fixture/开心",reason="喜欢安静的样子"))[0]
        assert not (await plugin.profile(nickname="千鱼·又换了",reason="测试"))[0]
        assert sum("set_qq_avatar" in name for name, args in calls)==1
        history=[json.loads(s) for s in (home/"profile-history.jsonl").read_text(encoding="utf-8").splitlines()]
        assert not any(o["success"] for o in history[0]["outcomes"])
        await plugin.on_unload()
        checks.append("原生插件声明通过；真图片数据交给模拟发送；未授权/错账号被拒，失败不冒充成功，成功后有冷却和审计")
        manager.save({"vision_enabled":False})
        assert not tomlkit.parse(model_path.read_text(encoding="utf-8"))["model_task_config"]["vlm"]["model_list"]
        manager.save({"vision_enabled":True})
        checks.append("视觉功能可关闭与重新启用")
    finally:
        mock.shutdown();mock.server_close();thread.join(timeout=3)
    report={"checks":checks,"local_mock_image_requests":len(requests),"real_model_test_calls":0,"real_qq_test_messages":0,"real_profile_test_changes":0}
    (ROOT/"verification/social-vision.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False))


if __name__=="__main__":asyncio.run(main())
