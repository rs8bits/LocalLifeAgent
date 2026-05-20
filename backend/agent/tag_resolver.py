"""标签解析/对齐模块 - 将用户意图对齐到 tag_catalog 中的真实标签"""

import json
import re
from typing import Optional

from backend.config import DATA_DIR
from backend.agent.schemas import Intent
from backend.llm.deepseek_client import deepseek_client, LLMResult

TAG_CATALOG_FILE = "tag_catalog.json"


def _load_catalog() -> dict:
    file_path = DATA_DIR / TAG_CATALOG_FILE
    if not file_path.exists():
        return {"domains": {}}
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── 规则兜底解析 ──────────────────────────────────────────────

_PLAY_KEYWORDS = [
    "唱歌", "密室", "桌游", "拍照", "打卡", "电影", "蹦床", "撸猫",
    "KTV", "LiveHouse", "livehouse", "演出", "展览", "电竞", "公园",
    "户外", "亲子", "乐园", "逛街", "购物", "citywalk", "Citywalk",
    "玩", "活动",
]
_EAT_KEYWORDS = [
    "吃饭", "餐厅", "美食", "火锅", "烤肉", "日料", "晚餐", "午饭",
    "午饭", "晚饭", "聚餐", "用餐", "轻食", "健康餐",
]
_DRINK_KEYWORDS = [
    "喝", "咖啡", "奶茶", "茶饮", "精酿", "啤酒", "酒吧", "喝酒",
    "小酌", "果茶", "奶盖", "奈雪", "喜茶", "星巴克", "瑞幸",
]
_DELIVERY_KEYWORDS = [
    "外卖", "点个", "送餐", "送到", "送到餐厅", "配送", "闪送", "跑腿",
    "急送", "同城送", "蛋糕", "生日蛋糕", "鲜花", "花束", "礼物", "礼盒",
    "气球", "惊喜", "水果", "水果拼盘",
]

# 标签类别 → tag_catalog 真实标签 的规则映射
_ALIGN_RULES = {
    "play": {
        "唱歌": ["唱歌"],
        "KTV": ["唱歌"],
        "karaoke": ["唱歌"],
        "singing": ["唱歌"],
        "livehouse": ["音乐"],
        "LiveHouse": ["音乐"],
        "演出": ["音乐"],
        "拍照": ["拍照"],
        "photography": ["拍照"],
        "打卡": ["拍照"],
        "出片": ["拍照"],
        "密室": ["密室"],
        "桌游": ["桌游"],
        "board game": ["桌游"],
        "电影": ["观影"],
        "cinema": ["观影"],
        "movie": ["观影"],
        "电竞": ["电竞"],
        "esports": ["电竞"],
        "蹦床": ["运动"],
        "trampoline": ["运动"],
        "撸猫": ["撸猫"],
        "cat cafe": ["撸猫"],
        "户外": ["户外"],
        "outdoor": ["户外"],
        "展览": ["艺术"],
        "exhibition": ["艺术"],
        "购物": ["购物"],
        "shopping": ["购物"],
        "亲子": ["亲子"],
        "kids": ["亲子"],
        "child": ["亲子"],
    },
    "eat": {
        "美食": ["聚会"],
        "火锅": ["火锅"],
        "hotpot": ["火锅"],
        "烤肉": ["烤肉"],
        "bbq": ["烤肉"],
        "日料": ["日料"],
        "japanese": ["日料"],
        "sushi": ["日料"],
        "聚会": ["聚会"],
        "party": ["聚会"],
        "聚餐": ["聚会"],
        "健康": ["健康"],
        "healthy": ["健康"],
        "减脂": ["健康"],
        "低卡": ["健康"],
        "轻食": ["健康"],
        "拍照": ["拍照"],
        "photography": ["拍照"],
        "约会": ["约会"],
        "date": ["约会"],
        "高品质": ["高品质"],
        "fine dining": ["高品质"],
    },
    "drink": {
        "咖啡": ["coffee", "咖啡"],
        "coffee": ["coffee", "咖啡"],
        "cafe": ["coffee", "咖啡"],
        "奶茶": ["milk_tea", "奶茶"],
        "milk tea": ["milk_tea", "奶茶"],
        "bubble tea": ["milk_tea", "奶茶"],
        "茶饮": ["tea", "奶茶"],
        "精酿": ["bar", "精酿"],
        "beer": ["bar", "精酿"],
        "酒吧": ["bar", "精酿"],
        "bar": ["bar", "精酿"],
        "喝酒": ["bar", "精酿"],
        "小酌": ["bar", "精酿"],
        "拍照": ["拍照"],
        "网红": ["网红"],
    },
    "delivery": {
        "外卖": ["外卖"],
        "takeout": ["外卖"],
        "food delivery": ["外卖"],
        "送餐": ["外卖"],
        "送到餐厅": ["外卖"],
        "送到": ["外卖"],
        "配送": ["闪送"],
        "闪送": ["闪送"],
        "flash delivery": ["闪送"],
        "跑腿": ["闪送"],
        "急送": ["闪送"],
        "蛋糕": ["cake", "蛋糕"],
        "生日蛋糕": ["cake", "蛋糕"],
        "cake": ["cake", "蛋糕"],
        "鲜花": ["flower", "鲜花"],
        "花束": ["flower", "鲜花"],
        "flower": ["flower", "鲜花"],
        "礼物": ["gift", "儿童礼物"],
        "礼盒": ["gift", "儿童礼物"],
        "气球": ["gift", "儿童礼物"],
        "惊喜": ["惊喜"],
        "水果": ["fruit", "水果"],
        "水果拼盘": ["fruit", "水果"],
        "轻食": ["food", "轻食"],
        "低卡": ["food", "低卡"],
        "奶茶": ["drink", "奶茶"],
    },
}


