from pathlib import Path
import asyncio

from maibot_sdk import HookHandler, MaiBotPlugin
from .style_library import StyleLibrary
from fatfish.knowledge import KnowledgeLibrary
from fatfish.reply_guard import clean_reply


class QianyuStylePlugin(MaiBotPlugin):
    async def on_load(self):
        self.library = StyleLibrary(Path(__file__).resolve().parents[2] / "persona" / "style-pack")
        self.knowledge = KnowledgeLibrary(Path(__file__).resolve().parents[2])
        await asyncio.to_thread(self.knowledge.refresh)
        self.ctx.logger.info("大肥鱼资料扩展已加载；本实例风格包%s", "已启用" if self.library.enabled() else "未启用")

    async def on_unload(self):
        self.library.recent.clear()

    async def on_config_update(self, scope, config_data, version):
        # 风格内容来自本实例的 Markdown/JSON，每次回复读取，可直接调整。
        self.library.recent.clear()

    @HookHandler("maisaka.replyer.before_request", name="natural_chat", description="读取用户自定义资料与表达参考", timeout_ms=2500)
    async def natural_chat(self, **kwargs):
        text = ""
        message_id = str(kwargs.get("reply_message_id") or "")
        session = str(kwargs.get("session_id") or "")
        if message_id:
            try:
                result = await asyncio.wait_for(self.ctx.message.get_by_id(message_id, chat_id=session), timeout=1.2)
                message = result.get("message") if isinstance(result, dict) else None
                if isinstance(message, dict):
                    text = str(message.get("processed_plain_text") or "")
                    if not text:
                        text = " ".join(str(part.get("data", "")) for part in message.get("raw_message", []) if isinstance(part, dict) and part.get("type") == "text")
            except Exception:
                self.ctx.logger.debug("目标消息暂不可读，本轮使用回复方向选择风格")
        reason = str(kwargs.get("reply_reason") or "")
        if not text:
            # 无法读取目标时仍检查回复方向中的场景，避免给严肃求助配上嘲讽例子。
            text = reason
        prompt, selected = self.library.build(text, session, message_id, reason) if self.library.enabled() else ("", [])
        knowledge_prompt = await asyncio.to_thread(self.knowledge.build, text + " " + reason)
        protocol_rule = "只输出当前对对方的回复。聊天记录标签是内部输入格式，不得复述。QQ 不会把 HTML img、Markdown 图片或图片网址变成真实图片；需要发表情必须调用 qianyu_sticker(query=情绪)，例如爱心、喜欢、开心。不得编造 qianyu.example 等地址，不得用代码、链接或括号旁白假装已经发图。表情工具发过真图后本轮完成，不再抄写历史原文。"
        if not self.library.enabled():
            # 未选择风格时只保留消息/工具协议，不注入角色名或表情偏好。
            protocol_rule = "聊天记录标签是内部输入格式，不得复述。不得将虚构地址、图片标记或文字冒充已发送的图片；只有工具成功回执能证明实际发送。"
        prompt = "\n\n".join(p for p in (prompt, knowledge_prompt, protocol_rule) if p)
        if not prompt:
            return {"action": "continue"}
        modified = dict(kwargs)
        modified.pop("hook_name", None)
        existing = str(modified.get("extra_prompt") or "")
        modified["extra_prompt"] = existing + ("\n\n" if existing else "") + prompt
        self.ctx.logger.info("大肥鱼资料参考已注入，范例=%s，资料=%s", ",".join(selected) or "无", bool(knowledge_prompt))
        return {"action": "continue", "modified_kwargs": modified}

    @HookHandler("maisaka.reply.before_post_process", name="guard_reply", description="在拆句前移除内部消息记录泄漏", timeout_ms=1000)
    async def guard_reply(self, **kwargs):
        cleaned, changed = clean_reply(kwargs.get("response", ""))
        if not changed:
            return {"action": "continue"}
        modified = {k:v for k,v in kwargs.items() if k != "hook_name"}
        modified.update(response=cleaned, enable_splitter=False, enable_chinese_typo=False)
        self.ctx.logger.warning("已拦截内部消息标签，未将原文发送到 QQ")
        return {"action":"continue", "modified_kwargs":modified}

    @HookHandler("send_service.before_send", name="guard_wire", description="发送前兜底拦截残留内部消息标签", timeout_ms=1000)
    async def guard_wire(self, **kwargs):
        message = kwargs.get("message") or {}
        fragments = [message.get("processed_plain_text", "")]
        for part in message.get("raw_message", []):
            if isinstance(part, dict) and part.get("type") == "text":
                fragments.append(part.get("data", ""))
        if any(clean_reply(value)[1] for value in fragments if isinstance(value, str)):
            return {"action":"abort"}
        return {"action":"continue"}


def create_plugin():
    return QianyuStylePlugin()
