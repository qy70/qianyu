"""阻止模型把内部聊天序列化记录当作 QQ 正文输出。"""
import re
import html

IMAGE_MARKUP = re.compile(r"<img\b[^>]*(?:>|$)|!\[[^\]]*\]\([^\n)]*\)|\[CQ:image,[^\]]*\]", re.I)
FAKE_IMAGE_URL = re.compile(r"https?://[^\s<>\"']*\.example(?:/[^\s<>\"']*)?", re.I)


def image_markers(text):
    return [match.group() for match in IMAGE_MARKUP.finditer(str(text or ""))]


def image_reference(marker):
    match = re.search(r'''\bsrc\s*=\s*["']([^"']+)["']''', marker, re.I)
    if not match:
        match = re.search(r"!\[[^\]]*\]\(([^)]*)\)", marker)
    if not match:
        match = re.search(r"\bfile=([^,\]]+)", marker)
    return html.unescape(match.group(1)) if match else ""

INTERNAL_OPEN = re.compile(r"<message\b(?=[^>]*(?:msg_id\s*=|time\s*=|user\s*=))[^>]*(?:>|$)", re.I | re.S)
INTERNAL_BLOCK = re.compile(r"<message\b(?=[^>]*(?:msg_id\s*=|time\s*=|user\s*=))[^>]*>.*?</message\s*>", re.I | re.S)
CLOSE = re.compile(r"</message\s*>", re.I)


def clean_reply(text):
    text = str(text or "")
    # 这里是 QQ 的正文出口，不会把 HTML/Markdown 解释成图片。
    # 已知图库标记由更早的社交 Hook 转成真图；残留标记均不能原样发出。
    image_leak = bool(IMAGE_MARKUP.search(text) or FAKE_IMAGE_URL.search(text))
    if image_leak:
        text = FAKE_IMAGE_URL.sub("", IMAGE_MARKUP.sub("", text)).strip()
        return "图片没有成功发送，我得通过发图工具重发。", True
    if not INTERNAL_OPEN.search(text) and re.search(r"<message\b[^>]*>", text, re.I):
        # 普通 XML 教学内容不带内部 msg_id/time/user 属性，不误伤。
        return text, False
    if not INTERNAL_OPEN.search(text) and not CLOSE.search(text):
        return text, False
    cleaned = INTERNAL_BLOCK.sub("", text)
    cleaned = INTERNAL_OPEN.sub("", cleaned)
    cleaned = CLOSE.sub("", cleaned)
    # 没有完整闭合时，余下文本可能仍是被抄出的历史消息，整段拒绝复述。
    if cleaned == text or (INTERNAL_OPEN.search(text) and not INTERNAL_BLOCK.search(text)):
        cleaned = ""
    return cleaned.strip() or "🐟", True
