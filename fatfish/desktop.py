"""原生桌面窗口；关闭主窗口时回收本应用的核心和 QQ 子进程。"""

import argparse
import ctypes
import hashlib
import json
import os
import threading

from fatfish.core import ROOT, FishManager, atomic_text
from fatfish.layout import personal_home
from fatfish.server import LocalServer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", default="my-fish")
    parser.add_argument("--no-qq", action="store_true", help="仅验证桌面界面，不运行真实 QQ")
    parser.add_argument("--resume-core", action="store_true", help="升级后恢复先前运行的核心")
    args = parser.parse_args()
    if (personal_home(ROOT) / ".qianyu-update.json").is_file():
        raise RuntimeError("千鱼正在升级，请等待安装完成后再打开。")
    import webview
    identity = hashlib.sha256((str(ROOT) + args.instance).encode()).hexdigest()[:24]
    mutex = None
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.restype = ctypes.c_void_p
        mutex = kernel.CreateMutexW(None, False, "Local\\FatfishDesktop-" + identity)
        if ctypes.get_last_error() == 183:
            signal_file = ROOT / ".runtime" / ("focus-" + identity)
            atomic_text(signal_file, "focus")
            kernel.CloseHandle(ctypes.c_void_p(mutex))
            return
    manager = FishManager(instance_name=args.instance)
    manager.initialize()
    try:
        server = LocalServer(("127.0.0.1", 17860), manager)
    except OSError:
        raise RuntimeError("管理端口被占用，请先退出旧版千鱼管理台再重新打开桌面版") from None
    url = f"http://127.0.0.1:{server.server_port}/#token={server.token}"
    atomic_text(ROOT / ".runtime" / "launcher.json", json.dumps({"url": url, "port": server.server_port, "desktop": True, "pid": os.getpid()}))
    signal_file = ROOT / ".runtime" / ("focus-" + identity)
    signal_file.unlink(missing_ok=True)
    done = threading.Event()
    closing = threading.Event()
    if os.name == "nt":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Qianyu.Qianyu")
    window = webview.create_window("千鱼", url, width=1240, height=860,
                                   min_size=(860, 620), background_color="#e6efff")
    server.on_quit = window.destroy

    def close_workers():
        try:
            # closing 回调在 GUI 线程同步触发；JS 调用必须放到后台线程。
            window.evaluate_js("document.querySelector('#header-state').textContent='正在保存并退出，请稍候'; document.querySelectorAll('button').forEach(b=>b.disabled=true)")
            manager.stop()
            server.qq.stop()
            server.shutdown()
        finally:
            done.set()
            window.destroy()

    def on_closing():
        if done.is_set():
            return True
        if not closing.is_set():
            closing.set()
            threading.Thread(target=close_workers, daemon=True).start()
        return False

    window.events.closing += on_closing

    def background():
        if not args.no_qq:
            server.qq.ensure()
        resume = args.resume_core and not args.no_qq
        while not done.wait(0.5):
            if resume and server.qq.snapshot().get("phase") == "online":
                resume = False
                try:
                    manager.check_qq()
                    manager.start()
                except Exception as error:
                    manager.logs.append("升级后恢复核心失败，请检查连接设置：" + manager.redact(str(error)))
            if signal_file.exists():
                signal_file.unlink(missing_ok=True)
                window.restore()
                window.show()

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        webview.start(background, gui="edgechromium", private_mode=True,
                      icon=str(ROOT / "fatfish" / "web" / "assets" / "qianyu.ico"),
                      storage_path=str(manager.instance / "desktop-cache"))
    finally:
        manager.stop()
        server.qq.stop()
        server.shutdown()
        server.server_close()
        done.set()
        if mutex:
            kernel.CloseHandle(ctypes.c_void_p(mutex))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        atomic_text(ROOT / ".runtime" / "desktop-error.log", str(error))
        if os.name == "nt":
            ctypes.windll.user32.MessageBoxW(None, str(error) + "\n详情见 .runtime/desktop-error.log", "千鱼启动未完成", 16)
        raise
