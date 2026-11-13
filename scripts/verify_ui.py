"""在隔离浏览器里验证管理页与真实后端，不连接付费模型或真实 QQ。"""

from pathlib import Path

import json
import secrets
import zipfile

from playwright.sync_api import sync_playwright

from fatfish.core import DEFAULTS, ROOT


def main():
    output = ROOT / "verification"
    output.mkdir(exist_ok=True)
    url = json.loads((ROOT / ".runtime" / "launcher.json").read_text(encoding="utf-8"))["url"]
    report = {"checks": [], "js_errors": []}
    marker = "ui-fixture-" + secrets.token_hex(12)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda error: report["js_errors"].append(str(error)))
        page.goto(url)
        page.get_by_text("核心未启动", exact=True).wait_for()
        original = page.evaluate("api('settings')")
        try:
            page.get_by_role("button", name="启动千羽", exact=True).click()
            page.get_by_role("status").filter(has_text="填写 API Key").wait_for()
            report["checks"].append("未配置时启动明确报错，不误启动")
            page.get_by_role("button", name="✦ 人格与记忆").click()
            page.get_by_label("名字", exact=True).fill("界面验证鱼")
            page.get_by_label("知识与背景（你手工添加的）").fill(marker)
            page.get_by_role("button", name="保存人格与记忆设置").click()
            page.get_by_role("status").filter(has_text="设置已保存").wait_for()
            page.reload()
            page.get_by_role("button", name="✦ 人格与记忆").click()
            page.wait_for_function("document.querySelector('[name=nickname]').value === '界面验证鱼'")
            assert page.get_by_label("知识与背景（你手工添加的）").input_value() == marker
            report["checks"].append("人格与手工记忆保存到后端，刷新后保留")
            page.get_by_role("button", name="⇄ 连接设置").click()
            page.get_by_role("button", name="查看 NapCat 连接说明").click()
            page.locator("#connection-guide").wait_for(state="visible")
            assert len(page.locator("#ws-token").input_value()) >= 20
            report["checks"].append("QQ 接口说明与独立令牌能读取")
            page.get_by_role("button", name="▤ 数据与扩展").click()
            page.get_by_role("button", name="生成纯净发行包").click()
            page.get_by_role("status").filter(has_text="纯净发行包已生成").wait_for(timeout=40000)
            with page.expect_download() as download_info:
                page.get_by_role("button", name="下载已生成的纯净包").click()
            download = download_info.value
            target = output / "ui-downloaded-clean-release.zip"
            download.save_as(target)
            with zipfile.ZipFile(target) as archive:
                assert archive.testzip() is None
                for name in archive.namelist():
                    assert "/instances/" not in name and "/.runtime/" not in name
                    assert marker.encode() not in archive.read(name), name
            report["checks"].append("界面生成和下载纯净包成功，个人记忆未进入包")
        finally:
            restore = {k: original[k] for k in (*DEFAULTS, "persona", "manual_memory")}
            page.evaluate("body => api('settings', body)", restore)
        page.reload()
        page.get_by_text("核心未启动", exact=True).wait_for()
        for key, label in (("home", "◉ 我的鱼"), ("connect", "⇄ 连接设置"), ("persona", "✦ 人格与记忆"), ("manage", "▤ 数据与扩展"), ("logs", "≋ 运行记录")):
            page.get_by_role("button", name=label).click()
            assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
            page.screenshot(path=str(output / f"ui-{key}.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.get_by_role("button", name="✦ 人格与记忆").click()
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
        page.screenshot(path=str(output / "ui-mobile.png"), full_page=True)
        report["checks"].append("五个页面与窄屏布局无横向溢出")
        assert not report["js_errors"], report["js_errors"]
        browser.close()
    (output / "ui-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

