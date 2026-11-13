"""千鱼跨私聊/群聊召回；不改变原生记忆格式与所属会话。"""
from typing import Any
import asyncio

from fatfish.shared_memory import enabled, recent_reference
from src.chat.message_receive.chat_manager import chat_manager
from src.common.paths import get_instance_root
from src.config.config import global_config
from src.person_info.person_info import get_person_id
from src.services.memory_service import memory_service


def sharing_enabled() -> bool:
    return enabled(get_instance_root())


def current_user(session: Any, anchor: Any = None) -> str:
    if not session.is_group_session:
        return str(session.user_id or "")
    message = anchor or (session.context.message if session.context else None)
    return str(message.message_info.user_info.user_id) if message else ""


def allows_source(source_id: str, session: Any, user_id: str) -> bool:
    if source_id == session.session_id:
        return True
    source = chat_manager.get_existing_session_by_session_id(source_id)
    if source is None or source.platform != session.platform or source.account_id != session.account_id:
        return False
    return source.is_group_session or (bool(user_id) and str(source.user_id or "") == user_id)


async def filter_hits(hits: list, session: Any, user_id: str) -> list:
    # Old paragraphs sometimes omit source metadata. Reuse the native read-only
    # preview API to resolve those hashes; unknown sources are not shared.
    from src.maisaka.memory.heuristic_injector import heuristic_memory_injector
    sources = await heuristic_memory_injector._resolve_hit_sources_by_hash(hits)
    selected = []
    current_person = get_person_id(session.platform, user_id) if user_id else ""
    for hit in hits:
        metadata = hit.metadata if isinstance(hit.metadata, dict) else {}
        source = str(metadata.get("source") or sources.get(hit.hash_value) or hit.source or "")
        source_id = str(metadata.get("chat_id") or "")
        if not source_id and source.startswith("chat_summary:"):
            source_id = source.split(":", 1)[1]
        if source_id:
            allowed = allows_source(source_id, session, user_id)
        elif source.startswith("person_fact:") or metadata.get("source_type") == "person_fact":
            person = str(metadata.get("person_id") or source.removeprefix("person_fact:"))
            allowed = bool(current_person and person == current_person)
        else:
            allowed = False
        if allowed:
            selected.append(hit)
    return selected


async def search_shared(query: str, *, session: Any, user_id: str, limit: int, **kwargs):
    result = await memory_service.search(query, chat_id="", user_id=user_id,
        group_id=str(session.group_id or ""), respect_filter=False, limit=20, **kwargs)
    if result.success and not result.filtered:
        result.hits = (await filter_hits(result.hits, session, user_id))[:limit]
        # A global summary may describe rejected hits. Only accepted evidence is
        # exposed to Planner/Replyer, including time/episode search routes.
        result.summary = ""
    return result


async def build_shared_reference(session_id: str, anchor: Any) -> str:
    if not await asyncio.to_thread(sharing_enabled):
        return ""
    session = chat_manager.get_existing_session_by_session_id(session_id)
    if session is None:
        return ""
    user_id = current_user(session, anchor)
    recent = await asyncio.to_thread(recent_reference, get_instance_root(), platform=session.platform,
        user_id=user_id, session_id=session_id, bot_id=str(global_config.bot.qq_account),
        account_id=str(session.account_id or ""))
    query = str(anchor.processed_plain_text or "").strip()[:500]
    if query:
        result = await search_shared(query, session=session, user_id=user_id, limit=3, mode="search", person_id="")
        if result.success and result.hits:
            return recent + "\n【跨会话长期记忆-内部参考】\n" + "\n".join(hit.content[:500] for hit in result.hits)
    return recent
