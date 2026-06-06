"""Rewrite 模块 - 将用户原始输入 + 用户记忆整理为更清晰的规划上下文"""

from typing import Any

from backend.agent.time_utils import detect_time_window, extract_start_time
from backend.llm.deepseek_client import deepseek_client

REWRITE_SYSTEM_PROMPT = """你是一个本地生活助手的上下文整理模块。你需要把用户的原始输入和用户记忆整理成更清晰的规划上下文。

## 规则
1. **绝对不能新增用户没提到的领域**。例如：
   - 用户说"想吃清淡的" → 只能涉及 eat 领域，不能加 play/drink/delivery
   - 用户说"唱歌/展览/桌游等活动" → 只能涉及 play 领域，不能加 eat/drink/delivery
   - 用户明确说"安排下午"、"完整行程"、"玩完吃饭" → 才能扩展多个领域
2. 从用户记忆中补充的信息必须放在 inferred_facts 里，不要编造。
3. 不确定的信息放在 missing_info 里。
4. rewritten_message 应该用一句完整的话总结用户的真实意图和上下文。

## 输出 JSON 格式
{
  "rewritten_message": "一句完整的话，整合用户意图和记忆上下文",
  "explicit_facts": ["用户明确说的信息"],
  "inferred_facts": ["从记忆补充的信息"],
  "missing_info": ["缺失的信息"],
  "constraints": {
    "time_window_hint": "morning|lunch|afternoon|dinner|evening|night|null",
    "start_time_hint": "HH:MM|null",
    "domains_hint": ["eat", "play", "drink", "delivery"],
    "diet_hint": ["清淡", "健康", "低卡"],
    "radius_km_hint": 8
  }
}"""


def _detect_domains_from_message(message: str) -> list[str]:
    """从用户消息中检测明确提到的领域"""
    domains: list[str] = []
    eat_kw = ["吃", "饭", "餐厅", "美食", "火锅", "烧烤", "日料", "西餐", "中餐", "小吃",
              "清淡", "低卡", "健康餐", "素食", "海鲜", "面", "粉", "汤", "点心", "早餐",
              "午餐", "晚饭", "晚餐", "宵夜", "夜宵", "甜点"]
    play_kw = ["玩", "唱歌", "KTV", "电影", "展览", "博物馆", "美术馆", "游乐园", "公园", "运动",
               "健身", "游泳", "攀岩", "密室", "剧本杀", "桌游", "麻将", "逛街", "购物",
               "拍照", "打卡", "演出", "音乐会", "话剧", "脱口秀", "相声", "逛逛", "走走",
               "游览", "参观", "citywalk", "Citywalk", "来我的城市"]
    drink_kw = ["喝", "酒吧", "酒", "精酿", "鸡尾酒", "啤酒", "红酒", "清酒", "饮品",
                "茶馆", "喝茶", "咖啡", "咖啡厅", "咖啡馆", "奶茶", "奶茶店", "冷饮"]
    delivery_kw = ["外卖", "跑腿", "闪送", "配送", "送到", "送餐", "代买", "买菜", "超市",
                   "送奶茶", "送蛋糕", "送花", "送礼物", "送水果"]

    for kw in eat_kw:
        if kw in message:
            domains.append("eat")
            break
    for kw in play_kw:
        if kw in message:
            domains.append("play")
            break
    for kw in drink_kw:
        if kw in message:
            domains.append("drink")
            break
    for kw in delivery_kw:
        if kw in message:
            domains.append("delivery")
            break
    return domains


def _detect_time_window(message: str) -> str | None:
    """检测时间窗口"""
    return detect_time_window(message)


def _detect_diet(message: str) -> list[str]:
    """检测饮食偏好"""
    hints = []
    if any(kw in message for kw in ["清淡", "少油", "少盐", "不辣"]):
        hints.append("清淡")
    if any(kw in message for kw in ["低卡", "减脂", "减肥", "健康餐", "轻食", "沙拉"]):
        hints.append("低卡")
    if any(kw in message for kw in ["素食", "吃素", "斋"]):
        hints.append("素食")
    if any(kw in message for kw in ["火锅", "麻辣", "辣"]):
        hints.append("辣")
    if any(kw in message for kw in ["海鲜", "日料", "刺身", "寿司"]):
        hints.append("海鲜/日料")
    return hints


