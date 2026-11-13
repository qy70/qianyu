"""白名单构建纯净发行包，永远不读取个人实例或本机运行时凭据。"""

from pathlib import Path

import argparse
import hashlib
import json
import zipfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fatfish import __version__
from fatfish.layout import release_path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {".git", "__pycache__", ".pytest_cache", "node_modules", ".venv", "logs", "temp"}
FILES = ["README.md", "layout.json", "THIRD_PARTY.md", "LICENSE", "upstream.lock.json", "requirements-windows.lock", "sitecustomize.py",
         "launch.ps1", "install.ps1", "setup.ps1", "package.ps1", "千鱼.exe", "千鱼安装助手.exe", "源码发布说明.md", "启动千鱼.cmd", "安装千鱼.cmd", "安装依赖.cmd", "打包纯净版.cmd"]
DIRECTORIES = ["fatfish", "scripts", "templates", "tests", "engine/MaiBot", "components/qq-connector", "components/qianyu-style", "components/qianyu-social"]
DISTRIBUTION_FILES = ("启动千鱼.cmd", "安装千鱼.cmd", "使用说明.md", "操作手册.pdf", "操作手册.md")


def selected_files(root: Path):
    for name in FILES:
        path = root / name
        if not path.is_file():
            raise FileNotFoundError(f"发行文件缺失：{name}")
        yield path
    for name in DIRECTORIES:
        base = root / name
        for path in sorted(base.rglob("*")):
            rel = path.relative_to(base)
            if not path.is_file() or any(p in EXCLUDED or p.endswith(".egg-info") for p in rel.parts):
                continue
            if path.suffix in {".pyc", ".pyo"}:
                continue
            if name == "templates" and rel.parts[0] == "style-packs":
                # 可选的历史写作模板不属于模型默认纯净发行包。
                continue
            if name == "engine/MaiBot" and rel.parts[0] in {"config", "data", "backups", "dashboard"}:
                continue
            if name == "components/qq-connector" and rel.name == "config.toml":
                continue
            if path.is_symlink():
                raise ValueError(f"发行包不接受符号链接：{path}")
            yield path


def build(root: Path = ROOT, output: Path | None = None) -> Path:
    root = root.resolve()
    output = output or release_path(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    if (root / "templates/persona.md").read_text(encoding="utf-8-sig").strip():
        raise ValueError("纯净发行的人格模板必须为空。")
    manifest = {"product": "fatfish", "version": __version__, "personal_data": False,
                "defaults": {"profile": "deepseek-baseline-v1", "persona": False, "style_pack": False,
                             "personal_memory": False, "knowledge": False}, "files": {}}
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in selected_files(root):
            relative = path.relative_to(root).as_posix()
            if any(p in {"instances", "backups", ".runtime", ".tools"} for p in Path(relative).parts):
                raise ValueError("纯净包选择到了个人或运行数据")
            content = path.read_bytes()
            if relative == "layout.json":
                content = json.dumps(dict(json.loads(content), layout="personal-home/program"), ensure_ascii=False).encode("utf-8")
            manifest["files"]["程序/" + relative] = hashlib.sha256(content).hexdigest()
            archive.writestr("千鱼纯净版/程序/" + relative, content)
        for name in DISTRIBUTION_FILES:
            content = (root / "templates" / "distribution" / name).read_bytes()
            manifest["files"][name] = hashlib.sha256(content).hexdigest()
            archive.writestr("千鱼纯净版/" + name, content)
        archive.writestr("千鱼纯净版/release-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("发行包校验失败")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(build(output=args.output))
