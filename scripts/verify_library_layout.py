"""仅核对本轮文件库、原生 Hook 与页面交互；不运行真实模型或 QQ。"""
import asyncio
import importlib.util
import json
import logging
from pathlib import Path
import shutil
import sys
import tempfile
import threading
from types import SimpleNamespace
from unittest.mock import patch

from fatfish.core import ROOT, DEFAULTS, FishManager
from fatfish.knowledge import KnowledgeLibrary
from fatfish.layout import ensure_portal, personal_home
from fatfish.server import LocalServer


def main():
    report = {"checks": [], "real_model_calls": 0, "real_qq_messages": 0, "js_errors": []}
    with tempfile.TemporaryDirectory(prefix="qianyu-library-") as temporary:
        root = Path(temporary) / "千鱼纯净版" / "程序"
        root.mkdir(parents=True)
        shutil.copyfile(ROOT / "layout.json", root / "layout.json")
        (root / "templates").mkdir()
        shutil.copyfile(ROOT / "templates/资料库使用说明.md", root / "templates/资料库使用说明.md")
        manager = FishManager(root)
        ensure_portal(root, manager.instance)
        notes = manager.instance / "memory/notes"
        notes.mkdir(parents=True)
        pinned = notes / "00-核心记忆.md"
        pinned.write_text("主人喜欢简洁直接的回答。", encoding="utf-8")
        knowledge = manager.instance / "knowledge"
        long_doc = knowledge / "飞船维修.md"
        long_doc.write_text("很长的旧档案，无关的材料。\n" * 2000 + "\n飞船维修：量子扳手的编号是 QY-9876。", encoding="utf-8")
        (knowledge / "_说明.md").write_text("不应读取的说明标记", encoding="utf-8")
        (knowledge / "错误编码.txt").write_bytes(b"\xff\xfe\xff")
        library = KnowledgeLibrary(manager.instance)
        prompt = library.build("飞船维修的量子扳手是什么编号")
        assert "QY-9876" in prompt and "主人喜欢简洁" in prompt and "不应读取" not in prompt
        assert len(prompt) < 6000 and library.status()["warnings"]
        pinned.write_text("主人喜欢自然一点的回答。", encoding="utf-8")
        long_doc.unlink()
        library.refresh(force=True)
        assert "自然一点" in library.build("随便问问") and "QY-9876" not in library.build("飞船维修")
        report["checks"].append("超过页面长度的文章尾部可检索；核心记忆生效，修改/删除重读，错误编码可见")
        alias = personal_home(root) / "我的资料/03-知识库"
        assert alias.resolve() == knowledge.resolve()
        (alias / "人物设定.md").write_text("白鲸号船长的名字叫阿禾。", encoding="utf-8")
        assert (knowledge / "人物设定.md").read_text(encoding="utf-8").endswith("阿禾。")
        report["checks"].append("中文资料入口直接编辑原文件，无副本")

        # 原生插件类 + SDK 装饰器，使用隔离实例路径和模拟消息。
        plugin_home = manager.instance / "plugins/qianyu-style"
        shutil.copytree(ROOT / "components/qianyu-style", plugin_home)
        spec = importlib.util.spec_from_file_location("qianyu_library_fixture", plugin_home / "plugin.py", submodule_search_locations=[str(plugin_home)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        plugin = module.create_plugin()
        async def message(*args, **kwargs):
            return {"message": {"processed_plain_text": "白鲸号船长叫什么"}}
        plugin._ctx = SimpleNamespace(logger=logging.getLogger("fixture"), message=SimpleNamespace(get_by_id=message))
        async def hook():
            await plugin.on_load()
            assert not plugin.library.enabled()
            result = await plugin.natural_chat(session_id="fixture", reply_message_id="fixture", extra_prompt="其他扩展")
            assert result["modified_kwargs"]["extra_prompt"].startswith("其他扩展")
            assert "阿禾" in result["modified_kwargs"]["extra_prompt"]
            await plugin.on_unload()
        asyncio.run(hook())
        report["checks"].append("原生回复 Hook 注入资料并保留其他扩展；风格关闭时资料仍可用")

        manager.settings = lambda private=False: dict(DEFAULTS, persona="隔离人格", manual_memory="", has_api_key=False)
        manager.status = lambda: dict(running=False, ready=False, last_exit=None, engine_version="1.3.19", api_configured=False, group_scope="all", private_scope="off", groups=0, users=0, instance=str(manager.instance), memory_enabled=True)
        server = LocalServer(("127.0.0.1", 0), manager)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            from playwright.sync_api import sync_playwright
            with patch("fatfish.server.os.startfile") as open_folder, sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="msedge", headless=True)
                page = browser.new_page(viewport={"width": 1360, "height": 1000})
                page.on("pageerror", lambda error: report["js_errors"].append(str(error)))
                page.goto(f"http://127.0.0.1:{server.server_port}/#token={server.token}")
                page.get_by_role("button", name="▧ 我的资料库").click()
                page.locator("#library-files").get_by_text("人物设定.md", exact=False).wait_for()
                assert page.locator("#library-warnings").inner_text()
                page.locator("#library-folders article").filter(has_text="03-知识库").get_by_role("button").click()
                page.get_by_role("status").filter(has_text="已打开文件夹").wait_for()
                assert open_folder.call_args.args[0] == knowledge
                # 保证只能打开固定目录。
                bad = page.evaluate("api('open-library-folder',{key:'../../outside'}).then(()=>false).catch(()=>true)")
                assert bad
                page.get_by_role("button", name="刷新资料列表").click()
                assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
                page.screenshot(path=str(ROOT / "verification/library-page.png"), full_page=True)
                page.set_viewport_size({"width": 390, "height": 844})
                assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
                browser.close()
                assert not report["js_errors"]
            report["checks"].append("真实本地页面：导航、资料列表、读取警告、打开指定目录、窄屏交互通过；无 JS 错误")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
    (ROOT / "verification/library-layout.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
