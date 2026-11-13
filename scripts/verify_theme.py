"""千鱼 主题的隔离实际浏览器验收，不连接真实 QQ 或模型。"""
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import json
import threading

from playwright.sync_api import sync_playwright

from fatfish.core import ROOT, FishManager
from fatfish.server import LocalServer


def main():
    manager = FishManager(instance_name="theme-fixture")
    manager.initialize()
    manager.save_group_reply_frequency({"group_reply_frequency": 0.8})
    server = LocalServer(("127.0.0.1", 0), manager)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    url = base + "/#token=" + server.token
    output = ROOT / "verification"
    output.mkdir(exist_ok=True)
    report = {"real_qq_messages": 0, "paid_model_requests": 0, "js_errors": [], "pages": [], "broken_images": []}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1240, "height": 860})
            page.on("pageerror", lambda error: report["js_errors"].append(str(error)))
            page.goto(url)
            page.wait_for_function("() => saved.group_reply_frequency === 0.8")
            assert page.title() == "千鱼"
            assert "千鱼" in page.locator(".brand").inner_text()
            assert "大肥鱼的小窝" in page.locator(".brand").inner_text()
            assert page.locator(".hero-kicker").inner_text().strip() == "大肥鱼"
            assert "大肥鱼" in page.locator("#core-detail").inner_text()
            page.wait_for_function("() => [...document.images].filter(img=>img.getAttribute('src')).every(img=>img.complete && img.naturalWidth>0)")
            for key in ("home", "connect", "persona", "library", "manage", "logs"):
                page.locator(f'.nav[data-page="{key}"]').click()
                if key == "library":
                    page.wait_for_function("() => document.querySelector('#library-summary').textContent.includes('份文件')")
                assert not page.evaluate("() => document.documentElement.scrollWidth > innerWidth"), key
                assert page.locator(f"#{key}").is_visible()
                page.screenshot(path=str(output / f"qianyu-desktop-{key}.png"), full_page=True)
                report["pages"].append(key)
            page.locator('#show-credits').click()
            assert page.locator('#credits-dialog').is_visible()
            assert page.locator('#credits-dialog h2').inner_text() == '大肥鱼'
            assert page.get_by_role('link', name='EDMOK / blue-fish-archive ↗').is_visible()
            page.locator('#close-credits').click()
            assert not page.locator('#credits-dialog').is_visible()
            report['credits_dialog'] = True
            page.locator('.nav[data-page="persona"]').click()
            page.get_by_label('名字', exact=True).fill('尚未保存的名字')
            slider = page.get_by_role('slider', name='新话题触发概率')
            slider.focus()
            slider.press('Home')
            for _ in range(25):
                slider.press('ArrowRight')
            page.get_by_role('button', name='保存新话题概率', exact=True).click()
            page.get_by_role('status').filter(has_text='新话题概率已保存').wait_for()
            assert page.get_by_label('名字', exact=True).input_value() == '尚未保存的名字'
            page.reload()
            page.wait_for_function('() => saved.group_reply_frequency === 0.25')
            page.locator('.nav[data-page="persona"]').click()
            assert slider.input_value() == '0.25'
            report['slider_saved_after_redesign'] = True
            page.get_by_label('名字', exact=True).fill('主题验证鱼')
            page.get_by_role('button', name='保存人格与记忆设置', exact=True).click()
            page.get_by_role('status').filter(has_text='设置已保存').wait_for()
            page.reload()
            page.wait_for_function("() => saved.nickname === '主题验证鱼'")
            assert manager.settings()['nickname'] == '主题验证鱼'
            report['persona_save_after_redesign'] = True
            page.locator('#show-qq').click()
            assert page.locator('#qq-dialog').is_visible()
            page.locator('#close-qq').click()
            assert not page.locator('#qq-dialog').is_visible()
            report['qq_dialog'] = True
            page.set_viewport_size({"width":1920,"height":1080})
            page.locator('.nav[data-page="home"]').click()
            assert not page.evaluate('() => document.documentElement.scrollWidth > innerWidth')
            page.screenshot(path=str(output/'qianyu-wide-home.png'), full_page=True)
            page.set_viewport_size({"width":390,"height":844})
            for key in ("home", "connect", "persona", "library", "manage", "logs"):
                page.locator(f'.nav[data-page="{key}"]').click()
                assert not page.evaluate('() => document.documentElement.scrollWidth > innerWidth'),key
                if key in {'home','persona'}:
                    page.screenshot(path=str(output/f'qianyu-mobile-{key}.png'),full_page=True)
            report['mobile_all_pages_no_horizontal_overflow'] = True
            assert not report['js_errors'],report['js_errors']
            report['broken_images'] = page.evaluate("() => [...document.images].filter(img=>img.getAttribute('src') && (!img.complete || !img.naturalWidth)).map(img=>img.getAttribute('src'))")
            assert not report['broken_images']
            report['background'] = page.evaluate("() => getComputedStyle(document.body,'::before').backgroundImage.includes('ocean-room.webp')")
            assert report['background']
            browser.close()
        for asset in ('qianyu.ico','qianyu.png','fish-hug.webp','ocean-room.webp','sources.json','ATTRIBUTION.md'):
            with urlopen(base+'/assets/'+asset,timeout=5) as response:
                assert response.status == 200 and response.read()
        try:
            urlopen(Request(base+'/assets/../instances/my-fish/fatfish.json',headers={'X-Fatfish-Token':server.token}),timeout=5)
            raise AssertionError('Static theme route exposed an unlisted file')
        except HTTPError as error:
            assert error.code == 404
        report['public_assets_whitelisted_only'] = True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        (output/'qianyu-branding-0312-ui.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
