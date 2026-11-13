"""从公开同人档案导入个人 PNG 形象图库，保留出处；不进纯净发行素材。"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import io
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen
from urllib.parse import quote

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
REPO="https://github.com/EDMOK/blue-fish-archive"
SELECTION={
 "原始立绘/deepseek_whale.png":("原始角色立绘","美图"),
 "character-art/v1/download/deepseek-full.webp":("蓝色鲸鱼娘全身立绘","美图"),
 "character-art/v1/download/deepseek-chibi.webp":("鲸鱼娘 Q 版形象","Q版"),
 "art/v1/deepseek-chibi-hug.webp":("抱抱的 Q 版鲸鱼娘","Q版"),
 "media/deepseek-duan-zuo.png":("端坐的大肥鱼","美图"),
 "media/deepseek-duzuo-fadai.png":("独坐发呆的大肥鱼","美图"),
 "media/deepseek-bao-xi-chuang-bian.png":("窗边抱膝的大肥鱼","美图"),
 "media/deepseek-bao-zhe-pangyu.png":("抱着胖鱼的大肥鱼","美图"),
 "media/deepseek-baozhe-weiba.png":("抱尾巴的大肥鱼","Q版"),
 "media/deepseek-bao-xigua.png":("抱西瓜的大肥鱼","Q版"),
 "media/deepseek-bao-shoubing.png":("抱游戏手柄的大肥鱼","Q版"),
 "media/deepseek-bao-tou-wei-qu.png":("抱头委屈的大肥鱼","Q版"),
 "media/deepseek-bei-bao-chu-men.png":("背包出门的大肥鱼","Q版"),
 "media/deepseek-chashou-shengqi.png":("叉手生气的大肥鱼","Q版"),
 "media/deepseek-chayao-gusai.png":("叉腰鼓腮的大肥鱼","Q版"),
 "media/deepseek-chi-bai-fan.png":("吃白饭的大肥鱼","Q版"),
 "media/deepseek-dafeiyu-zuodezhu.png":("坐得住的大肥鱼","Q版"),
 "media/deepseek-fudu-daxiao.png":("大笑的大肥鱼","Q版"),
 "media/deepseek-fuduizhengshui.png":("犯困的鲸鱼娘","Q版"),
 "media/deepseek-hai-jing-mai-meng.png":("海景卖萌的大肥鱼","美图"),
 "media/deepseek-huishou-gaobie.png":("挥手告别的大肥鱼","Q版"),
 "media/deepseek-jiaoao.png":("骄傲的大肥鱼","Q版"),
 "media/deepseek-jushou-dazhaohu.png":("举手打招呼的大肥鱼","Q版"),
 "media/deepseek-kan-shouji-lianhong.png":("看手机脸红的大肥鱼","Q版"),
 "media/deepseek-ken-xian-ka.png":("啃显卡的大肥鱼","Q版"),
 "media/deepseek-lanse-dafeiyu.png":("蓝色大肥鱼形象","Q版"),
 "media/deepseek-maohan.png":("冒汗的大肥鱼","Q版"),
 "media/deepseek-mo-tou.png":("摸头的大肥鱼","Q版"),
}


def fetch(url):
    with urlopen(Request(url,headers={"User-Agent":"Qianyu-personal-portrait-library"}),timeout=15) as r:data=r.read(12*1024*1024+1)
    if len(data)>12*1024*1024:raise ValueError("图片超过 12 MB")
    return data


def collect(instance):
    from PIL import Image
    from fatfish.core import atomic_text
    cached=ROOT/"research/头像来源/tree.json"
    tree=json.loads(cached.read_text(encoding="utf-8")) if cached.exists() else json.loads(fetch("https://api.github.com/repos/EDMOK/blue-fish-archive/git/trees/main?recursive=1"))
    index={i["path"]:i for i in tree["tree"]}
    home=instance/"data/portraits";home.mkdir(parents=True,exist_ok=True)
    def download(pair):
        path,(label,kind)=pair
        info=index[path]
        url="https://raw.githubusercontent.com/EDMOK/blue-fish-archive/"+tree["sha"]+"/"+quote(path,safe="/")
        data=fetch(url)
        if hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()!=info["sha"]:raise ValueError("原图 Git blob 哈希不符")
        folder=home/kind;folder.mkdir(exist_ok=True)
        name=Path(path).stem+".png";target=folder/name
        with Image.open(io.BytesIO(data)) as source:
            source.load();size=source.size
            if source.format=="PNG":target.write_bytes(data)
            else:source.convert("RGBA").save(target,format="PNG")
        return {"id":"头像/"+Path(path).stem,"file":kind+"/"+name,"description":label+"；DeepSeek 蓝色鲸鱼娘形象，PNG 可用作头像。",
                "tags":[kind,"大肥鱼","DeepSeek","蓝色","头像"],"width":size[0],"height":size[1],"source":url,
                "source_page":REPO+"/blob/"+tree["sha"]+"/"+quote(path,safe="/"),"sha256":hashlib.sha256(target.read_bytes()).hexdigest(),
                "conversion":"原生 PNG" if path.endswith(".png") else "原图 WebP 无损转存 PNG"}
    rows=[];failures=[]
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures={pool.submit(download,pair):pair[0] for pair in SELECTION.items()}
        for future in as_completed(futures):
            try:rows.append(future.result())
            except Exception as error:failures.append({"source":futures[future],"error":type(error).__name__})
    if not rows:raise RuntimeError("未成功下载任何 PNG")
    rows.sort(key=lambda i:(i["tags"][0],i["id"]))
    atomic_text(home/"catalog.json",json.dumps({"source":REPO,"commit":tree["sha"],"avatars":rows,"failed":failures},ensure_ascii=False,indent=2))
    atomic_text(home/"来源说明.md","# PNG 美图与 Q 版图库\n\n来源："+REPO+" ，展示站 https://fisharchive.cc/ 。角色原作：上善无形；DeepSeek 女仆鲸鱼娘二次设计：ZipZipPipe。按来源声明保留署名、仅非商业使用，角色二创遵循 CC BY-NC-SA 4.0；各图相关权利归原作者。\n\n原始 PNG 保留文件字节，三张 WebP 角色图无损转存 PNG；没有把 GIF 截图冒充下载的独立 PNG。逐图原网址、固定提交及哈希见 catalog.json。图库只进入个人实例，不进入纯净分享包。\n")
    return {"png_images":len(rows),"native_png":sum(i["conversion"]=="原生 PNG" for i in rows),"failed":len(failures)}


if __name__=="__main__":
    from fatfish.core import FishManager
    parser=argparse.ArgumentParser();parser.add_argument("--instance",default="my-fish");args=parser.parse_args()
    print(json.dumps(collect(FishManager(instance_name=args.instance).instance),ensure_ascii=False))
