"""Local transactional upgrades. Never downloads code or follows external data links."""
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

import ctypes
import datetime as dt
import hashlib
import json
import os
import shutil
import time
import uuid

ACTIVE = ".qianyu-update.json"
BASELINE = "deepseek-baseline-v1"
PRIVATE = {"instances", ".runtime", ".external", ".tools", "backups", "备份", "我的资料"}


def load(path, default=None):
    return json.loads(Path(path).read_text(encoding="utf-8-sig")) if Path(path).is_file() else default


def atomic(path: Path, content: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".update-" + uuid.uuid4().hex)
    try:
        with temporary.open("wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def save(path: Path, value):
    atomic(path, json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"))


def sha(path: Path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def value_sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def safe(root: Path, relative: str):
    parts = PurePosixPath(relative)
    if (parts.is_absolute() or "\\" in relative or ":" in relative
            or any(part in {"..", ""} for part in parts.parts)):
        raise ValueError("升级路径无效。")
    path = root / Path(*parts.parts)
    ancestors = [path, *path.parents]
    linked = any(p.is_symlink() or p.is_junction() for p in ancestors if p != root and p.is_relative_to(root))
    if not path.resolve().is_relative_to(root.resolve()) or linked:
        raise ValueError("升级目录中的链接指向了安装位置以外，已停止。")
    return path


def program_root(home: Path):
    if (home / "程序/fatfish/core.py").is_file():
        return home / "程序", "personal-home/program"
    if (home / "fatfish/core.py").is_file():
        return home, "flat-install"
    return home / "程序", "personal-home/program"


def alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            return False
        try:
            return kernel.WaitForSingleObject(handle, 0) == 258
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def stop_existing(root: Path):
    """Only use this install's authenticated loopback API; never kill by process name."""
    info = load(root / ".runtime/launcher.json", {})
    if not info:
        return {"desktop_was_running": False, "core_was_running": False}
    parsed = urlsplit(str(info.get("url", "")))
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("旧版管理地址无效，未向该地址发送凭据。")
    port = int(info.get("port", 0))
    token = parse_qs(parsed.fragment).get("token", [""])[0]
    if not 1024 <= port <= 65535 or parsed.port != port or not token:
        raise ValueError("旧版管理信息不完整，请正常退出旧版后重试。")
    base = f"http://127.0.0.1:{port}"
    try:
        with urlopen(Request(base + "/api/status", headers={"X-Fatfish-Token": token}), timeout=5) as response:
            status = json.load(response)
    except OSError:
        if alive(info.get("pid")):
            raise RuntimeError("旧版仍在运行但无法正常联系，请正常退出后重试；未改写程序。") from None
        return {"desktop_was_running": False, "core_was_running": False}
    instance = Path(str(status.get("instance", ""))).resolve()
    if not instance.is_relative_to((root / "instances").resolve()):
        raise RuntimeError("该端口属于另一套千鱼，未关停或更新它。")
    print("正在正常关闭旧版并保存资料……", flush=True)
    request = Request(base + "/api/quit", data=b"{}", headers={"X-Fatfish-Token": token, "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=90) as response:
            json.load(response)
    except OSError:
        if alive(info.get("pid")):
            raise RuntimeError("旧版尚未正常退出，未开始覆盖安装。") from None
    deadline = time.monotonic() + 90
    while alive(info.get("pid")) and time.monotonic() < deadline:
        time.sleep(0.25)
    if alive(info.get("pid")):
        raise RuntimeError("旧版进程尚未退出，请等待正常关停后重试。")
    return {"desktop_was_running": True, "core_was_running": bool(status.get("running"))}


def copy_data(source: Path, destination: Path):
    """Back up real files; leave directory links in place without following them."""
    skipped = []
    if not source.exists():
        return skipped
    for current, dirs, files in os.walk(source, followlinks=False):
        current = Path(current)
        kept = []
        for name in dirs:
            item = current / name
            if item.is_symlink() or item.is_junction():
                skipped.append(item.relative_to(source).as_posix())
            else:
                kept.append(name)
        dirs[:] = kept
        target = destination / current.relative_to(source)
        target.mkdir(parents=True, exist_ok=True)
        for name in files:
            item = current / name
            if item.is_symlink():
                skipped.append(item.relative_to(source).as_posix())
            else:
                shutil.copy2(item, target / name)
    return skipped


def memory_fingerprints(root: Path):
    result = {}
    instances = root / "instances"
    if not instances.exists():
        return result
    for instance in instances.iterdir():
        if not instance.is_dir() or instance.is_symlink() or instance.is_junction():
            continue
        for area in ("memory", "knowledge", "data"):
            base = instance / area
            if not base.exists() or base.is_symlink() or base.is_junction():
                continue
            for current, dirs, files in os.walk(base, followlinks=False):
                current = Path(current)
                dirs[:] = [name for name in dirs if not (current / name).is_symlink() and not (current / name).is_junction()]
                for name in files:
                    path = current / name
                    if not path.is_symlink():
                        result[path.relative_to(root).as_posix()] = sha(path)
    return result


class Upgrade:
    def __init__(self, source: Path, home: Path, *, owner_pid=None, stop=stop_existing):
        self.source, self.home = source.resolve(), home.resolve()
        if self.home == Path(self.home.anchor) or self.source.is_relative_to(self.home) or self.home.is_relative_to(self.source):
            raise ValueError("请选择独立的原安装目录，安装来源和目标不能相互包含。")
        self.program, self.layout = program_root(self.home)
        self.backup_base = self.home.parent / "千鱼升级备份" / self.home.name
        if not self.backup_base.resolve().is_relative_to(self.home.parent) or self.backup_base.resolve().is_relative_to(self.home):
            raise ValueError("升级备份位置无效。")
        self.owner_pid, self.stop = owner_pid or 0, stop
        self.tx = None
        self.backup = None
        self.locked = False

    def journal(self):
        save(self.backup / "transaction.json", self.tx)

    def recover(self):
        active = load(self.home / ACTIVE)
        if not active:
            return
        backup = Path(active.get("transaction", "")).resolve()
        if not backup.is_relative_to(self.backup_base.resolve()):
            raise ValueError("旧升级记录指向了其他位置，未自动操作。")
        old = load(backup / "transaction.json", {})
        if old.get("home") != str(self.home):
            raise ValueError("升级恢复记录与安装位置不一致。")
        if old.get("phase") in {"committed", "rolled_back"}:
            (self.home / ACTIVE).unlink()
            return
        if alive(old.get("owner_pid")):
            raise RuntimeError("另一项升级正在进行，请等待其完成。")
        self.stop(self.program)
        current_backup, current_tx, current_locked = self.backup, self.tx, self.locked
        self.backup, self.tx, self.locked = backup, old, True
        self.rollback()
        self.backup, self.tx, self.locked = current_backup, current_tx, current_locked

    def validate(self):
        self.manifest = load(self.source / "release-manifest.json", {})
        if self.manifest.get("personal_data") is not False or not self.manifest.get("files"):
            raise ValueError("不是有效的纯净安装来源。")
        files, seen = {}, set()
        for relative, expected in self.manifest["files"].items():
            path = safe(self.source, relative)
            if not path.is_file() or sha(path) != expected:
                raise ValueError("安装来源文件校验失败：" + relative)
            if any(part.casefold() in {name.casefold() for name in PRIVATE} for part in PurePosixPath(relative).parts):
                raise ValueError("安装来源混入了个人目录。")
            if self.layout == "flat-install":
                dest = relative.removeprefix("程序/")
                if not relative.startswith("程序/") and dest in {"启动千鱼.cmd", "安装千鱼.cmd"}:
                    continue
            else:
                dest = relative
            if dest.casefold() in seen:
                raise ValueError("安装来源有重复的目标文件。")
            seen.add(dest.casefold())
            safe(self.home, dest)
            files[dest] = path
        existing = (self.program / "fatfish/core.py").is_file()
        recovery = load(self.home / ".qianyu-recovery.json", {})
        recovered_backup = Path(recovery.get("transaction", ".")).resolve()
        retry = (recovered_backup.is_relative_to(self.backup_base.resolve())
                 and load(recovered_backup / "transaction.json", {}).get("phase") == "rolled_back")
        if self.home.exists() and any(self.home.iterdir()) and not existing and not (self.home / ACTIVE).is_file() and not retry:
            if set(p.name for p in self.home.iterdir()) - {ACTIVE}:
                raise ValueError("请选择空文件夹或原来的千鱼安装目录。")
        old_manifest = load(self.home / "release-manifest.json", {})
        def version(value):
            try:
                return tuple(int(x) for x in value.split("."))
            except (TypeError, ValueError, AttributeError):
                return ()
        if version(old_manifest.get("version")) > version(self.manifest.get("version")):
            raise ValueError("不能用旧安装包覆盖较新的版本。")
        return files

    def remember(self, path):
        path = safe(self.home, path.relative_to(self.home).as_posix())
        relative = path.relative_to(self.home).as_posix()
        if relative in self.tx["changed"]:
            return
        if path.exists() and not path.is_file():
            raise ValueError("程序文件位置被其他目录占用：" + relative)
        existed = path.is_file()
        if path.is_file():
            backup = safe(self.backup / "previous-files", relative)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)
        self.tx["changed"][relative] = existed
        self.journal()

    def write(self, path, content):
        self.remember(path)
        atomic(path, content)

    def write_json(self, path, value):
        self.write(path, json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"))

    def apply(self):
        files = self.validate()
        self.recover()
        state = self.stop(self.program)
        self.home.mkdir(parents=True, exist_ok=True)
        self.backup = self.backup_base / (dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
        self.backup.mkdir(parents=True)
        self.tx = {"format": 1, "home": str(self.home), "program": str(self.program), "layout": self.layout,
                   "version": self.manifest["version"], "owner_pid": self.owner_pid, "phase": "backing_up",
                   "changed": {}, "previous_state": state, "migration": [], "dependencies": {}}
        self.journal()
        # Exclusive creation prevents two installers from sharing an installation.
        with (self.home / ACTIVE).open("x", encoding="utf-8") as handle:
            json.dump({"transaction": str(self.backup)}, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        self.locked = True
        print("正在备份个人资料、记忆和知识……", flush=True)
        instance_root = self.program / "instances"
        if instance_root.exists() and not instance_root.resolve().is_relative_to(self.home):
            raise ValueError("个人资料链接位于安装目录以外，已停止自动升级。")
        self.tx["skipped_links"] = copy_data(instance_root.resolve(), self.backup / "user-data/instances")
        self.tx["memory_before"] = memory_fingerprints(self.program)
        for name in (".runtime/local.json", ".runtime/install-state.json"):
            self.remember(self.program / name)
        self.tx["phase"] = "applying"
        self.journal()
        print("正在更新通用程序，原有记忆和知识保持原位置……", flush=True)
        for relative, source in files.items():
            content = source.read_bytes()
            if relative == "layout.json" and self.layout == "flat-install":
                layout = json.loads(content)
                layout["layout"] = "flat-install"
                content = json.dumps(layout, ensure_ascii=False).encode("utf-8")
            self.write(safe(self.home, relative), content)
        installed_manifest = dict(self.manifest, installation_layout=self.layout)
        self.write_json(self.home / "release-manifest.json", installed_manifest)
        self.tx["phase"] = "program_updated"
        self.journal()
        return self

    def migrate_defaults(self):
        import tomlkit
        signatures = load(self.source / "程序/templates/migrations/factory-default-digests.json", {})
        style_hashes = signatures.get("style_files", {})
        expected_values = signatures.get("factory_values", {})
        def factory_style(folder):
            if not folder.is_dir():
                return False
            if not folder.resolve().is_relative_to(self.home):
                raise ValueError("风格目录位于安装位置以外，已停止自动操作。")
            files = []
            for current, dirs, names in os.walk(folder, followlinks=False):
                if any((Path(current) / name).is_symlink() or (Path(current) / name).is_junction() for name in dirs + names):
                    return False
                files.extend(Path(current) / name for name in names)
            return {p.relative_to(folder).as_posix(): sha(p) for p in files} == style_hashes and bool(style_hashes)
        source_style = self.program / "templates/style-packs/qianyu-tieba"
        if factory_style(source_style):
            for relative in style_hashes:
                path = safe(self.home, (source_style / relative).relative_to(self.home).as_posix())
                self.remember(path)
                path.unlink()
            self.tx["removed_factory_source_files"] = len(style_hashes)
        instances = self.program / "instances"
        for instance in sorted(instances.iterdir() if instances.exists() else []):
            if not instance.is_dir() or instance.is_symlink() or instance.is_junction():
                continue
            identity = instance / "persona/identity.md"
            settings_path, bot_path = instance / "fatfish.json", instance / "config/bot_config.toml"
            if not all(path.is_file() for path in (identity, settings_path, bot_path)):
                continue
            for path in (identity, settings_path, bot_path):
                safe(self.home, path.relative_to(self.home).as_posix())
            style = instance / "persona/style-pack"
            old_style = factory_style(style)
            old_identity = sha(identity) in signatures.get("identity_sha256", [])
            row = {"instance": instance.name, "factory_style_removed": False, "custom_preserved": True}
            self.tx["migration"].append(row)
            self.journal()
            settings = load(settings_path, {})
            bot = tomlkit.parse(bot_path.read_text(encoding="utf-8-sig"))
            personality = bot["personality"]
            old_text = identity.read_text(encoding="utf-8-sig")
            manual_path = instance / "memory/manual.md"
            manual = manual_path.read_text(encoding="utf-8-sig") if manual_path.is_file() else ""
            old_name = settings.get("nickname", "")
            native = str(personality.get("personality", ""))
            original_base = old_text + ("\n\n主人明确录入的背景资料：\n" + manual if manual.strip() else "")
            if old_style:
                factory_text = (style / "persona.md").read_text(encoding="utf-8-sig")
                suffix = "\n\n主人当前选择的性格与语气（本段优先于旧设定中冲突的语气要求，保留背景事实；当前昵称为“" + old_name + "”）：\n" + factory_text
                if native.endswith(suffix):
                    native = native[:-len(suffix)]
                for relative in style_hashes:
                    path = style / relative
                    self.remember(path)
                    path.unlink()
                row["factory_style_removed"] = True
            if old_identity:
                self.write(identity, b"")
                if native.startswith(original_base) and original_base:
                    native = "你是一个 AI 助手。" + ("\n\n主人明确录入的背景资料：\n" + manual if manual.strip() else "") + native[len(original_base):]
                elif value_sha(native) in expected_values.get("PersonalityConfig.personality", []):
                    native = "你是一个 AI 助手。"
                if old_name in signatures.get("default_nicknames", []) and bot["bot"].get("nickname") == old_name:
                    settings["nickname"] = "DeepSeek"
                    bot["bot"]["nickname"] = "DeepSeek"
                    if list(bot["bot"].get("alias_names", [])) == signatures.get("old_default_aliases"):
                        bot["bot"]["alias_names"] = []
            personality["personality"] = native or "你是一个 AI 助手。"
            current_base = identity.read_text(encoding="utf-8-sig") or "你是一个 AI 助手。"
            current_base += "\n\n主人明确录入的背景资料：\n" + manual if manual.strip() else ""
            for field in ("behavior_style", "reply_style", "multiple_reply_style"):
                current = personality.get(field)
                if value_sha(current) in expected_values.get("PersonalityConfig." + field, []):
                    personality[field] = [] if field == "multiple_reply_style" else ""
                    if field == "multiple_reply_style":
                        personality["multiple_probability"] = 0.0
            chat_style = bot.get("chat", {}).get("reply_style", {})
            for field in ("group_chat_prompt", "private_chat_prompts"):
                if value_sha(chat_style.get(field)) in expected_values.get("ChatReplyStyleConfig." + field, []):
                    chat_style[field] = ""
            self.write_json(settings_path, settings)
            self.write(bot_path, tomlkit.dumps(bot).encode("utf-8"))
            self.write_json(instance / "persona/default-profile.json", {"profile": BASELINE, "initialized": True,
                            "preserve_reply_style": bool(str(personality.get("reply_style", "")).strip()),
                            "preserve_aliases": True,
                            "preserve_native_personality": personality["personality"] != current_base,
                            "identity_sha256": hashlib.sha256(identity.read_text(encoding="utf-8-sig").encode()).hexdigest(),
                            "manual_sha256": hashlib.sha256(manual.encode()).hexdigest()})
            row["custom_identity_preserved"] = not old_identity
            self.journal()
        self.tx["phase"] = "migrated"
        self.journal()

    def commit(self):
        after = memory_fingerprints(self.program)
        if after != self.tx["memory_before"]:
            raise RuntimeError("记忆或知识文件校验不一致，升级将回滚。")
        self.tx["memory_preserved"] = True
        result = {"version": self.tx["version"], "program_root": str(self.program), "backup": str(self.backup),
                  "memory_preserved": True, "memory_files": len(after), "migration": self.tx["migration"],
                  "resume_core": self.tx["previous_state"].get("core_was_running", False), "layout": self.layout}
        save(self.backup / "upgrade-result.json", result)
        previous_phase = self.tx["phase"]
        self.tx["phase"] = "committed"
        try:
            self.journal()
        except BaseException:
            self.tx["phase"] = previous_phase
            raise
        (self.home / ACTIVE).unlink(missing_ok=True)
        (self.home / ".qianyu-recovery.json").unlink(missing_ok=True)
        return result

    def rollback(self):
        if not self.locked or not self.tx or not self.backup or self.tx.get("phase") in {"committed", "rolled_back"}:
            return
        dependency = load(self.backup / "dependency-state.json", {})
        if dependency.get("previous_packages") or dependency.get("fresh_packages"):
            runtime = self.program / ".runtime"
            packages = safe(self.home, (runtime / "site-packages").relative_to(self.home).as_posix())
            previous = safe(self.backup, dependency["previous_packages"]) if dependency.get("previous_packages") else None
            if (previous and previous.is_dir()) or dependency.get("fresh_packages"):
                if packages.exists():
                    if not packages.resolve().is_relative_to(runtime.resolve()) or packages.is_junction():
                        raise ValueError("依赖回滚路径无效，备份已保留。")
                    shutil.rmtree(packages)
                packages.parent.mkdir(parents=True, exist_ok=True)
                if previous and previous.is_dir():
                    previous.rename(packages)
        for relative, existed in reversed(list(self.tx["changed"].items())):
            path = safe(self.home, relative)
            if existed:
                atomic(path, safe(self.backup / "previous-files", relative).read_bytes())
            else:
                path.unlink(missing_ok=True)
        self.tx["phase"] = "rolled_back"
        self.journal()
        (self.home / ACTIVE).unlink(missing_ok=True)
        save(self.home / ".qianyu-recovery.json", {"transaction": str(self.backup)})
