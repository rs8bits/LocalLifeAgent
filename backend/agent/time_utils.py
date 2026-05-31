"""中文时间表达解析与时间段归一化工具。"""

from __future__ import annotations

import re


TIME_WINDOWS = {"morning", "lunch", "afternoon", "dinner", "evening", "night", "unknown"}

TIME_WINDOW_ALIASES = {
    "breakfast": "morning",
    "am": "morning",
    "noon": "lunch",
    "midday": "lunch",
    "午间": "lunch",
    "午餐": "lunch",
    "午饭": "lunch",
    "dinner": "dinner",
    "supper": "dinner",
    "晚餐": "dinner",
    "晚饭": "dinner",
    "night": "night",
    "late_night": "night",
    "unknown": "unknown",
}

_CN_NUM = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}

_PERIOD_WORDS = "上午|早上|清晨|中午|午间|下午|午后|傍晚|晚上|今晚|晚间|夜里|夜间|凌晨"


def normalize_time_window(value: str | None, default: str = "unknown") -> str:
    """把 LLM/规则可能给出的时间段统一到内部枚举。"""
    if not value:
        return default
    normalized = TIME_WINDOW_ALIASES.get(str(value).strip(), str(value).strip())
    return normalized if normalized in TIME_WINDOWS else default


def detect_time_window(message: str) -> str | None:
    """从中文文本中识别粗粒度时间段。"""
    if any(kw in message for kw in ["早餐", "早饭", "早点", "上午", "早上", "清晨"]):
        return "morning"
    if any(kw in message for kw in ["午餐", "午饭", "中午", "午间"]):
        return "lunch"
    if any(kw in message for kw in ["晚餐", "晚饭"]):
        return "dinner"
    if any(kw in message for kw in ["晚上", "今晚", "傍晚"]) and any(
        kw in message for kw in ["吃", "饭", "餐厅", "聚餐", "用餐"]
    ):
        return "dinner"
    if any(kw in message for kw in ["宵夜", "夜宵", "深夜", "半夜", "凌晨"]):
        return "night"
    if any(kw in message for kw in ["下午", "午后"]):
        return "afternoon"
    if any(kw in message for kw in ["傍晚", "晚上", "今晚", "晚间", "夜间", "夜里"]):
        return "evening"
    return None


def extract_start_time(message: str) -> tuple[str | None, str | None]:
    """识别 15:30、下午三点、两点半 等表达，返回 (HH:MM, inferred_window)。"""
    numeric_match = re.search(
        rf"(?:(?P<period>{_PERIOD_WORDS})\s*)?(?P<hour>[01]?\d|2[0-3])\s*[:：]\s*(?P<minute>[0-5]\d)",
        message,
    )
    if numeric_match:
        hour = int(numeric_match.group("hour"))
        minute = int(numeric_match.group("minute"))
        normalized = _normalize_clock(hour, minute, numeric_match.group("period"), message)
        if normalized:
            return normalized, infer_time_window_from_clock(normalized)

    point_match = re.search(
        rf"(?:(?P<period>{_PERIOD_WORDS})\s*)?"
        r"(?P<hour>[零〇一二两三四五六七八九十\d]{1,3})\s*点"
        r"(?P<minute>半|一刻|三刻|[零〇一二两三四五六七八九十\d]{1,3}\s*分?)?",
        message,
    )
    if not point_match:
        return None, None

    hour = _parse_number(point_match.group("hour"))
    minute = _parse_minute(point_match.group("minute"))
    if hour is None or minute is None:
        return None, None
    normalized = _normalize_clock(hour, minute, point_match.group("period"), message)
    if not normalized:
        return None, None
    return normalized, infer_time_window_from_clock(normalized)


def infer_time_window_from_clock(start_time: str) -> str:
    """根据 HH:MM 推断时间段。"""
    try:
        hour, minute = [int(part) for part in start_time.split(":", 1)]
    except (ValueError, AttributeError):
        return "unknown"
    total = hour * 60 + minute
    if 5 * 60 <= total < 11 * 60:
        return "morning"
    if 11 * 60 <= total < 13 * 60 + 30:
        return "lunch"
    if 13 * 60 + 30 <= total < 17 * 60:
        return "afternoon"
    if 17 * 60 <= total < 19 * 60:
        return "dinner"
    if 19 * 60 <= total < 22 * 60:
        return "evening"
    return "night"


def _parse_number(value: str | None) -> int | None:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return int(value)
    if value in _CN_NUM:
        return _CN_NUM[value]
    if "十" in value:
        left, _, right = value.partition("十")
        tens = 1 if not left else _CN_NUM.get(left)
        ones = 0 if not right else _CN_NUM.get(right)
        if tens is None or ones is None:
            return None
        return tens * 10 + ones
    return None


def _parse_minute(value: str | None) -> int | None:
    if not value:
        return 0
    value = value.strip().replace(" ", "")
    if value == "半":
        return 30
    if value == "一刻":
        return 15
    if value == "三刻":
        return 45
    value = value.removesuffix("分钟").removesuffix("分")
    minute = _parse_number(value)
    if minute is None or not 0 <= minute <= 59:
        return None
    return minute


def _normalize_clock(hour: int, minute: int, period: str | None, message: str) -> str | None:
    if not 0 <= minute <= 59:
        return None

    window = detect_time_window(message)
    if period in {"下午", "午后"} or (not period and window == "afternoon"):
        if 1 <= hour < 12:
            hour += 12
    elif period in {"中午", "午间"} or (not period and window == "lunch"):
        if 1 <= hour <= 3:
            hour += 12
    elif period in {"傍晚", "晚上", "今晚", "晚间"} or (not period and window in {"dinner", "evening"}):
        if 1 <= hour < 12:
            hour += 12
    elif period in {"夜里", "夜间"} or (not period and window == "night"):
        if 1 <= hour < 12:
            hour += 12
    elif period == "凌晨":
        if hour == 12:
            hour = 0
    elif not period and window is None and 1 <= hour <= 7:
        # 本地生活规划里裸写“两点半/三点”更常表示下午。
        hour += 12

    if not 0 <= hour <= 23:
        return None
    return f"{hour:02d}:{minute:02d}"
