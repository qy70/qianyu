from pathlib import Path
import base64
import io
import json
import random
from urllib.parse import unquote, urlsplit

from fatfish.knowledge import terms


class StickerLibrary:
    def __init__(self, instance):
        self.instance = Path(instance)
        self.home = self.instance / "data" / "emoji"
        self.recent = []

    def items(self):
        path = self.home / "catalog.json"
        if not path.is_file():
            return []
        return json.loads(path.read_text(encoding="utf-8"))["stickers"]

    def portraits(self):
        path = self.instance / "data" / "portraits" / "catalog.json"
        return json.loads(path.read_text(encoding="utf-8")).get("avatars", []) if path.is_file() else []

    def search(self, query="", limit=12, kind="sticker"):
        if kind == "sticker" and any(word in query for word in ("爱你", "爱爸", "爱老爸", "心心", "比心")):
            query += " 爱心 喜欢 送心 亲近"
        query_terms = terms(query)
        items = self.portraits() if kind == "avatar" else self.items()
        if query_terms:
            items.sort(key=lambda item: len(query_terms & terms(" ".join([item["id"], item.get("description", ""), *item.get("tags", [])]))), reverse=True)
        return [{k:item[k] for k in ("id", "description", "tags", "width", "height") if k in item} for item in items[:limit]]

    def pick(self, sticker_id="", query=""):
        items = self.items()
        if sticker_id:
            item = next((i for i in items if i["id"] == sticker_id), None)
        else:
            candidates = self.search(query, 8)
            fresh = [i for i in candidates if i["id"] not in self.recent] or candidates
            choice = random.choice(fresh) if fresh else None
            item = next((i for i in items if choice and i["id"] == choice["id"]), None)
        if not item:
            raise ValueError("没有找到表情；先用 qianyu_gallery 查看可用编号。")
        path = (self.home / item["file"]).resolve()
        if not path.is_relative_to(self.home.resolve()) or not path.is_file() or path.stat().st_size > 5*1024*1024:
            raise ValueError("表情文件缺失、超限或路径无效")
        return item, path

    def resolve_reference(self, reference):
        # 只把生成出来的图片标记映射到本地白名单，不访问或下载标记中的网址。
        name = unquote(urlsplit(str(reference)).path).replace("\\", "/").rsplit("/",1)[-1]
        stem = Path(name).stem
        return next((i["id"] for i in self.items() if stem in {Path(i["id"]).name, Path(i["file"]).stem}), None)

    def avatar(self, sticker_id):
        from PIL import Image, ImageOps, ImageStat
        item = next((i for i in self.portraits() if i["id"] == sticker_id), None)
        if item:
            home = (self.instance / "data" / "portraits").resolve()
            path = (home / item["file"]).resolve()
            if not path.is_relative_to(home) or not path.is_file() or path.stat().st_size > 12*1024*1024:
                raise ValueError("头像原图缺失、超限或路径无效")
        else:
            item, path = self.pick(sticker_id)
        with Image.open(path) as source:
            count = getattr(source, "n_frames", 1)
            indices = sorted(set(round(i*(count-1)/min(31,max(1,count-1))) for i in range(min(32,count))))
            best, best_score = None, 0
            for index in indices:
                source.seek(index)
                frame = source.convert("RGBA")
                alpha = frame.getchannel("A")
                bbox = alpha.point(lambda value: 255 if value > 32 else 0).getbbox()
                if not bbox:
                    continue
                foreground = sum(alpha.histogram()[33:]) / (frame.width*frame.height)
                thumb = Image.new("RGBA", frame.size, "#edf7ff")
                thumb.alpha_composite(frame)
                small = ImageOps.contain(thumb.convert("RGB"), (96,96))
                spread = sum(ImageStat.Stat(small).var)
                score = foreground * spread
                if spread > 80 and foreground > .025 and score > best_score:
                    best, best_score = frame.copy(), score
            if best is None:
                raise ValueError("这张图未找到非空白主体，已拒绝上传纯色头像；请改选 PNG 图库")
            # 非空的真实角色帧；只裁透明留白，不修改图库原图和原始动画。
            bbox = best.getchannel("A").getbbox()
            avatar = ImageOps.contain(best.crop(bbox), (640,640))
            canvas = Image.new("RGBA", (640, 640), "#edf7ff")
            canvas.alpha_composite(avatar, ((640-avatar.width)//2, (640-avatar.height)//2))
            stream = io.BytesIO()
            canvas.convert("RGB").save(stream, format="PNG")
        return item, base64.b64encode(stream.getvalue()).decode("ascii")

    def preview(self, items):
        from PIL import Image, ImageOps, ImageDraw
        columns = 4
        sheet = Image.new("RGB", (columns*180, ((len(items)+columns-1)//columns)*200), "#edf7ff")
        draw = ImageDraw.Draw(sheet)
        home = (self.instance / "data/portraits").resolve()
        originals = {i["id"]:i for i in self.portraits()}
        for index, item in enumerate(items):
            path = (home / originals[item["id"]]["file"]).resolve()
            if not path.is_relative_to(home):
                raise ValueError("预览图路径无效")
            with Image.open(path) as image:
                tile = ImageOps.contain(image.convert("RGBA"), (174,174))
                x, y = (index%columns)*180, (index//columns)*200
                sheet.paste(tile, (x+(180-tile.width)//2,y), tile)
                draw.text((x+8,y+180), str(index+1), fill="black")
        output = io.BytesIO();sheet.save(output,format="PNG")
        return base64.b64encode(output.getvalue()).decode("ascii")
