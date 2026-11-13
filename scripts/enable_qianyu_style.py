"""启用通用千鱼风格模板；先停止核心，不访问模型与 QQ。"""
from pathlib import Path
import argparse
import datetime as dt
import shutil
import zipfile

from fatfish.core import ROOT, FishManager, tcp_open
from fatfish.layout import personal_home


def enable(instance_name="my-fish"):
    if tcp_open("127.0.0.1", 18001):
        raise ValueError("请先在页面停止核心，再启用风格包")
    manager = FishManager(instance_name=instance_name)
    target = manager.instance / "persona" / "style-pack"
    backup = personal_home(ROOT) / "备份" / ("before-qianyu-style-" + instance_name + "-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S") + ".zip")
    backup.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(backup, "w", zipfile.ZIP_DEFLATED) as archive:
        for relative in ("fatfish.json", "config/bot_config.toml", "config/model_config.toml", "persona/identity.md", "memory/manual.md"):
            path = manager.instance / relative
            if path.is_file():
                archive.write(path, relative)
        if target.exists():
            for path in target.rglob("*"):
                if path.is_file():
                    archive.write(path, str(path.relative_to(manager.instance)))
    manager.initialize()
    shutil.copytree(ROOT / "templates" / "style-packs" / "qianyu-tieba", target, dirs_exist_ok=True)
    # 使用现有设置，不覆盖用户自己录入的人格、知识、密钥和接入范围。
    current = manager.settings()
    manager.save({"nickname": "千鱼" if current["nickname"] == "大肥鱼" else current["nickname"]})
    return backup


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", default="my-fish")
    args = parser.parse_args()
    print("千鱼风格已启用；个人设置备份：" + str(enable(args.instance)))
