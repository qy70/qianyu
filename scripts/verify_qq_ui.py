"""只替换浏览器测试页的状态响应，验证扫码弹窗；不操作真实账号。"""
import base64
import io
import json

import qrcode
from qrcode.image.svg import SvgPathImage
from playwright.sync_api import sync_playwright
from fatfish.core import ROOT


def main():
    url = json.loads((ROOT / ".runtime/launcher.json").read_text(encoding="utf-8"))["url"]
    report = {"mode": "mock status in isolated browser", "checks": [], "js_errors": []}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1240, "height": 900})
        page.on("pageerror", lambda e: report["js_errors"].append(str(e)))
        page.goto(url)
        original = page.evaluate("api('status')")
        stream = io.BytesIO()
        qrcode.make("https://example.invalid/fatfish-ui-fixture", image_factory=SvgPathImage).save(stream)
        qr = "data:image/svg+xml;base64," + base64.b64encode(stream.getvalue()).decode()
        state = {"phase": "waiting_qr", "message": "界面验证二维码，请勿扫码", "qr": qr, "account": "", "progress": 100, "running": True, "installed": True}
        page.route("**/api/status", lambda route: route.fulfill(json={**original, "qq_tool": state}))
        page.reload()
        page.locator("#qq-dialog[open]").wait_for()
        page.wait_for_function("document.querySelector('#qq-qr').complete && document.querySelector('#qq-qr').naturalWidth > 0")
        page.screenshot(path=str(ROOT / "verification/ui-qq-mock.png"))
        page.locator("#close-qq").click()
        page.evaluate("refresh()")
        assert not page.locator("#qq-dialog").evaluate("e=>e.open")
        page.locator("#show-qq").click()
        page.locator("#qq-dialog[open]").wait_for()
        report["checks"].append("二维码自动弹出、实际渲染、关闭不反复弹出、可主动重开")
        state.update(phase="confirming", message="等待手机确认（模拟）")
        page.evaluate("refresh()")
        assert "等待手机确认" in page.locator("#qq-dialog-detail").inner_text()
        state.update(phase="online", message="QQ 已登录（模拟）", account="1234567", qr="")
        page.evaluate("refresh()")
        assert not page.locator("#qq-dialog").evaluate("e=>e.open")
        page.get_by_role("button", name="⇄ 连接设置").click()
        page.locator("#use-login-account").click()
        assert page.locator("[name=qq_account]").input_value() == "1234567"
        report["checks"].append("确认与已登录状态展示，登录成功自动收起，已登录账号可填入表单但未自动保存")
        state.update(phase="waiting_qr", message="重新登录（模拟）", account="", qr=qr)
        page.evaluate("refresh()")
        page.locator("#qq-dialog[open]").wait_for()
        page.set_viewport_size({"width": 390, "height": 844})
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
        rect = page.locator("#qq-dialog").bounding_box()
        assert rect["x"] >= 0 and rect["x"] + rect["width"] <= 390
        page.screenshot(path=str(ROOT / "verification/ui-qq-mock-mobile.png"))
        report["checks"].append("掉线后重新提示扫码，窄屏弹窗完整可见")
        assert not report["js_errors"], report["js_errors"]
        browser.close()
    (ROOT / "verification/qq-ui-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
