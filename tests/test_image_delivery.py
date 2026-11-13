import base64
import importlib.util
import json
import logging
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from PIL import Image
from fatfish.core import ROOT, atomic_text
from fatfish.reply_guard import clean_reply


class ImageDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="qianyu-image-delivery-")
        self.instance=Path(self.temp.name)/"fish"
        dest=self.instance/"plugins/social"
        shutil.copytree(ROOT/"components/qianyu-social",dest)
        name="image_delivery_fixture_"+str(id(self))
        spec=importlib.util.spec_from_file_location(name,dest/"plugin.py",submodule_search_locations=[str(dest)])
        module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
        self.plugin=module.create_plugin();self.sent=[];self.receipt=True
        async def send(data,stream,**kwargs):
            self.sent.append((base64.b64decode(data),stream,kwargs))
            return {"sent":self.receipt,"message_id":"fixture-id" if self.receipt else None}
        self.plugin._ctx=SimpleNamespace(logger=logging.getLogger("fixture"),send=SimpleNamespace(emoji=send))
        home=self.instance/"data/emoji";home.mkdir(parents=True)
        Image.new("RGB",(32,32),"blue").save(home/"heart.png")
        atomic_text(home/"catalog.json",json.dumps({"stickers":[{"id":"大肥鱼/16N08_给你心心","file":"heart.png","description":"爱心","tags":["爱心"]}]}))
        await self.plugin.on_load()

    async def asyncTearDown(self):
        await self.plugin.on_unload();self.temp.cleanup()

    async def test_screenshot_markup_sends_image_and_removes_html(self):
        result=await self.plugin.deliver_image_marker(response='<img src="https://qianyu.example/sticker/16N08_给你心心.png">心给了',session_id="fixture")
        self.assertEqual(result["modified_kwargs"]["response"],"心给了")
        self.assertEqual(len(self.sent),1)
        self.assertTrue(self.sent[0][0].startswith(b"\x89PNG"))
        self.assertTrue(self.sent[0][2]["return_details"])

    async def test_failed_receipt_never_claims_success(self):
        self.receipt=False
        result=await self.plugin.deliver_image_marker(response='<img src="https://qianyu.example/sticker/16N08_给你心心.png">发好了',session_id="fixture")
        self.assertIn("没发成功",result["modified_kwargs"]["response"])

    async def test_unknown_reference_is_not_downloaded_or_sent(self):
        result=await self.plugin.deliver_image_marker(response='<img src="http://127.0.0.1/secret-not-in-library.png">发好了',session_id="fixture")
        self.assertEqual(self.sent,[])
        self.assertIn("没发成功",result["modified_kwargs"]["response"])

    def test_wire_guard_and_tools_visibility(self):
        for text in ['<img src="https://qianyu.example/a.png">','![心](https://qianyu.example/a.png)','[CQ:image,file=anything]','https://qianyu.example/a.png']:
            cleaned,changed=clean_reply(text)
            self.assertTrue(changed);self.assertNotIn("qianyu.example",cleaned)
        self.assertEqual(clean_reply("普通文字"),("普通文字",False))
        for method in [self.plugin.gallery,self.plugin.sticker]:
            self.assertEqual(method.__maibot_component_info__.metadata["visibility"],"visible")