def _rule_resolve_domains(message: str, intent: Intent) -> dict:
    """规则兜底：直接从用户消息和意图中解析领域需求"""
    prefs = intent.drink_preferences or []
    act_prefs = intent.activity_preferences or []
    food_prefs = intent.food_preferences or []

    # required 表示用户明确提出的领域；domains 可以包含系统补充的可选领域。
    required_play = _contains_keyword(message, _PLAY_KEYWORDS) or len(act_prefs) > 0
    required_eat = _contains_keyword(message, _EAT_KEYWORDS) or intent.needs_low_calorie
    required_drink = _contains_keyword(message, _DRINK_KEYWORDS) or len(prefs) > 0
    required_delivery = _contains_keyword(message, _DELIVERY_KEYWORDS) or len(intent.delivery_preferences or []) > 0

    domains: list[str] = []
    if required_play:
        domains.append("play")
    if required_eat:
        domains.append("eat")
    if required_drink:
        domains.append("drink")
    if required_delivery:
        domains.append("delivery")

    # 泛化的“安排一下/出去几个小时”没有明确领域时，默认给玩+吃的综合方案。
    if not domains:
        domains.extend(["play", "eat"])
        required_play = True
        required_eat = True

    # 用户只说“出去玩”时，吃饭作为可选补充进入规划，但不要变成红框级 required。
    if required_play and intent.scene in ("family", "friends") and "eat" not in domains:
        domains.append("eat")

    result = {
        "domains": domains,
        "domain_tags": {"play": [], "eat": [], "drink": [], "delivery": []},
        "domain_sub_categories": {"play": [], "eat": [], "drink": [], "delivery": []},
        "domain_required": {
            "play": required_play,
            "eat": required_eat,
            "drink": required_drink,
            "delivery": required_delivery,
        },
        "explanations": [],
    }

    # 对齐 play 标签
    if "play" in domains:
        raw_tags = act_prefs + _extract_play_keywords(message)
        _align_domain("play", raw_tags, result)

    # 对齐 eat 标签
    if "eat" in domains:
        raw_tags = food_prefs + _extract_eat_keywords(message)
        _align_domain("eat", raw_tags, result)

    # 对齐 drink 标签
    if "drink" in domains:
        raw_prefs = prefs + _extract_drink_keywords(message)
        _align_domain("drink", raw_prefs, result)

    if "delivery" in domains:
        raw_delivery = (intent.delivery_preferences or []) + _extract_delivery_keywords(message)
        _align_domain("delivery", raw_delivery, result)

    return result


