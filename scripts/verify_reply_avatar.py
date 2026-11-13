"""针对表情后泄漏标签与动图空帧头像的离线回归。"""
import asyncio
import base64
import importlib.util
import io
import json
import logging
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace

from PIL import Image, ImageDraw, ImageStat
from fatfish.core import ROOT, atomic_text
from fatfish.reply_guard import clean_reply


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path,submodule_search_locations=[str(path.parent)])
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module


async def main():
    report={"checks":[],"real_qq_test_messages":0,"paid_model_test_calls":0}
    leaked='<message msg_id="1982908318" time="16:38:27"\nuser="群友">发个表情包</message>'
    assert clean_reply(leaked)==("🐟",True)
    assert clean_reply(leaked+'\n吃瓜呢。')==('吃瓜呢。',True)
    assert clean_reply('普通的 <message>Hello</message> XML 例子')[1] is False
    assert clean_reply('</message>')==('🐟',True)
    report['checks'].append('截图中的完整标签、属性跨行与孤立关闭标签被拦截；普通文字/XML保留')
    with tempfile.TemporaryDirectory(prefix='qianyu-avatar-regression-') as temp:
        instance=Path(temp)/'my-fish';home=instance/'data/emoji';home.mkdir(parents=True)
        blank=Image.new('RGBA',(100,100),(0,0,0,0));figure=blank.copy();ImageDraw.Draw(figure).ellipse((20,8,80,90),fill='blue')
        blank.save(home/'transparent-first.gif',save_all=True,append_images=[figure],duration=[100,100],disposal=2)
        atomic_text(home/'catalog.json',json.dumps({'stickers':[{'id':'fixture/探头','file':'transparent-first.gif','description':'探头','tags':['吃瓜']}]}))
        dest=instance/'plugins/qianyu-social';shutil.copytree(ROOT/'components/qianyu-social',dest)
        module=load('avatar_regression_plugin',dest/'plugin.py');plugin=module.create_plugin()
        sent=[]
        async def send(data,stream,**kwargs):sent.append((data,stream));return True
        plugin._ctx=SimpleNamespace(logger=logging.getLogger('fixture'),send=SimpleNamespace(emoji=send))
        await plugin.on_load()
        _,encoded=plugin.library.avatar('fixture/探头')
        with Image.open(io.BytesIO(base64.b64decode(encoded))) as image:
            assert sum(ImageStat.Stat(image).var)>1000
            assert image.getpixel((320,320))[2]>100
        solid=Image.new('RGB',(100,100),'#edf7ff');solid.save(home/'solid.png')
        data=json.loads((home/'catalog.json').read_text());data['stickers'].append({'id':'fixture/纯色','file':'solid.png','description':'纯色','tags':[]});atomic_text(home/'catalog.json',json.dumps(data))
        try:plugin.library.avatar('fixture/纯色');raise AssertionError('纯色头像未被拒绝')
        except ValueError:pass
        report['checks'].append('透明首帧动图选出有角色内容的帧，纯色图片拒绝上传')
        portraits=instance/'data/portraits';portraits.mkdir(parents=True);figure.save(portraits/'q.png')
        atomic_text(portraits/'catalog.json',json.dumps({'avatars':[{'id':'头像/Q版','file':'q.png','description':'蓝色Q版鱼','tags':['Q版'],'width':100,'height':100}]}))
        gallery=await plugin.gallery(kind='avatar')
        assert gallery['content_items'][0]['type']=='image'
        Image.open(io.BytesIO(base64.b64decode(gallery['content_items'][0]['data']))).verify()
        # 上游真实工具结果转换器保留终止标记和图像内容，不能只用模拟返回值宣称接通。
        from src.plugin_runtime.component_query import ComponentQueryService
        entry=SimpleNamespace(name='qianyu_sticker',plugin_id='fatfish.qianyu-social')
        result=await plugin.sticker(stream_id='fixture',sticker_id='fixture/探头')
        parsed=ComponentQueryService._parse_tool_invoke_result(entry,result)
        assert parsed.success and parsed.stop_after_execution
        parsed_gallery=ComponentQueryService._parse_tool_invoke_result(entry,gallery)
        assert parsed_gallery.content_items[0].content_type=='image'
        await plugin.sticker(stream_id='fixture',sticker_id='fixture/探头');assert len(sent)==1
        report['checks'].append('真实工具结果转换保留发送后终止标记；去重不再发图；PNG预览作为原生多模态工具内容交给模型')
        style_dir=instance/'plugins/qianyu-style';shutil.copytree(ROOT/'components/qianyu-style',style_dir)
        style=load('reply_guard_fixture',style_dir/'plugin.py').create_plugin();style._ctx=SimpleNamespace(logger=logging.getLogger('fixture'))
        cleaned=await style.guard_reply(response=leaked,session_id='fixture',enable_splitter=True,enable_chinese_typo=True)
        assert '<message' not in cleaned['modified_kwargs']['response']
        assert not cleaned['modified_kwargs']['enable_splitter']
        blocked=await style.guard_wire(message={'raw_message':[{'type':'text','data':leaked}]})
        assert blocked['action']=='abort'
        allowed=await style.guard_wire(message={'raw_message':[{'type':'emoji','binary_data_base64':'fixture'}]})
        assert allowed['action']=='continue'
        report['checks'].append('真实SDK Hook在拆句前过滤，发送前再次阻断，真实图片段放行')
        await plugin.on_unload()
    (ROOT/'verification/reply-avatar-regression.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':asyncio.run(main())
