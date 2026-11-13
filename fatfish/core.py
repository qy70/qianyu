"""管理个人实例，不修改 MaiBot 上游源码。"""

from pathlib import Path
from urllib.parse import urlparse

import asyncio
import collections
import datetime as dt
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import zipfile

import tomlkit

from fatfish import __version__

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PERSONA = ""
BASELINE_PROFILE = "deepseek-baseline-v1"
DEFAULTS = {
    "nickname": "DeepSeek", "qq_account": "", "group_scope": "all", "private_scope": "off", "groups": [], "users": [],
    "api_base": "https://api.deepseek.com", "model": "deepseek-flash",
    "qq_host": "127.0.0.1", "qq_port": 3001,
    "participation": "quiet", "group_reply_frequency": 0.05, "memory_enabled": False,
    "vision_enabled": True, "collect_emoji": False, "shared_memory_enabled": True,
}


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + secrets.token_hex(4))
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else default


def tcp_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False


def worker_python() -> str:
    """桌面用 pythonw，核心必须用具备标准输出的 python；窗口由启动参数隐藏。"""
    executable = Path(sys.executable)
    if os.name == "nt" and executable.name.lower() == "pythonw.exe":
        console = executable.with_name("python.exe")
        if not console.is_file():
            raise RuntimeError("核心所需的 Python 运行文件缺失，请修复 Python 安装")
        return str(console)
    return str(executable)


def copy_component(source: Path, destination: Path) -> None:
    """复制固定程序文件，保留实例自己生成的配置和数据。"""
    shutil.copytree(source, destination, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "config.toml", "tests"))


