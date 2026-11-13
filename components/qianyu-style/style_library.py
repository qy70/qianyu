"""本地风格资料选择，不读写经历数据库，不调用网络或模型。"""

from collections import OrderedDict
from pathlib import Path
import hashlib
import json


class StyleLibrary:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.recent = OrderedDict()

    def read(self, name, limit):
        path = self.directory / name
        if path.stat().st_size > limit * 4:
            raise ValueError(f"风格文件过大：{name}")
        value = path.read_text(encoding="utf-8-sig")
        if len(value) > limit:
            raise ValueError(f"风格文件过长：{name}")
        return value

    def enabled(self):
        path = self.directory / "manifest.json"
        return path.is_file() and json.loads(self.read("manifest.json", 4000)).get("enabled") is True

    def build(self, text, session_id="", message_id="", reason=""):
        if not self.enabled():
            return "", []
        manifest = json.loads(self.read("manifest.json", 4000))
        # 情绪判断优先依据对方实际发言，Planner 的回复理由仅用于辅助检索。
        text = str(text or "")[-5000:]
        query = text + "\n" + str(reason or "")[-1500:]
        comfort_words = ("去世", "葬礼", "抑郁", "想死", "自杀", "不想活", "别开玩笑", "别调侃", "不想被嘲讽", "很难过", "很崩溃", "被欺负", "我很害怕")
        mode = "comfort" if any(word in text for word in comfort_words) else "normal"
        if mode == "normal" and any(word in text for word in ("地狱笑话", "黑色幽默", "来个黑的", "讲个黑", "来个地狱")):
            mode = "dark"
        if mode == "normal" and any(word in text for word in ("报错", "怎么修", "怎么弄", "为什么打不开", "帮我看看", "求助")):
            mode = "help"
        rows = []
        for line in self.read("examples.jsonl", 80000).splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row.get("keywords"), list) or not row.get("id") or not row.get("reply"):
                continue
            if mode == "comfort" and row.get("mode") != "comfort":
                continue
            if mode != "comfort" and row.get("mode") == "comfort":
                continue
            if row.get("mode") == "dark" and mode != "dark":
                continue
            score = sum(min(len(word), 6) for word in row["keywords"] if isinstance(word, str) and word in query)
            if row.get("mode") == mode and mode in {"comfort", "dark", "help"}:
                score += 12
            if score:
                tie = hashlib.sha256((session_id + message_id + row["id"]).encode()).hexdigest()
                rows.append((score, tie, row))
        previous = self.recent.get(session_id, [])
        rows.sort(key=lambda item: (item[2]["id"] not in previous, item[0], item[1]), reverse=True)
        count = max(1, min(4, int(manifest.get("max_examples", 3))))
        chosen = [row for _, _, row in rows[:count]]
        ids = [row["id"] for row in chosen]
        self.recent[session_id] = (previous + ids)[-12:]
        self.recent.move_to_end(session_id)
        if len(self.recent) > 128:
            self.recent.popitem(last=False)
        rules = self.read("natural-chat.md", 6000) + "\n\n" + self.read("dialogue-distill.md", 4000)
        mode_rule = {
            "normal": "根据当前问题和用户选择的风格回应。",
            "dark": "根据对方明确提出的创作要求回应，示例不代表真实经历。",
            "help": "先回应实际问题，缺少必要信息时再询问。",
            "comfort": "根据对方表达的处境与需要回应。",
        }[mode]
        # 场景只负责选例；具体语气可由本实例选择的风格包提供。
        scene_rules = manifest.get("scene_rules")
        if isinstance(scene_rules, dict):
            custom_rule = scene_rules.get(mode)
            if isinstance(custom_rule, str) and custom_rule.strip():
                mode_rule = custom_rule.strip()
        prompt = "【用户自定义表达参考】\n" + rules + "\n\n本轮场景：" + mode_rule
        if chosen:
            prompt += "\n\n【按场景取出的表达范例】\n这些是写法示范，不是真实经历；参考回应方式，重新组织当前回复，不背诵、不自称来自语料库。\n"
            for row in chosen:
                prompt += f"情境：{row['situation']}\n示范：{row['reply']}\n技巧：{row.get('technique', '')}\n\n"
        return prompt, ids
