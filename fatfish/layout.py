"""可读的个人目录入口；真实数据只有 instances 中的一份。"""
from pathlib import Path
import json
import os
import subprocess

from fatfish import __version__


def personal_home(root: Path) -> Path:
    path = root / "layout.json"
    if not path.is_file():
        return root
    layout = json.loads(path.read_text(encoding="utf-8-sig"))
    return root if layout.get("layout") == "flat-install" else root.parent


def share_dir(root: Path) -> Path:
    home = personal_home(root)
    return home.parent / "02-纯净分享版" if home.name == "01-我的千鱼" else home / "导出分享版"


def release_path(root: Path) -> Path:
    return share_dir(root) / f"千鱼-{__version__}-纯净版.zip"


def folders(root: Path, instance: Path) -> dict:
    return {
        "persona": ("01-人格", instance / "persona", "identity.md 是基础人格；修改后重启核心。"),
        "memory": ("02-手写记忆", instance / "memory", "manual.md 是短背景；notes 中的 00-核心记忆.md 每次附带，其他 Markdown/TXT 按相关性读取。"),
        "knowledge": ("03-知识库", instance / "knowledge", "放 UTF-8 的 .md / .txt，可建子文件夹；按当前聊天选取片段，通常 5 秒内更新。"),
        "style": ("04-说话风格", instance / "persona" / "style-pack", "可选的自定义语气与范例；新版纯净实例默认为空。人格与回复风格文件修改后重启核心。"),
        "automatic": ("05-自动记忆", instance / "data" / "a-memorix", "聊天自动积累的记忆；不要手改数据库，通过完整记忆管理查看。聊天历史另在 data/MaiBot.db。"),
        "account": ("06-账号与配置", instance / "config", "模型密钥及核心配置，勿分享。个人设置另在实例 fatfish.json。"),
        "qq": ("07-QQ登录资料", instance / "qq", "扫码登录态、QQ 配置与缓存，勿分享。"),
        "emoji": ("08-表情包", instance / "data" / "emoji", "可用表情包原图，自动收集也保存在这里；catalog.json 记录初始图库说明与来源。"),
        "social": ("09-自主资料", instance / "social", "preferences.json 决定是否允许自主换头像/昵称；profile-history.jsonl 记录成功或失败，不影响主人身份。"),
        "portraits": ("10-PNG头像与美图", instance / "data" / "portraits", "独立的 PNG 美图和 Q 版图库；catalog.json 记录编号、画面说明和来源，可让千鱼挑选头像。"),
    }


def ensure_portal(root: Path, instance: Path) -> None:
    if not (root / "layout.json").is_file() or instance.name != "my-fish":
        return
    portal = personal_home(root) / "我的资料"
    portal.mkdir(parents=True, exist_ok=True)
    for title, target, _ in folders(root, instance).values():
        target.mkdir(parents=True, exist_ok=True)
        link = portal / title
        if os.path.lexists(link):
            if link.resolve() != target.resolve():
                raise RuntimeError(f"资料入口指向其他位置，请先处理：{link}")
            continue
        if os.name == "nt":
            quote = lambda p: "'" + str(p).replace("'", "''") + "'"
            result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                "$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path " + quote(link) + " -Target " + quote(target) + " | Out-Null"],
                capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:
                raise RuntimeError("无法创建资料入口：" + str(link))
        else:
            link.symlink_to(target, target_is_directory=True)
    guide = portal / "先看这里.md"
    if not guide.exists():
        guide.write_text((root / "templates" / "资料库使用说明.md").read_text(encoding="utf-8"), encoding="utf-8")


def library_info(root: Path, instance: Path) -> dict:
    from fatfish.knowledge import KnowledgeLibrary
    portal = personal_home(root) / "我的资料"
    entries = []
    for key, (title, target, description) in folders(root, instance).items():
        alias = portal / title
        entries.append(dict(key=key, title=title, path=str(alias if alias.exists() else target), description=description))
    return {"folders": entries, "index": KnowledgeLibrary(instance).status(), "share": str(share_dir(root))}