class FishManager:
    def __init__(self, root: Path = ROOT, instance_name: str = "my-fish"):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,48}", instance_name):
            raise ValueError("实例名称只能使用英文字母、数字、横线和下划线")
        self.root = root.resolve()
        self.instance = self.root / "instances" / instance_name
        self.engine = self.root / "engine" / "MaiBot"
        self.process = None
        self.logs = collections.deque(maxlen=400)
        self.lock = threading.RLock()
        self.started_at = None
        self.last_exit = None
        self._reader = None
        self.boot_ready = False

    def env(self) -> dict:
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join((str(self.root / ".runtime" / "site-packages"), str(self.engine), str(self.root)))
        env["PYTHONUTF8"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        env["MAIBOT_INSTANCE_DIR"] = str(self.instance)
        env["MAIBOT_LOCALE"] = "zh-CN"
        env["FATFISH_STOP_FILE"] = str(self.instance / "stop.request")
        env.pop("MAIBOT_INITIALIZE_ONLY", None)
        return env

    def initialize(self) -> None:
        new_instance = not (self.instance / "fatfish.json").exists()
        fresh_profile = new_instance and not (self.instance / "persona/identity.md").exists()
        self.instance.mkdir(parents=True, exist_ok=True)
        if not (self.instance / "config" / "bot_config.toml").exists():
            result = subprocess.run([worker_python(), "-m", "src.cli.tool", "init", "--directory", str(self.instance)],
                                    env=self.env(), cwd=self.root, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=90,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            if result.returncode:
                raise RuntimeError("MaiBot 初始化失败：" + result.stdout[-1500:] + result.stderr[-1500:])
        connector = self.instance / "plugins" / "qq-connector"
        if not (connector / "_manifest.json").exists():
            copy_component(self.root / "components" / "qq-connector", connector)
        # 自有风格插件按实例安装；没有启用本实例风格包时不会影响回复。
        style_component = self.root / "components" / "qianyu-style"
        if style_component.is_dir():
            copy_component(style_component, self.instance / "plugins" / "qianyu-style")
        social_component = self.root / "components" / "qianyu-social"
        if social_component.is_dir():
            copy_component(social_component, self.instance / "plugins" / "qianyu-social")
        social_policy = self.instance / "social" / "preferences.json"
        if not social_policy.exists():
            atomic_text(social_policy, json.dumps({"enabled": False, "owner_qq": "", "cooldown_hours": 24}, ensure_ascii=False, indent=2))
        # 从通用模板启用话题接话，已有实例的呼叫词与开关始终保留。
        topic_policy = self.instance / "social" / "topic-reply.json"
        topic_template = self.root / "templates" / "topic-reply.json"
        if not topic_policy.exists() and topic_template.is_file():
            copy_component_text = topic_template.read_text(encoding="utf-8")
            atomic_text(topic_policy, copy_component_text)
        template_path = self.root / "templates" / "persona.md"
        initial_persona = template_path.read_text(encoding="utf-8") if template_path.exists() else DEFAULT_PERSONA
        for name, value in (("persona/identity.md", initial_persona), ("memory/manual.md", "")):
            path = self.instance / name
            if not path.exists():
                atomic_text(path, value)
        settings_path = self.instance / "fatfish.json"
        # 新安装不预置人设、语气或示例；旧实例不自动重置或迁移。
        if fresh_profile:
            atomic_text(self.instance / "persona/default-profile.json",
                        json.dumps({"profile": BASELINE_PROFILE, "initialized": False}, ensure_ascii=False, indent=2))
        notes = self.instance / "memory" / "notes"
        notes.mkdir(parents=True, exist_ok=True)
        (self.instance / "knowledge").mkdir(exist_ok=True)
        pinned = notes / "00-核心记忆.md"
        if not pinned.exists():
            atomic_text(pinned, "")
        for folder, text in ((notes, "在 00-核心记忆.md 写重要事实；其他记忆可新建 UTF-8 的 .md / .txt。开头 _ 的说明文件不读取。详见软件我的资料库或上层资料说明。\n"),
                             (self.instance / "knowledge", "把 UTF-8 的 Markdown / TXT 知识文章放这里，可以建子目录。请使用明确标题和主题词。详见软件我的资料库或上层资料说明。\n")):
            guide = folder / "_怎么添加.md"
            if not guide.exists():
                atomic_text(guide, text)
        from fatfish.layout import ensure_portal
        ensure_portal(self.root, self.instance)
        if not settings_path.exists():
            settings = dict(DEFAULTS, qq_token=secrets.token_urlsafe(24),
                            persona=(self.instance / "persona" / "identity.md").read_text(encoding="utf-8"),
                            manual_memory=(self.instance / "memory" / "manual.md").read_text(encoding="utf-8"))
            self.apply_config(settings)
        elif "fatfish-deepseek" not in (self.instance / "config" / "model_config.toml").read_text(encoding="utf-8"):
            self.apply_config(self.settings(private=True))

    def settings(self, private: bool = False) -> dict:
        stored = read_json(self.instance / "fatfish.json", {})
        data = dict(DEFAULTS, **stored)
        if "group_reply_frequency" not in stored:
            # 保留旧实例当前生效的全天群聊规则，包括此前手工调到的 0.5。
            timing = tomlkit.parse((self.instance / "config" / "bot_config.toml").read_text(encoding="utf-8"))["chat"]["reply_timing"]
            data["group_reply_frequency"] = float(timing["talk_value"])
            if timing.get("enable_talk_value_rules"):
                for rule in timing.get("talk_value_rules", []):
                    if not rule.get("platform") and not rule.get("item_id") and rule.get("rule_type") == "group" and rule.get("time") in {"*", "00:00-23:59"}:
                        data["group_reply_frequency"] = float(rule["value"])
        # 旧实例的指定名单与仅私聊设置继续保留，尚未设置范围的实例默认所有群。
        if "group_scope" not in stored:
            data["group_scope"] = "selected" if stored.get("groups") or stored.get("users") else "all"
        if "private_scope" not in stored:
            data["private_scope"] = "selected" if stored.get("users") else "off"
        models = tomlkit.parse((self.instance / "config" / "model_config.toml").read_text(encoding="utf-8"))
        provider = next((p for p in models.get("api_providers", []) if p["name"] == "fatfish-deepseek"), {})
        data["api_key"] = str(provider.get("api_key", ""))
        data["has_api_key"] = bool(data["api_key"] and data["api_key"] != "your-api-key")
        data["persona"] = (self.instance / "persona" / "identity.md").read_text(encoding="utf-8")
        data["manual_memory"] = (self.instance / "memory" / "manual.md").read_text(encoding="utf-8")
        if not private:
            data.pop("api_key", None)
            data.pop("qq_token", None)
        return data

    @staticmethod
    def has_chat_scope(data: dict) -> bool:
        private_scope = data.get("private_scope", "selected" if data.get("users") else "off")
        return (data.get("group_scope", "selected") == "all" or bool(data.get("groups"))
                or private_scope == "all" or (private_scope == "selected" and bool(data.get("users"))))

    @staticmethod
    def validate(data: dict) -> dict:
        data = dict(data)
        data.setdefault("group_scope", "selected")
        if data["group_scope"] not in {"all", "selected"}:
            raise ValueError("群聊范围请选择所有群聊或指定群聊")
        data.setdefault("private_scope", "selected" if data.get("users") else "off")
        if data["private_scope"] not in {"off", "all", "selected"}:
            raise ValueError("私聊范围请选择关闭私聊、所有私聊或指定联系人")
        for field, limit in (("nickname", 40), ("model", 160), ("persona", 12000), ("manual_memory", 12000)):
            value = data.get(field, "")
            if not isinstance(value, str) or len(value) > limit:
                raise ValueError(f"{field} 内容格式或长度不正确")
        if not data.get("nickname", "").strip() or not data.get("model", "").strip():
            raise ValueError("名字和模型名称不能为空")
        for field in ("groups", "users"):
            values = data.get(field, [])
            if not isinstance(values, list) or len(values) > 100 or any(not re.fullmatch(r"[1-9][0-9]{3,15}", str(x)) for x in values):
                raise ValueError("群号和私聊账号请填写有效数字，每项用逗号分隔")
            data[field] = list(dict.fromkeys(str(x) for x in values))
        qq = data.get("qq_account", "")
        if qq and not re.fullmatch(r"[1-9][0-9]{3,15}", qq):
            raise ValueError("机器人 QQ 号格式不正确")
        url = urlparse(data.get("api_base", ""))
        if url.scheme not in {"https", "http"} or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("API 地址必须是完整的 HTTP 或 HTTPS 地址，不能包含账号或查询参数")
        if url.scheme == "http" and url.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("远程模型服务请使用 HTTPS 地址")
        if data.get("qq_host") not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("本地版 QQ 连接地址请使用本机回环地址")
        if type(data.get("qq_port")) is not int or not 1024 <= data["qq_port"] <= 65535:
            raise ValueError("QQ 接口端口应为 1024–65535")
        if data.get("participation") not in {"quiet", "normal"} or type(data.get("memory_enabled")) is not bool:
            raise ValueError("发言或记忆设置无效")
        FishManager.validate_group_reply_frequency(data["group_reply_frequency"])
        for flag in ("vision_enabled", "collect_emoji", "shared_memory_enabled"):
            if type(data.get(flag, True)) is not bool:
                raise ValueError("识图与表情包设置无效")
        for field in ("api_key", "qq_token"):
            value = data.get(field, "")
            if not isinstance(value, str) or len(value) > 4096 or "\n" in value or "\r" in value:
                raise ValueError("密钥或令牌格式无效")
        return data

    @staticmethod
    def validate_group_reply_frequency(value):
        if type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("主动接话频率应为 0 到 1 之间的数字")

    @staticmethod
    def apply_group_reply_frequency(bot, value):
        FishManager.validate_group_reply_frequency(value)
        timing = bot["chat"]["reply_timing"]
        timing["talk_value"] = float(value)
        # 滑块只表示新话题触发概率；端点 1 也不切换到逐条回复。
        timing["reply_each_message"] = False
        # 页面控制所有已接入群聊，旧全天/分群规则不能把滑块的值覆盖掉。
        timing["enable_talk_value_rules"] = False

    def save_group_reply_frequency(self, submitted):
        if set(submitted) != {"group_reply_frequency"}:
            raise ValueError("此按钮只保存主动接话频率")
        value = submitted["group_reply_frequency"]
        self.validate_group_reply_frequency(value)
        with self.lock:
            bot_path = self.instance / "config" / "bot_config.toml"
            settings_path = self.instance / "fatfish.json"
            bot = tomlkit.parse(bot_path.read_text(encoding="utf-8"))
            self.apply_group_reply_frequency(bot, value)
            stored = read_json(settings_path, {})
            stored["group_reply_frequency"] = float(value)
            documents = {settings_path: json.dumps(stored, ensure_ascii=False, indent=2), bot_path: tomlkit.dumps(bot)}
            originals = {path: path.read_bytes() for path in documents}
            try:
                for path, content in documents.items():
                    atomic_text(path, content)
            except Exception:
                for path, original in originals.items():
                    path.write_bytes(original)
                raise
            return self.settings()

    def save(self, submitted: dict) -> dict:
        with self.lock:
            if self.running():
                raise ValueError("请先停止大肥鱼再保存配置，避免与高级设置同时写入")
            current = self.settings(private=True)
            allowed = set(DEFAULTS) | {"api_key", "qq_token", "persona", "manual_memory"}
            if set(submitted) - allowed:
                raise ValueError("包含不支持的设置字段")
            data = {**current, **submitted}
            # 兼容旧页面和脚本：只提交群号列表时仍按指定群聊处理。
            if "groups" in submitted and "group_scope" not in submitted:
                data["group_scope"] = "selected"
            if "users" in submitted and "private_scope" not in submitted:
                data["private_scope"] = "selected" if submitted["users"] else "off"
            for secret in ("api_key", "qq_token"):
                if not submitted.get(secret):
                    data[secret] = current[secret]
            data = self.validate(data)
            self.apply_config(data)
            return self.settings()

    def fish_identities(self):
        from fatfish.fish_identity import FishIdentityMemory
        return {"people": sorted(FishIdentityMemory(self.instance).rows().values(),
                                 key=lambda row: row.get("updated_at", 0), reverse=True)}

    def correct_fish_identity(self, submitted):
        from fatfish.fish_identity import FishIdentityMemory
        if set(submitted) != {"user_id", "status"}:
            raise ValueError("请提供 QQ 号与身份。")
        FishIdentityMemory(self.instance).correct(submitted["user_id"], submitted["status"])
        return {"message": "人物身份已纠正，下一条消息生效。", **self.fish_identities()}

    def apply_config(self, data: dict) -> None:
        bot_path = self.instance / "config" / "bot_config.toml"
        model_path = self.instance / "config" / "model_config.toml"
        bot = tomlkit.parse(bot_path.read_text(encoding="utf-8"))
        models = tomlkit.parse(model_path.read_text(encoding="utf-8"))
        profile_path = self.instance / "persona/default-profile.json"
        profile = read_json(profile_path, {})
        baseline = profile.get("profile") == BASELINE_PROFILE
        aliases = list(bot["bot"].get("alias_names", [])) if baseline and (profile.get("initialized") or profile.get("preserve_aliases")) else ([] if baseline else ["肥鱼"])
        bot["bot"].update(platform="qq", qq_account=data["qq_account"], nickname=data["nickname"], alias_names=aliases)
        persona = data.get("persona", DEFAULT_PERSONA)
        memory = data.get("manual_memory", "")
        # 上游会把空人设解释为“是人类”；中性新实例仅使用通用 AI 身份。
        model_identity = (persona or "你是一个 AI 助手。") if baseline else persona
        keep_native = (baseline and profile.get("preserve_native_personality")
                         and profile.get("identity_sha256") == hashlib.sha256(persona.encode()).hexdigest()
                         and profile.get("manual_sha256") == hashlib.sha256(memory.encode()).hexdigest())
        if not keep_native:
            bot["personality"]["personality"] = model_identity + ("\n\n主人明确录入的背景资料：\n" + memory if memory.strip() else "")
        if not baseline or not profile.get("initialized"):
            bot["personality"]["selected_profile"] = ""
        if not baseline or (not profile.get("initialized") and not profile.get("preserve_reply_style")):
            bot["personality"]["reply_style"] = "" if baseline else "优先用一两句自然中文回答，不堆列表，不使用客服套话；需要解释时再展开。"
        if baseline and not profile.get("initialized"):
            bot["personality"].update(behavior_style="", multiple_reply_style=[], multiple_probability=0.0, profiles=[])
            bot["chat"]["reply_style"].update(group_chat_prompt="", private_chat_prompts="")
        style_dir = self.instance / "persona" / "style-pack"
        style_manifest = read_json(style_dir / "manifest.json", {})
        if style_manifest.get("enabled") is True:
            style_persona = (style_dir / "persona.md").read_text(encoding="utf-8")
            natural_style = (style_dir / "reply-style.md").read_text(encoding="utf-8")
            style_suffix = "\n\n主人当前选择的性格与语气（本段优先于旧设定中冲突的语气要求，保留背景事实；当前昵称为“" + data["nickname"] + "”）：\n" + style_persona
            if not bot["personality"]["personality"].endswith(style_suffix):
                bot["personality"]["personality"] += style_suffix
            bot["personality"]["reply_style"] = natural_style
        if not baseline or style_manifest.get("enabled") is True:
            bot["personality"]["reply_style"] += "\n喜欢用真正的表情包表达情绪：轻松聊天、接梗、开心、无语、得意时积极使用 send_emoji，或 qianyu_sticker 精确选择图库；通常一轮一张，有合适表情可以只回图，不必每次硬配文字。不输出假装发图的括号旁白。严肃解释与真实痛苦场合少插图。"
        timing = bot["chat"]["reply_timing"]
        self.apply_group_reply_frequency(bot, data["group_reply_frequency"])
        timing["mentioned_bot_reply"] = True
        timing["inevitable_at_reply"] = True
        timing["planner_message_steering"] = False
        timing["no_action_backoff_base_seconds"] = 30.0
        bot["chat"]["max_context_size"] = 30
        bot["http"].update(host=["127.0.0.1"], port=18001)
        bot["telemetry"]["enable"] = False
        bot["maim_message"]["enabled"] = False
        bot["maim_message"]["enable_api_server"] = False
        bot["debug"]["enable_console_input"] = False
        bot["agent"]["enabled"] = False
        bot["computer"]["enabled"] = False
        bot["a_memorix"]["plugin"]["enabled"] = data["memory_enabled"]
        bot["a_memorix"]["image_memory"]["enabled"] = False
        bot["emoji"]["steal_emoji"] = data.get("collect_emoji", True)
        bot["emoji"]["max_reg_num"] = max(int(bot["emoji"].get("max_reg_num", 64)), 256)
        bot["emoji"]["max_emoji_size_mb"] = 5.0
        bot["emoji"]["check_interval"] = 5
        providers = models["api_providers"]
        provider = next((p for p in providers if p["name"] == "fatfish-deepseek"), None)
        if provider is None:
            provider = tomlkit.table()
            providers.append(provider)
        provider.update(name="fatfish-deepseek", base_url=data["api_base"].rstrip("/"),
                        api_key=data.get("api_key") or "your-api-key", client_type="openai",
                        max_retry=1, timeout=60, retry_interval=3)
        model = next((m for m in models["models"] if m["name"] == "fatfish-chat"), None)
        if model is None:
            model = tomlkit.table()
            models["models"].append(model)
        model.update(name="fatfish-chat", model_identifier=data["model"], api_provider="fatfish-deepseek",
                     model_type="llm", send_temperature=True, visual=data.get("vision_enabled", True),
                     extra_params={"thinking": {"type": "disabled"}})
        for name in ("utils", "memory", "replyer", "planner", "learner", "fast_model", "emoji"):
            models["model_task_config"][name].update(model_list=["fatfish-chat"], max_tokens=2048, hard_timeout=90.0)
        vision = models["model_task_config"]["vlm"]
        if data.get("vision_enabled", True):
            # 保留用户在高级设置中配置的独立视觉模型；空任务使用当前聊天模型。
            if not vision.get("model_list"):
                vision["model_list"] = ["fatfish-chat"]
        else:
            vision["model_list"] = []
        # 先通过上游类型校验再发布，避免写入 MaiBot 无法加载的设置。
        os.environ["MAIBOT_INITIALIZE_ONLY"] = "1"
        os.environ["MAIBOT_INSTANCE_DIR"] = str(self.instance)
        from src.config.config import Config, ModelConfig, _normalize_a_memorix_config
        bot_validation = bot.unwrap()
        bot_validation["a_memorix"] = _normalize_a_memorix_config(bot_validation["a_memorix"])
        bot_validation.pop("inner", None)
        model_validation = models.unwrap()
        model_validation.pop("inner", None)
        Config.model_validate(bot_validation)
        ModelConfig.model_validate(model_validation)
        adapter_path = self.instance / "plugins" / "qq-connector" / "config.toml"
        adapter = tomlkit.parse(adapter_path.read_text(encoding="utf-8")) if adapter_path.exists() else tomlkit.document()
        if "plugin" not in adapter:
            adapter["plugin"] = {"enabled": True, "config_version": "2.7.1"}
        adapter.setdefault("client", {})
        adapter["client"].update(client_type="napcat", server=data["qq_host"], port=data["qq_port"],
                                 token=data["qq_token"], connection_id="fatfish-primary")
        adapter.setdefault("debug", {})
        adapter["debug"]["ignore_self_message"] = True
        all_groups = data.get("group_scope", "selected") == "all"
        private_scope = data.get("private_scope", "selected" if data.get("users") else "off")
        policy = {"defaults": {"group": {"default_action": "allow" if all_groups else "block", "allow_ids": [] if all_groups else data["groups"]},
                               "private": {"default_action": "allow" if private_scope == "all" else "block",
                                           "allow_ids": data["users"] if private_scope == "selected" else []}}}
        documents = {
            bot_path: tomlkit.dumps(bot), model_path: tomlkit.dumps(models),
            adapter_path: tomlkit.dumps(adapter),
            self.instance / "config" / "adapter_policy.toml": tomlkit.dumps(policy),
            self.instance / "persona" / "identity.md": persona,
            self.instance / "memory" / "manual.md": memory,
            self.instance / "fatfish.json": json.dumps({k: data[k] for k in (*DEFAULTS, "qq_token")}, ensure_ascii=False, indent=2),
        }
        if baseline and not profile.get("initialized"):
            documents[profile_path] = json.dumps({**profile, "initialized": True}, ensure_ascii=False, indent=2)
        originals = {path: path.read_bytes() if path.exists() else None for path in documents}
        try:
            for path, content in documents.items():
                atomic_text(path, content)
        except Exception:
            for path, original in originals.items():
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(original)
            raise

    def running(self) -> bool:
        if self.process is None:
            return False
        code = self.process.poll()
        if code is not None:
            self.last_exit = code
            return False
        return True

    def redact(self, text: str) -> str:
        try:
            data = self.settings(private=True)
            values = [data.get("api_key"), data.get("qq_token")]
            auth = read_json(self.instance / "data" / "webui.json", {})
            values.append(auth.get("access_token"))
            for value in values:
                if value and value != "your-api-key":
                    text = text.replace(value, "[已隐藏密钥]")
        except (OSError, ValueError):
            pass
        return re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[已隐藏密钥]", text)

    def _read_output(self, process):
        log_path = self.instance / "logs" / "launcher-core.log"
        log_path.parent.mkdir(exist_ok=True)
        # 启动记录只保留本轮，完整运行日志仍由 MaiBot 自己管理。
        with log_path.open("w", encoding="utf-8") as handle:
            for line in process.stdout:
                clean = self.redact(re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", line.rstrip()))
                if "全部系统初始化完成" in clean:
                    self.boot_ready = True
                if "主程序发生异常" in clean:
                    self.boot_ready = False
                self.logs.append(clean)
                handle.write(clean + "\n")
                handle.flush()
            code = process.wait()
            if code:
                clean = f"核心启动或运行失败（退出码 {code}），请查看运行记录。"
                self.logs.append(clean)
                handle.write(clean + "\n")
                handle.flush()

    def start(self, allow_unconfigured: bool = False):
        with self.lock:
            if self.running():
                return {"message": "大肥鱼已经在运行"}
            data = self.settings()
            if not allow_unconfigured:
                if not data["has_api_key"]:
                    raise ValueError("先在连接设置中填写 API Key 并保存")
                if not data["qq_account"]:
                    raise ValueError("先填写或填入已登录的小号 QQ，并保存连接设置")
                if not self.has_chat_scope(data):
                    raise ValueError("请选择允许接入的群聊或私聊范围，指定模式下至少填写一个群号或联系人 QQ 号，再保存")
            if tcp_open("127.0.0.1", 18001):
                raise ValueError("18001 端口已被其他进程占用，请先关闭已有实例")
            # 直接编辑 Markdown 的人格和明确背景，也会在启动时发布到核心配置。
            self.apply_config(self.settings(private=True))
            self.logs.clear()
            self.boot_ready = False
            (self.instance / "stop.request").unlink(missing_ok=True)
            self.logs.append("启动 MaiBot，正在等待核心就绪……")
            kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
            self.last_exit = None
            self.process = subprocess.Popen([worker_python(), "-m", "src.cli.tool", "run", "--directory", str(self.instance)],
                                            env=self.env(), cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                            stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", **kwargs)
            self.started_at = time.time()
            self._reader = threading.Thread(target=self._read_output, args=(self.process,), daemon=True)
            self._reader.start()
            return {"message": "已发出启动请求，请在状态和日志中查看真实结果"}

    def stop(self):
        with self.lock:
            forced = False
            if self.running():
                atomic_text(self.instance / "stop.request", "stop")
                try:
                    self.process.wait(timeout=55)
                except subprocess.TimeoutExpired:
                    forced = True
                    # 正常退出超时后，只结束本启动器自己创建且仍存活的进程树。
                    if os.name == "nt":
                        subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"], capture_output=True, timeout=15)
                    else:
                        import signal
                        os.killpg(self.process.pid, signal.SIGTERM)
                    self.process.wait(timeout=20)
            if self._reader:
                self._reader.join(timeout=3)
            self.boot_ready = False
            return {"message": ("正常关停超时，已强制停止，请检查运行记录。" if forced else "核心已正常停止。") + "人格和记忆保留，QQ 客户端单独管理"}

    def status(self) -> dict:
        data = self.settings()
        live = self.running()
        return {"running": live, "ready": live and self.boot_ready and tcp_open("127.0.0.1", 18001),
                "last_exit": self.last_exit, "started_at": self.started_at,
                "instance": str(self.instance), "version": __version__, "engine_version": "1.3.19",
                "api_configured": data["has_api_key"], "qq_configured": bool(data["qq_account"]),
                "group_scope": data["group_scope"], "private_scope": data["private_scope"], "groups": len(data["groups"]),
                "users": len(data["users"]) if data["private_scope"] == "selected" else 0,
                "memory_enabled": data["memory_enabled"], "python_version": sys.version.split()[0],
                "memory_bytes": sum(p.stat().st_size for p in (self.instance / "data").glob("*.db") if p.is_file())}

    def test_api(self):
        import httpx
        data = self.settings(private=True)
        if not data["has_api_key"]:
            raise ValueError("尚未填写 API Key")
        # 使用用户保存的明确地址，且不继承系统代理，避免把本地密钥交给未知代理。
        with httpx.Client(timeout=25, trust_env=False) as client:
            response = client.post(data["api_base"].rstrip("/") + "/chat/completions",
                                   headers={"Authorization": "Bearer " + data["api_key"]},
                                   json={"model": data["model"], "messages": [{"role": "user", "content": "只回复：连接成功"}],
                                         "max_tokens": 64, "thinking": {"type": "disabled"}})
        if response.status_code != 200:
            raise ValueError(f"模型服务返回 HTTP {response.status_code}，请检查地址、密钥、模型和余额")
        body = response.json()
        if not body.get("choices"):
            raise ValueError("服务未返回聊天结果，请检查是否为兼容的聊天接口")
        return {"message": "模型连接成功", "reply": body["choices"][0]["message"].get("content", ""), "usage": body.get("usage", {})}

    def check_qq(self):
        import aiohttp
        data = self.settings(private=True)
        async def check():
            timeout = aiohttp.ClientTimeout(total=6)
            async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
                async with session.ws_connect(f"http://{data['qq_host']}:{data['qq_port']}",
                                              headers={"Authorization": "Bearer " + data["qq_token"]}) as ws:
                    await ws.send_json({"action": "get_login_info", "params": {}, "echo": "fatfish-check"})
                    for _ in range(30):
                        message = await ws.receive_json(timeout=4)
                        if message.get("echo") == "fatfish-check":
                            if message.get("status") != "ok":
                                raise ValueError("QQ 接口已连接，但登录信息查询失败")
                            info = message.get("data", {})
                            if str(info.get("user_id", "")) != data["qq_account"]:
                                raise ValueError("接口登录的 QQ 与配置中的小号不一致，请核对")
                            return {"message": "QQ 登录和账号核对成功", "nickname": info.get("nickname", "")}
                    raise ValueError("QQ 接口未返回登录信息")
        try:
            return asyncio.run(check())
        except (OSError, TimeoutError, aiohttp.ClientError):
            raise ValueError("未能连接 QQ，请启动 NapCat、完成小号登录并核对端口及令牌") from None

    def qq_friends(self):
        """只读获取好友名称与账号，供用户选择私聊范围，不发送消息。"""
        import aiohttp
        data = self.settings(private=True)

        async def load():
            async with asyncio.timeout(12):
                async with aiohttp.ClientSession(trust_env=False) as session:
                    async with session.ws_connect(f"http://{data['qq_host']}:{data['qq_port']}",
                                                  headers={"Authorization": "Bearer " + data["qq_token"]}) as ws:
                        async def query(action):
                            echo = "fatfish-friends-" + secrets.token_hex(8)
                            await ws.send_json({"action": action, "params": {}, "echo": echo})
                            while True:
                                message = await ws.receive_json(timeout=5)
                                if message.get("echo") == echo:
                                    if message.get("status") != "ok":
                                        raise ValueError("QQ 未能返回好友列表，请确认已登录后重试")
                                    return message.get("data")
                        info = await query("get_login_info")
                        if not isinstance(info, dict) or not info.get("user_id"):
                            raise ValueError("QQ 尚未登录，请先扫码")
                        if data["qq_account"] and str(info["user_id"]) != data["qq_account"]:
                            raise ValueError("当前登录账号与已保存的小号不一致，请核对")
                        friends = await query("get_friend_list")
                        if not isinstance(friends, list):
                            raise ValueError("QQ 返回的好友列表格式不正确")
                        contacts = {}
                        for friend in friends:
                            if not isinstance(friend, dict):
                                continue
                            account = str(friend.get("user_id", ""))
                            if re.fullmatch(r"[1-9][0-9]{3,15}", account):
                                contacts[account] = {"qq": account, "name": str(friend.get("remark") or friend.get("nickname") or account)[:120]}
                        return {"friends": list(contacts.values())}
        try:
            return asyncio.run(load())
        except (OSError, TimeoutError, aiohttp.ClientError):
            raise ValueError("暂时无法读取 QQ 好友，请确认组件已启动并完成扫码登录，也可手动填写 QQ 号") from None

    def connection_info(self):
        data = self.settings(private=True)
        return {"address": f"ws://{data['qq_host']}:{data['qq_port']}", "token": data["qq_token"],
                "napcat_url": "http://127.0.0.1:6099", "docs": "https://napneko.github.io/guide/boot/Shell"}

    def advanced_info(self):
        if not (self.running() and tcp_open("127.0.0.1", 18001)):
            raise ValueError("请先启动核心并等待就绪")
        data = read_json(self.instance / "data" / "webui.json", {})
        return {"url": "http://127.0.0.1:18001", "token": data.get("access_token", "")}

    def open_qq_folder(self):
        directory = self.instance / "qq"
        if not directory.exists():
            raise ValueError("当前没有解压后的 QQ 组件，请先按官方安装说明下载 NapCat")
        if os.name == "nt":
            os.startfile(directory)
        return {"message": "已打开 QQ 组件目录。请按官方说明安装，并由你完成小号扫码登录"}

    def backup(self) -> Path:
        with self.lock:
            if self.running():
                raise ValueError("请先停止核心再备份，保证数据库和记忆状态一致")
            from fatfish.layout import personal_home
            target = personal_home(self.root) / "备份" / (self.instance.name + "-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S") + ".zip")
            target.parent.mkdir(exist_ok=True)
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
                for path in self.instance.rglob("*"):
                    if path.is_file() and not any(p in {".git", "__pycache__", "logs", "temp"} for p in path.relative_to(self.instance).parts):
                        archive.write(path, str(path.relative_to(self.instance)))
            return target
