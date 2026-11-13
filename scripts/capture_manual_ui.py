"""只用空白隔离实例截取手册配图，不启动 QQ 或模型。"""
from pathlib import Path
import threading

from playwright.sync_api import sync_playwright

from fatfish.core import ROOT, FishManager
from fatfish.server import LocalServer


def main():
    manager = FishManager(instance_name="manual-fixture")
    manager.initialize()
    manager.save({"nickname": "千羽", "group_scope": "selected", "groups": [],
                  "private_scope": "off", "group_reply_frequency": 0.5})
    server = LocalServer(("127.0.0.1", 0), manager)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    output = ROOT / "templates/distribution/manual-assets"
    output.mkdir(parents=True, exist_ok=True)
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1000, "height": 1000}, device_scale_factor=1.5)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}/#token={server.token}")
            page.wait_for_function("saved && Number.isFinite(saved.group_reply_frequency)")
            page.get_by_role("button", name="⇄ 连接设置", exact=True).click()
            page.locator("#connection-form > article").first.locator(".form-grid").screenshot(path=str(output / "模型设置.png"))
            page.get_by_role("button", name="✦ 人格与记忆", exact=True).click()
            page.locator("#participation-form").screenshot(path=str(output / "接话频率.png"))
            assert page.get_by_role("slider", name="主动接话频率").input_value() == "0.5"
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    print("已生成两张隔离实例手册配图，无真实 QQ 或模型请求。")


if __name__ == "__main__":
    main()
