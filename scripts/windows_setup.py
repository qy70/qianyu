"""Native installer's dependency stage; standard library only, no PowerShell."""
from pathlib import Path
import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
PROBE = "import tomlkit,webview,win32api,maim_message; print('READY')"


def environment(root: Path, packages: Path) -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(packages), str(root / "engine/MaiBot"), str(root)))
    env["PYTHONUTF8"] = "1"
    return env


def probe(root: Path, packages: Path) -> bool:
    result = subprocess.run([sys.executable, "-c", PROBE], cwd=root,
                            env=environment(root, packages), capture_output=True, timeout=45)
    return result.returncode == 0 and b"READY" in result.stdout


def clean_generated(path: Path, runtime: Path) -> None:
    if (path.parent.resolve() != runtime.resolve() or not path.resolve().is_relative_to(runtime.resolve())
            or not path.name.startswith(("install-staging-", "install-previous-"))):
        raise RuntimeError("拒绝清理运行环境以外的目录。")
    shutil.rmtree(path)


def installed_versions_match(root: Path, packages: Path) -> bool:
    normalize = lambda value: re.sub(r"[-_.]+", "-", value).lower()
    installed = {normalize(dist.metadata.get("Name", "")): dist.version
                 for dist in importlib.metadata.distributions(path=[str(packages)])}
    expected = []
    for line in (root / "requirements-windows.lock").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s;]+)", line.strip())
        if not match:
            return False
        expected.append((normalize(match[1]), match[2]))
    return bool(expected) and all(installed.get(name) == version for name, version in expected)


def prepare(root: Path, check: bool = False, rollback_directory: Path | None = None) -> None:
    if sys.version_info[:2] != (3, 12) or struct.calcsize("P") != 8:
        raise RuntimeError("需要 Python 3.12 x64。")
    runtime = root / ".runtime"
    if not runtime.resolve().is_relative_to(root.resolve()) or runtime.is_symlink() or runtime.is_junction():
        raise RuntimeError("运行环境目录必须在本次安装内，不能使用目录链接。")
    packages = runtime / "site-packages"
    if packages.is_symlink() or packages.is_junction():
        raise RuntimeError("依赖目录必须是本次安装内的普通目录。")
    if check:
        if not probe(root, packages):
            raise RuntimeError("依赖不完整，请重新运行安装入口。")
        print("Python 与千鱼依赖检查通过。")
        return
    runtime.mkdir(parents=True, exist_ok=True)
    lock_hash = hashlib.sha256((root / "requirements-windows.lock").read_bytes()).hexdigest()
    state_path = runtime / "install-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    if (state.get("requirements_sha256") == lock_hash or installed_versions_match(root, packages)) and probe(root, packages):
        print("已有依赖检查通过。")
    else:
        staging = runtime / ("install-staging-" + uuid.uuid4().hex)
        previous = ((rollback_directory / "dependencies/site-packages") if rollback_directory
                    else runtime / ("install-previous-" + uuid.uuid4().hex))
        staging.mkdir()
        try:
            print("正在从 PyPI 安装锁定版本依赖，下载期间请保持窗口打开。", flush=True)
            command = [sys.executable, "-I", "-m", "pip", "--isolated", "install", "--disable-pip-version-check",
                       "--target", str(staging), "-r", str(root / "requirements-windows.lock"),
                       "--index-url", "https://pypi.org/simple", "--no-warn-script-location"]
            with (runtime / "install.log").open("a", encoding="utf-8") as log:
                process = subprocess.Popen(command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           text=True, encoding="utf-8", errors="replace")
                for line in process.stdout:
                    print(line, end="", flush=True)
                    log.write(line)
                if process.wait() != 0:
                    raise RuntimeError("依赖下载或安装失败，原有依赖未替换；请查看 .runtime/install.log。")
            check_code = "import site; site.addsitedir(" + repr(str(staging)) + "); " + PROBE
            result = subprocess.run([sys.executable, "-I", "-c", check_code], cwd=root, capture_output=True, timeout=45)
            if result.returncode:
                raise RuntimeError("新依赖检查失败，原有依赖未替换。" + result.stderr.decode("utf-8", "replace")[-1500:])
            if packages.exists():
                if not packages.resolve().is_relative_to(runtime.resolve()) or packages.is_junction():
                    raise RuntimeError("原依赖目录不在安装位置内，已停止替换。")
                if rollback_directory:
                    from fatfish.updater import save
                    if not previous.resolve().is_relative_to(rollback_directory.resolve()):
                        raise RuntimeError("依赖备份目标无效。")
                    previous.parent.mkdir(parents=True, exist_ok=True)
                    save(rollback_directory / "dependency-state.json", {"previous_packages": "dependencies/site-packages"})
                packages.rename(previous)
            elif rollback_directory:
                from fatfish.updater import save
                save(rollback_directory / "dependency-state.json", {"fresh_packages": True})
            try:
                staging.rename(packages)
                if not probe(root, packages):
                    raise RuntimeError("安装后依赖检查失败。")
            except BaseException:
                if packages.exists():
                    packages.rename(staging)
                if previous.exists():
                    previous.rename(packages)
                raise
            # These generated paths are confined to this install's .runtime.
            if previous.exists() and not rollback_directory:
                clean_generated(previous, runtime)
        finally:
            if staging.exists():
                clean_generated(staging, runtime)
    for path, value in ((runtime / "local.json", {"python": sys.executable}),
                        (state_path, {"requirements_sha256": lock_hash, "python": sys.executable})):
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    print("千鱼依赖准备完成。", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        prepare(ROOT, check=args.check)
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