def _contains_keyword(message: str, keywords: list[str]) -> bool:
    msg_lower = message.lower()
    return any(kw in message or kw.lower() in msg_lower for kw in keywords)


def _extract_play_keywords(message: str) -> list[str]:
    found = []
    for kw in _PLAY_KEYWORDS:
        if kw in message:
            found.append(kw)
    return found


def _extract_eat_keywords(message: str) -> list[str]:
    found = []
    for kw in _EAT_KEYWORDS:
        if kw in message:
            found.append(kw)
    return found


def _extract_drink_keywords(message: str) -> list[str]:
    found = []
    for kw in _DRINK_KEYWORDS:
        if kw in message:
            found.append(kw)
    return found


def _extract_delivery_keywords(message: str) -> list[str]:
    found = []
    for kw in _DELIVERY_KEYWORDS:
        if kw in message:
            found.append(kw)
    return found


def _align_domain(domain: str, raw_keywords: list[str], result: dict) -> None:
    """将原始关键词对齐到 tag_catalog 中的真实标签和子品类"""
    rules = _ALIGN_RULES.get(domain, {})
    matched_tags: set[str] = set()
    matched_sub_cats: set[str] = set()

    for kw in raw_keywords:
        mapped = rules.get(kw)
        if mapped:
            for m in mapped:
                # 检查是标签还是子品类
                if m in ("bar", "coffee", "milk_tea", "tea", "food", "drink", "cake", "flower", "fruit", "gift"):
                    matched_sub_cats.add(m)
                else:
                    matched_tags.add(m)
            result["explanations"].append(f"'{kw}' 对齐到 {domain} 标签: {mapped}")
        else:
            # 直接尝试匹配
            catalog = _load_catalog()
            domain_info = catalog.get("domains", {}).get(domain, {})
            if kw in domain_info.get("tags", []):
                matched_tags.add(kw)
            elif kw in domain_info.get("categories", []):
                matched_tags.add(kw)
            elif kw in domain_info.get("sub_categories", []):
                matched_sub_cats.add(kw)

    result["domain_tags"][domain] = list(matched_tags)
    result["domain_sub_categories"][domain] = list(matched_sub_cats)


# ── LLM 辅助解析 ──────────────────────────────────────────────

TAG_RESOLVE_SYSTEM_PROMPT = """你是一个标签对齐器。根据用户输入和可用标签目录，输出对齐后的标签。仅输出 JSON：

{
  "domains": ["play", "eat", "drink", "delivery"],
  "domain_tags": {
    "play": [],
    "eat": [],
    "drink": [],
    "delivery": []
  },
  "domain_sub_categories": {
    "play": [],
    "eat": [],
    "drink": [],
    "delivery": []
  },
  "domain_required": {
    "play": true,
    "eat": true,
    "drink": true,
    "delivery": true
  },
  "explanations": []
}

规则：
- 只使用给定的可用标签和子品类，不允许编造。
- domain_required 判断用户是否明确要求该领域（说了唱歌→play required，说了吃饭→eat required，说了喝→drink required，说了外卖/闪送/蛋糕/鲜花→delivery required）。
- 英文输入应对齐到中文标签。
"""


