"""多轮方案修改：把上一轮规划上下文与用户修改建议合并成新需求。"""

from __future__ import annotations

import re
from typing import Any


def build_revision_message(session: dict[str, Any], revision_message: str) -> str:
    """构造用于重新规划的消息。

    这里不直接复用旧 intent，因为用户的修改建议通常是在纠正上一轮错误。
    新消息保留上一轮原始需求，再明确声明“以本次修改为准”。
    """
    previous_message = str(session.get("message") or "").strip()
    revision = revision_message.strip()
    if not previous_message:
        return revision

    cleaned_previous = previous_message
    if _negates_child(revision):
        cleaned_previous = _remove_child_mentions(cleaned_previous)

    parts = [
        f"上一轮需求：{cleaned_previous}",
        f"用户本轮修改：{revision}",
        "请以用户本轮修改为准，重新安排方案。",
    ]
    return "。".join(part for part in parts if part)


def _negates_child(message: str) -> bool:
    patterns = [
        r"不带(小孩|孩子|儿童|宝宝|娃)",
        r"没带(小孩|孩子|儿童|宝宝|娃)",
        r"没有(小孩|孩子|儿童|宝宝|娃)",
        r"无(小孩|孩子|儿童|宝宝|娃)",
        r"不.*亲子",
        r"不是亲子",
        r"不要亲子",
    ]
    return any(re.search(pattern, message) for pattern in patterns)


def _remove_child_mentions(message: str) -> str:
    replacements = [
        r"孩子\s*\d+\s*岁",
        r"\d+\s*岁\s*(孩子|宝宝|小朋友)",
        r"带?(老婆|老公|妻子|丈夫)?孩子",
        r"亲子(乐园|活动|场景|友好)?",
        r"宝宝",
        r"小朋友",
        r"儿童",
    ]
    cleaned = message
    for pattern in replacements:
        cleaned = re.sub(pattern, "", cleaned)
    cleaned = re.sub(r"[，,。；;]\s*[，,。；;]+", "，", cleaned)
    return cleaned.strip("，,。；; ")
