"""仅监听本机的个人管理页，所有数据接口需要本次启动的随机凭据。"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import argparse
import atexit
import json
import mimetypes
import os
import secrets
import threading
import webbrowser

from fatfish.core import ROOT, FishManager, atomic_text
from fatfish import __version__
from fatfish.qqtool import QQTool
from fatfish.layout import folders, library_info, release_path, share_dir


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address, manager):
        self.manager = manager
        self.qq = QQTool(manager)
        self.on_quit = None
        self.token = secrets.token_urlsafe(32)
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server: LocalServer

    def log_message(self, *_):
        pass

    def reply(self, code, data, content_type="application/json; charset=utf-8"):
        content = json.dumps(data, ensure_ascii=False).encode() if isinstance(data, (dict, list)) else data
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(content)

    def authorized(self):
        port = self.server.server_port
        if self.headers.get("Host") not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
            self.reply(403, {"error": "主机地址无效"})
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}:
            self.reply(403, {"error": "不允许跨站访问"})
            return False
        if not secrets.compare_digest(self.headers.get("X-Fatfish-Token", ""), self.server.token):
            self.reply(401, {"error": "请通过桌面启动入口重新打开管理页"})
            return False
        return True

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/health":
            return self.reply(200, {"app": "fatfish", "version": __version__})
        static = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}
        # 仅公开固定的通用主题素材，不将个人图库作为静态目录暴露。
        for asset in ("ocean-room.webp", "fish-wave.webp", "fish-hug.webp", "fish-chibi.webp", "qianyu.ico", "qianyu.png", "sources.json", "ATTRIBUTION.md"):
            static["/assets/" + asset] = "assets/" + asset
        static["/favicon.ico"] = "assets/qianyu.ico"
        if path in static:
            file = ROOT / "fatfish" / "web" / static[path]
            return self.reply(200, file.read_bytes(), (mimetypes.guess_type(file.name)[0] or "text/plain") + "; charset=utf-8")
        if not self.authorized():
            return
        manager = self.server.manager
        try:
            if path == "/api/status":
                result = manager.status()
                result["qq_tool"] = self.server.qq.snapshot()
            elif path == "/api/settings":
                result = manager.settings()
            elif path == "/api/logs":
                result = {"lines": list(manager.logs)}
            elif path == "/api/connection":
                result = manager.connection_info()
            elif path == "/api/qq-friends":
                result = manager.qq_friends()
            elif path == "/api/advanced":
                result = manager.advanced_info()
            elif path == "/api/library":
                result = library_info(manager.root, manager.instance)
            elif path == "/api/fish-identities":
                result = manager.fish_identities()
            elif path == "/api/download-release":
                file = release_path(manager.root)
                if not file.is_file():
                    raise ValueError("请先生成纯净发行包")
                return self.reply(200, file.read_bytes(), "application/zip")
            else:
                return self.reply(404, {"error": "没有这个入口"})
            self.reply(200, result)
        except Exception as error:
            self.reply(400, {"error": manager.redact(str(error))})

    def do_POST(self):
        if not self.authorized():
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 100000:
                return self.reply(413, {"error": "提交内容过大"})
            data = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(data, dict):
                raise ValueError("提交内容必须是一个对象")
            manager = self.server.manager
            path = urlsplit(self.path).path
            actions = {
                "/api/settings": lambda: self.save_settings(data),
                "/api/participation": lambda: manager.save_group_reply_frequency(data),
                "/api/fish-identities": lambda: manager.correct_fish_identity(data),
                "/api/start": self.start_core,
                "/api/stop": manager.stop,
                "/api/test-api": manager.test_api,
                "/api/check-qq": manager.check_qq,
                "/api/backup": self.backup,
                "/api/open-qq-folder": manager.open_qq_folder,
                "/api/qq-start": self.server.qq.ensure,
                "/api/qq-stop": self.stop_qq,
                "/api/qq-refresh": self.server.qq.refresh_qr,
                "/api/open-library-folder": lambda: self.open_library_folder(data),
            }
            if path == "/api/package":
                from scripts.build_release import build
                file = build(manager.root)
                return self.reply(200, {"message": "纯净发行包已生成，不包含个人配置和记忆", "filename": file.name})
            if path == "/api/quit":
                result = manager.stop()
                self.server.qq.stop()
                self.reply(200, {"message": "核心与管理台已退出，重新使用请双击启动入口"})
                if self.server.on_quit:
                    threading.Thread(target=self.server.on_quit, daemon=True).start()
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if path not in actions:
                return self.reply(404, {"error": "没有这个操作"})
            result = actions[path]()
            self.reply(200, result)
        except Exception as error:
            self.reply(400, {"error": self.server.manager.redact(str(error))})

    def save_settings(self, data):
        before = self.server.manager.settings(private=True)
        result = self.server.manager.save(data)
        after = self.server.manager.settings(private=True)
        if self.server.qq.snapshot()["running"] and any(before[k] != after[k] for k in ("qq_account", "qq_host", "qq_port", "qq_token")):
            self.server.qq.stop()
            self.server.qq.ensure()
        return result

    def open_library_folder(self, data):
        manager = self.server.manager
        choices = {key: value[1] for key, value in folders(manager.root, manager.instance).items()}
        choices["share"] = share_dir(manager.root)
        key = data.get("key")
        if key not in choices:
            raise ValueError("请选择资料页中列出的文件夹")
        target = choices[key]
        target.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            raise ValueError("当前环境请使用显示的路径打开文件夹")
        os.startfile(target)
        return {"message": "已打开文件夹", "path": str(target)}

    def start_core(self):
        manager = self.server.manager
        data = manager.settings()
        if manager.running() or not (data["has_api_key"] and data["qq_account"] and manager.has_chat_scope(data)):
            return manager.start()
        manager.check_qq()
        return manager.start()

    def stop_qq(self):
        self.server.manager.stop()
        return self.server.qq.stop()

    def backup(self):
        if self.server.qq.snapshot()["running"]:
            raise ValueError("请先停止核心和 QQ 组件再备份，保证登录资料与记忆状态一致")
        return {"message": "备份完成，含个人配置与密钥，请妥善保管", "path": str(self.server.manager.backup())}


def main():
    parser = argparse.ArgumentParser(description="千鱼本地管理台")
    parser.add_argument("--port", type=int, default=17860)
    parser.add_argument("--instance", default="my-fish")
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    manager = FishManager(instance_name=args.instance)
    manager.initialize()
    server = LocalServer(("127.0.0.1", args.port), manager)
    url = f"http://127.0.0.1:{server.server_port}/#token={server.token}"
    atomic_text(ROOT / ".runtime" / "launcher.json", json.dumps({"url": url, "port": server.server_port}, ensure_ascii=False))
    atexit.register(manager.stop)
    print(f"千鱼管理台已启动：http://127.0.0.1:{server.server_port}", flush=True)
    if not args.no_open:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        manager.stop()
        server.qq.stop()
        server.server_close()


if __name__ == "__main__":
    main()
