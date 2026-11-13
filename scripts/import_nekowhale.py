"""从作者公开端点导入本实例表情；不安装/运行 DSH 或第三方脚本，不进入发行模板。"""
import argparse
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
META = "https://raw.githubusercontent.com/Loping151/dsh-nekowhale-stickers/main/meta/nekowhale.json"
LICENSE = "https://raw.githubusercontent.com/Loping151/dsh-nekowhale-stickers/main/LICENSE-ASSETS"
SITE = "https://kiriyuki.com"


def fetch(url, max_bytes=5*1024*1024):
    with urlopen(Request(url, headers={"User-Agent":"Qianyu-personal-sticker-import/1.0", "Referer":SITE+"/"}), timeout=15) as response:
        data = response.read(max_bytes+1)
    if len(data)>max_bytes:
        raise ValueError("下载超过大小上限")
    return data


def seed(instance, catalog):
    os.environ["MAIBOT_INSTANCE_DIR"] = str(instance)
    os.environ["MAIBOT_INITIALIZE_ONLY"] = "1"
    from sqlmodel import select
    from src.common.database.database import get_db_session
    from src.common.database.database_model import Images, ImageType
    count = 0
    with get_db_session() as session:
        for item in catalog["stickers"]:
            path = instance / "data/emoji" / item["file"]
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            existing = session.exec(select(Images).where(Images.image_hash == digest, Images.image_type == ImageType.EMOJI)).first()
            if existing:
                continue
            # 直接保留来源的已标注情绪/画面，不为了导入而重复调用付费视觉模型。
            row = Images(image_hash=digest, image_type=ImageType.EMOJI,
                         full_path=path.relative_to(instance).as_posix(),
                         description=",".join(item["tags"]+[item["description"]]),
                         is_registered=True, is_banned=False, no_file_flag=False,
                         vlm_processed=True, register_time=dt.datetime.now())
            session.add(row)
            count += 1
    return count


def collect(instance, count=64):
    from PIL import Image
    from fatfish.core import atomic_text, tcp_open
    if tcp_open("127.0.0.1",18001):
        raise RuntimeError("请先停止核心，避免与原生表情管理同时导入")
    home = instance / "data/emoji"
    origin = home / "来源说明"
    origin.mkdir(parents=True, exist_ok=True)
    # 已读取的公开元数据可复用，媒体仍从作者站点获取，校验清单哈希。
    cached = ROOT / "research/表情包来源/nekowhale.json"
    meta_bytes = cached.read_bytes() if cached.is_file() else fetch(META)
    meta = json.loads(meta_bytes)
    manifest = json.loads(fetch(SITE+"/api/kit/nekowhale"))
    (origin / "作者标注.json").write_bytes(meta_bytes)
    (origin / "下载清单.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    license_cache = ROOT / "research/表情包来源/LICENSE-ASSETS.txt"
    (origin / "LICENSE-ASSETS.txt").write_bytes(license_cache.read_bytes() if license_cache.exists() else fetch(LICENSE))
    metadata = {item["id"]:item for item in meta["stickers"]}
    groups = defaultdict(deque)
    for item in manifest["items"]:
        annotation = metadata.get(item["id"])
        if item["pack"] != "大肥鱼" or not annotation or item.get("bytes",0)>5*1024*1024:
            continue
        if any(word in " ".join(annotation.get("tags",[]))+annotation.get("use","") for word in ("舌吻","脱衣","色情","性行为")):
            continue
        groups[annotation["emotion"]].append(item)
    choices=[]
    while groups and len(choices)<count:
        for key in list(groups):
            if len(choices)>=count:break
            choices.append(groups[key].popleft())
            if not groups[key]:del groups[key]
    dest = home / "nekowhale"
    dest.mkdir(exist_ok=True)
    def download(item):
        url=SITE+manifest["gif_base"]+"/"+quote(item["pack"],safe="")+"/"+quote(item["file"],safe="")+"?h="+item["hash"]
        name=hashlib.sha256(item["id"].encode()).hexdigest()[:16]+".gif"
        path=dest/name
        data=path.read_bytes() if path.exists() else fetch(url)
        if hashlib.sha1(data).hexdigest()[:12]!=item["hash"]:
            raise ValueError("作者清单哈希不符")
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        if not path.exists():path.write_bytes(data)
        a=metadata[item["id"]]
        return {"id":item["id"],"file":"nekowhale/"+name,"sha256":hashlib.sha256(data).hexdigest(),
                "description":a.get("use","")+"；"+a.get("desc",""),
                "tags":[a["emotion"],*a.get("tags",[])],"source":url,
                "author":"可以叫我云大人/雾雪", "author_site":SITE,
                "description_source":META}
    results=[]; failures=[]
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures={pool.submit(download,item):item for item in choices}
        for future in as_completed(futures):
            try:results.append(future.result())
            except Exception as error:failures.append({"id":futures[future]["id"],"error":type(error).__name__})
    results.sort(key=lambda item:item["id"])
    if not results:raise RuntimeError("没有成功获取任何表情，请稍后手动重试")
    catalog={"source":"https://github.com/Loping151/dsh-nekowhale-stickers", "author":meta["attribution"],
             "assets_usage":"仅本实例非商业使用，保留作者链接；不放进纯净发行包", "stickers":results,"failed":failures}
    atomic_text(home / "catalog.json",json.dumps(catalog,ensure_ascii=False,indent=2))
    atomic_text(origin / "来源与用途.md","# 初始表情图库\n\n作者：可以叫我云大人/雾雪。https://space.bilibili.com/103739 ，https://kiriyuki.com 。\n\n元数据：https://github.com/Loping151/dsh-nekowhale-stickers 。标注 CC BY-NC 4.0，图片按作者说明仅非商业分享并保留署名。原始动画保留，未执行第三方插件。详见 LICENSE-ASSETS.txt。\n\n这些是表情，不是千鱼的真实经历；库内作者标注直接作为描述导入，未调用模型冒充识别结果。\n")
    registered=seed(instance,catalog)
    return {"downloaded":len(results),"registered":registered,"failed":len(failures),"root":str(home)}


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--count",type=int,default=64)
    parser.add_argument("--instance",default="my-fish")
    args=parser.parse_args()
    if not 1<=args.count<=128 or not args.instance.replace("-","").replace("_","").isalnum():
        parser.error("实例名称无效，或数量不在 1–128 范围")
    print(json.dumps(collect(ROOT/"instances"/args.instance,args.count),ensure_ascii=False))