async def rewrite_message(
    message: str,
    user_profile: dict | None = None,
) -> dict[str, Any]:
    """Rewrite 用户消息，整合用户记忆上下文。

    返回:
        {
            "rewritten_message": str,
            "explicit_facts": list[str],
            "inferred_facts": list[str],
            "missing_info": list[str],
            "constraints": {
                "time_window_hint": str | None,
                "domains_hint": list[str],
                "diet_hint": list[str],
                "radius_km_hint": int | None,
            },
        }
    """
    user_profile = user_profile or {}
    domains = _detect_domains_from_message(message)
    time_window = _detect_time_window(message)
    start_time, inferred_window = extract_start_time(message)
    if inferred_window:
        time_window = inferred_window
    diet = _detect_diet(message)
    radius = user_profile.get("max_distance_km") or user_profile.get("radius_km")

    # 从用户记忆中提取可补充的信息
    inferred: list[str] = []
    home = user_profile.get("home_location") or user_profile.get("home", "")
    if home:
        inferred.append(f"家在{home}附近")
    child_age = user_profile.get("child_age")
    if child_age:
        inferred.append(f"有{child_age}岁孩子")
    pref = user_profile.get("preferences", {}) if isinstance(user_profile.get("preferences"), dict) else {}
    if pref.get("needs_low_calorie"):
        inferred.append("偏好低卡/健康饮食")
    if pref.get("child_friendly"):
        inferred.append("偏好亲子友好")

    # 尝试 LLM
    llm_result = None
    if deepseek_client.available:
        try:
            messages = [
                {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
                {"role": "user", "content": f"用户输入: {message}\n用户记忆: {user_profile}"},
            ]
            llm_resp = await deepseek_client.chat_json(messages, temperature=0.1)
            if llm_resp.ok and llm_resp.json_data:
                llm_result = llm_resp.json_data
                # 校验 LLM 没有非法扩展领域
                constraints = llm_result.setdefault("constraints", {})
                llm_domains = set(constraints.get("domains_hint", []))
                original_domains = set(domains)
                if llm_domains != original_domains:
                    # LLM 扩展了领域，强制修正
                    constraints["domains_hint"] = domains
                constraints.setdefault("time_window_hint", time_window)
                constraints.setdefault("start_time_hint", start_time)
        except Exception:
            llm_result = None

    if llm_result:
        return llm_result

    # 规则兜底
    facts = _extract_explicit_facts(message)
    rewritten = f"用户想在{time_window or '合适时段'}，" if time_window else "用户想"
    if home:
        rewritten += f"在{home}附近"
    if domains:
        rewritten += f"找{'、'.join(domains)}相关的内容。"
    else:
        rewritten += "整理一个本地生活安排。"
    rewritten += f"原始需求: {message}"

    return {
        "rewritten_message": rewritten,
        "explicit_facts": facts,
        "inferred_facts": inferred,
        "missing_info": ["人数未说明"] if "人" not in message and "位" not in message else [],
        "constraints": {
            "time_window_hint": time_window,
            "start_time_hint": start_time,
            "domains_hint": domains,
            "diet_hint": diet,
            "radius_km_hint": radius,
        },
    }


def _extract_explicit_facts(message: str) -> list[str]:
    """从消息中提取显式事实"""
    facts = []
    if any(kw in message for kw in ["中午", "午餐", "午饭"]):
        facts.append("中午")
    if any(kw in message for kw in ["下午", "午后"]):
        facts.append("下午")
    if any(kw in message for kw in ["晚餐", "晚饭", "晚上"]):
        facts.append("晚上")
    if "清淡" in message:
        facts.append("清淡")
    if "辣" in message:
        facts.append("辣")
    if any(kw in message for kw in ["低卡", "减脂", "健康"]):
        facts.append("健康/低卡")
    return facts