async def _llm_resolve(message: str, intent_dict: dict, catalog: dict) -> Optional[dict]:
    """使用 LLM 做标签对齐"""
    if not deepseek_client.available:
        return None
    try:
        # 构造简化的 catalog 给 LLM
        simplified = {}
        for domain_name, info in catalog.get("domains", {}).items():
            simplified[domain_name] = {
                "tags": info.get("tags", []),
                "categories": info.get("categories", []),
                "sub_categories": info.get("sub_categories", []),
            }
        msgs = [
            {"role": "system", "content": TAG_RESOLVE_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps({
                "message": message,
                "intent": intent_dict,
                "catalog": simplified,
            }, ensure_ascii=False)},
        ]
        result: LLMResult = await deepseek_client.chat_json(msgs, temperature=0.1)
        if result.ok and isinstance(result.json_data, dict):
            return result.json_data
        return None
    except Exception:
        return None


def _validate_resolve(result: dict, catalog: dict) -> dict:
    """确保解析结果中的标签都存在于 catalog 中"""
    domains_info = catalog.get("domains", {})
    allowed_domains = {"play", "eat", "drink", "delivery"}
    result["domains"] = [
        d for d in result.get("domains", [])
        if d in allowed_domains and d in domains_info
    ]
    result.setdefault("domain_required", {})
    for domain_name in allowed_domains:
        result["domain_required"][domain_name] = bool(
            result["domain_required"].get(domain_name, False)
        )
    for domain_name in allowed_domains:
        info = domains_info.get(domain_name, {})
        valid_tags = set(info.get("tags", [])) | set(info.get("categories", []))
        valid_sub_cats = set(info.get("sub_categories", []))
        result.setdefault("domain_tags", {}).setdefault(domain_name, [])
        result.setdefault("domain_sub_categories", {}).setdefault(domain_name, [])
        result["domain_tags"][domain_name] = [
            t for t in result["domain_tags"][domain_name] if t in valid_tags
        ]
        result["domain_sub_categories"][domain_name] = [
            s for s in result["domain_sub_categories"][domain_name] if s in valid_sub_cats
        ]
    return result


# ── 主入口 ────────────────────────────────────────────────────

async def resolve_domain_tags(
    message: str, intent: Intent, intent_dict: dict
) -> dict:
    """解析用户领域需求和对齐标签。LLM 优先，规则兜底。"""
    catalog = _load_catalog()

    # 规则兜底总是可用
    rule_result = _rule_resolve_domains(message, intent)

    # LLM 尝试
    llm_result = await _llm_resolve(message, intent_dict, catalog)
    if llm_result:
        llm_result = _validate_resolve(llm_result, catalog)
        # LLM 只做增强，不允许把规则已识别出的领域误删。
        merged_domains = []
        for domain_name in rule_result.get("domains", []) + llm_result.get("domains", []):
            if domain_name in ("play", "eat", "drink", "delivery") and domain_name not in merged_domains:
                merged_domains.append(domain_name)
        rule_result["domains"] = merged_domains
        for domain_name in ["play", "eat", "drink", "delivery"]:
            rule_required = rule_result.get("domain_required", {}).get(domain_name, False)
            llm_required = llm_result.get("domain_required", {}).get(domain_name, False)
            rule_result["domain_required"][domain_name] = bool(rule_required or llm_required)
        # 合并标签
        for domain_name in ["play", "eat", "drink", "delivery"]:
            llm_tags = set(llm_result.get("domain_tags", {}).get(domain_name, []))
            rule_tags = set(rule_result.get("domain_tags", {}).get(domain_name, []))
            rule_result["domain_tags"][domain_name] = list(llm_tags | rule_tags)
            llm_sub = set(llm_result.get("domain_sub_categories", {}).get(domain_name, []))
            rule_sub = set(rule_result.get("domain_sub_categories", {}).get(domain_name, []))
            rule_result["domain_sub_categories"][domain_name] = list(llm_sub | rule_sub)
        # 合并解释
        rule_result.setdefault("explanations", [])
        for exp in llm_result.get("explanations", []):
            if exp not in rule_result["explanations"]:
                rule_result["explanations"].append(exp)

    return rule_result
