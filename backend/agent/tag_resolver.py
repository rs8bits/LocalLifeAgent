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
    "玩", "活动", "约会", "纪念日", "仪式感", "手作", "香氛",
    "逛逛", "逛一逛", "走走", "游览", "参观", "博物馆", "美术馆",
    "来我的城市", "带他们逛", "小吃街", "市集", "citywalk小吃",
]
_EAT_KEYWORDS = [
    "吃饭", "餐厅", "美食", "火锅", "烤肉", "日料", "晚餐", "午饭",
    "午饭", "晚饭", "聚餐", "用餐", "轻食", "健康餐",
    "午餐", "吃点", "吃点儿", "清淡", "想吃", "下午茶", "约会",
    "纪念日", "仪式感", "高端", "景观", "西餐", "包间", "宴请",
    "小吃", "小吃街", "citywalk小吃", "夜宵",
]
_DRINK_KEYWORDS = [
    "喝", "咖啡", "奶茶", "茶饮", "精酿", "啤酒", "酒吧", "喝酒",
    "小酌", "果茶", "奶盖", "奈雪", "喜茶", "星巴克", "瑞幸",
    "约会", "纪念日", "安静", "高端", "下午茶", "茶馆", "喝茶",
]
_DELIVERY_KEYWORDS = [
    "外卖", "点个", "送餐", "送到", "送到餐厅", "配送", "闪送", "跑腿",
    "急送", "同城送", "蛋糕", "生日蛋糕", "鲜花", "花束", "礼物", "礼盒",
    "气球", "惊喜", "水果", "水果拼盘", "纪念日", "仪式感",
]

# 标签类别 → tag_catalog 真实标签/类目/子品类 的规则映射
_ALIGN_RULES = {
    "play": {
        "唱歌": ["KTV", "唱歌"],
        "KTV": ["KTV", "唱歌"],
        "karaoke": ["KTV", "唱歌"],
        "singing": ["KTV", "唱歌"],
        "livehouse": ["LiveHouse", "音乐"],
        "LiveHouse": ["LiveHouse", "音乐"],
        "演出": ["LiveHouse", "音乐"],
        "拍照": ["拍照"],
        "photography": ["拍照"],
        "打卡": ["拍照"],
        "出片": ["拍照"],
        "密室": ["密室逃脱", "密室"],
        "桌游": ["桌游", "社交"],
        "board game": ["桌游", "社交"],
        "电影": ["影院", "观影"],
        "cinema": ["影院", "观影"],
        "movie": ["影院", "观影"],
        "电竞": ["电竞馆", "电竞"],
        "esports": ["电竞馆", "电竞"],
        "蹦床": ["运动馆", "运动"],
        "trampoline": ["运动馆", "运动"],
        "健身": ["运动馆", "运动"],
        "撸猫": ["撸猫馆", "撸猫"],
        "cat cafe": ["撸猫馆", "撸猫"],
        "户外": ["公园", "户外"],
        "outdoor": ["公园", "户外"],
        "展览": ["展览", "艺术"],
        "exhibition": ["展览", "艺术"],
        "购物": ["商场", "购物"],
        "shopping": ["商场", "购物"],
        "亲子": ["亲子乐园", "亲子"],
        "kids": ["亲子乐园", "亲子"],
        "child": ["亲子乐园", "亲子"],
        "逛逛": ["散步", "户外"],
        "逛一逛": ["散步", "户外"],
        "走走": ["散步", "户外"],
        "游览": ["散步", "历史文化"],
        "参观": ["展览", "历史文化", "安静"],
        "博物馆": ["展览", "历史文化", "安静"],
        "美术馆": ["展览", "艺术", "安静"],
        "来我的城市": ["散步", "历史文化"],
        "带他们逛": ["散步", "历史文化"],
        "游玩": ["散步", "展览", "公园", "历史文化"],
        "小吃街": ["citywalk", "散步", "拍照"],
        "市集": ["citywalk", "散步", "拍照"],
        "citywalk小吃": ["citywalk", "散步", "拍照"],
        "sightseeing": ["历史文化", "散步", "展览"],
        "观光": ["历史文化", "散步", "展览"],
        "爸妈": ["长辈友好", "安静", "少走路"],
        "父母": ["长辈友好", "安静", "少走路"],
        "长辈友好": ["长辈友好", "安静", "少走路"],
        "少走路": ["少走路", "安静"],
        "好停车": ["好停车", "安静"],
        "约会": ["约会"],
        "纪念日": ["纪念日", "约会"],
        "仪式感": ["仪式感"],
        "高端": ["高端"],
        "安静": ["安静"],
        "手作": ["手作"],
        "香氛": ["香氛"],
        "独处": ["安静"],
        "商务": ["商务", "安静"],
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
        "健康": ["健康轻食", "健康"],
        "healthy": ["健康轻食", "健康"],
        "减脂": ["健康轻食", "健康", "减脂", "低卡", "轻食"],
        "低卡": ["健康轻食", "健康", "低卡", "轻食"],
        "轻食": ["健康轻食", "健康", "轻食"],
        "拍照": ["拍照"],
        "photography": ["拍照"],
        "约会": ["约会"],
        "date": ["约会"],
        "高品质": ["高品质"],
        "fine dining": ["高品质"],
        "清淡": ["健康轻食", "健康", "低卡", "轻食"],
        "纪念日": ["纪念日", "约会", "仪式感"],
        "仪式感": ["仪式感"],
        "高端": ["高端"],
        "安静": ["安静"],
        "包间": ["包间"],
        "少走路": ["少走路"],
        "好停车": ["好停车"],
        "长辈友好": ["长辈友好"],
        "爸妈": ["长辈友好", "少走路", "安静"],
        "父母": ["长辈友好", "少走路", "安静"],
        "商务": ["商务", "包间", "安静"],
        "景观": ["景观"],
        "西餐": ["西餐"],
        "下午茶": ["咖啡甜品", "下午茶"],
        "小吃": ["小吃", "聚会"],
        "小吃街": ["小吃", "聚会", "拍照"],
        "夜宵": ["小吃", "聚会"],
        "生日": ["生日"],
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
        "约会": ["约会"],
        "纪念日": ["纪念日", "约会"],
        "仪式感": ["仪式感"],
        "高端": ["高端"],
        "安静": ["安静"],
        "长辈友好": ["长辈友好", "安静"],
        "爸妈": ["长辈友好", "少走路", "安静"],
        "父母": ["长辈友好", "少走路", "安静"],
        "少走路": ["少走路", "安静"],
        "好停车": ["好停车"],
        "商务": ["商务", "安静"],
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
        "纪念日": ["纪念日", "约会", "仪式感", "鲜花", "惊喜"],
        "仪式感": ["仪式感"],
        "约会": ["约会", "鲜花"],
        "高端": ["高端"],
        "生日": ["cake", "蛋糕", "生日"],
    },
}


def _rule_resolve_domains(message: str, intent: Intent) -> dict:
    """规则兜底：直接从用户消息和意图中解析领域需求"""
    prefs = intent.drink_preferences or []
    act_prefs = intent.activity_preferences or []
    food_prefs = intent.food_preferences or []
    delivery_prefs = intent.delivery_preferences or []

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

    occasion_full_plan = _needs_occasion_full_plan(message, intent)
    if occasion_full_plan:
        for domain_name in ["play", "eat", "drink", "delivery"]:
            if domain_name not in domains:
                domains.append(domain_name)
        required_play = required_play or _needs_composite_plan(message)
        required_eat = required_eat or _needs_composite_plan(message)

    # 只有用户表达“帮我安排几个小时/完整下午”时，才把吃饭作为可选补充。
    if (
        required_play
        and intent.party_type in {"family_with_child", "family_elder", "family", "friends", "couple", "business"}
        and "eat" not in domains
        and _needs_composite_plan(message)
    ):
        domains.append("eat")

    # 完整/半天行程可以把茶饮咖啡作为可选休息点，尤其适合长辈或家庭场景。
    if (
        _needs_composite_plan(message)
        and "play" in domains
        and "eat" in domains
        and "drink" not in domains
        and intent.party_type in {"family_elder", "family", "family_with_child", "couple", "friends"}
    ):
        domains.append("drink")

    result = {
        "domains": domains,
        "domain_categories": {"play": [], "eat": [], "drink": [], "delivery": []},
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
        raw_tags = intent.tags + act_prefs + _extract_play_keywords(message)
        _align_domain("play", raw_tags, result)

    # 对齐 eat 标签
    if "eat" in domains:
        raw_tags = intent.tags + food_prefs + _extract_eat_keywords(message)
        _align_domain("eat", raw_tags, result)

    # 对齐 drink 标签
    if "drink" in domains:
        raw_prefs = intent.tags + prefs + _extract_drink_keywords(message)
        _align_domain("drink", raw_prefs, result)

    if "delivery" in domains:
        raw_delivery = intent.tags + delivery_prefs + _extract_delivery_keywords(message)
        _align_domain("delivery", raw_delivery, result)

    _refresh_domain_specs(result)
    return result


def _contains_keyword(message: str, keywords: list[str]) -> bool:
    msg_lower = message.lower()
    return any(kw in message or kw.lower() in msg_lower for kw in keywords)


def _needs_composite_plan(message: str) -> bool:
    keywords = [
        "安排一下", "规划", "几个小时", "一下午", "下午空", "今天下午是空的",
        "完整方案", "行程", "半天", "去哪玩", "玩完", "吃饭前后",
        "逛逛", "逛一逛", "走走", "游览", "参观", "来我的城市", "带他们逛",
    ]
    return any(kw in message for kw in keywords)


def _needs_occasion_full_plan(message: str, intent: Intent) -> bool:
    occasion_tags = {"纪念日", "约会", "仪式感", "惊喜", "生日"}
    has_occasion = bool(occasion_tags.intersection(intent.tags)) or any(
        kw in message for kw in ["纪念日", "约会", "生日", "仪式感"]
    )
    if not has_occasion:
        return False
    if intent.party_type == "couple":
        return True
    return _needs_composite_plan(message)


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
    matched_categories: set[str] = set()
    matched_tags: set[str] = set()
    matched_sub_cats: set[str] = set()
    catalog = _load_catalog()
    domain_info = catalog.get("domains", {}).get(domain, {})
    valid_categories = set(domain_info.get("categories", []))
    valid_tags = set(domain_info.get("tags", []))
    valid_sub_cats = set(domain_info.get("sub_categories", []))

    for kw in raw_keywords:
        mapped = rules.get(kw)
        if mapped:
            for m in mapped:
                # 检查是标签还是子品类
                if m in valid_sub_cats:
                    matched_sub_cats.add(m)
                elif m in valid_categories:
                    matched_categories.add(m)
                elif m in valid_tags:
                    matched_tags.add(m)
                elif m in ("bar", "coffee", "milk_tea", "tea", "food", "drink", "cake", "flower", "fruit", "gift"):
                    matched_sub_cats.add(m)
                else:
                    matched_tags.add(m)
            result["explanations"].append(f"'{kw}' 对齐到 {domain} 标签: {mapped}")
        else:
            # 直接尝试匹配
            if kw in valid_tags:
                matched_tags.add(kw)
            elif kw in valid_categories:
                matched_categories.add(kw)
            elif kw in valid_sub_cats:
                matched_sub_cats.add(kw)

    result["domain_categories"][domain] = list(matched_categories)
    result["domain_tags"][domain] = list(matched_tags)
    result["domain_sub_categories"][domain] = list(matched_sub_cats)


def _refresh_domain_specs(result: dict) -> None:
    specs = []
    for domain_name in result.get("domains", []):
        categories = result.get("domain_categories", {}).get(domain_name, [])
        tags = result.get("domain_tags", {}).get(domain_name, [])
        sub_categories = result.get("domain_sub_categories", {}).get(domain_name, [])
        specs.append({
            "domain": domain_name,
            "required": bool(result.get("domain_required", {}).get(domain_name, False)),
            "categories": categories,
            "tags": tags,
            "sub_categories": sub_categories,
            "query_reason": _build_query_reason(domain_name, categories, tags, sub_categories),
        })
    result["domain_specs"] = specs


def _build_query_reason(
    domain_name: str,
    categories: list[str],
    tags: list[str],
    sub_categories: list[str],
) -> str:
    label = {"play": "玩", "eat": "吃", "drink": "喝", "delivery": "外卖/闪送"}.get(domain_name, domain_name)
    parts = []
    if categories:
        parts.append(f"类目={','.join(categories)}")
    if sub_categories:
        parts.append(f"子类目={','.join(sub_categories)}")
    if tags:
        parts.append(f"标签={','.join(tags)}")
    detail = "；".join(parts) if parts else "无额外标签，使用领域默认候选"
    return f"查询{label}领域：{detail}"


# ── LLM 辅助解析 ──────────────────────────────────────────────

TAG_RESOLVE_SYSTEM_PROMPT = """你是一个标签对齐器。根据用户输入和可用标签目录，先判断用户明确需要哪些业务领域，再输出对齐后的标签。仅输出 JSON：

{
  "domains": ["eat"],
  "domain_categories": {
    "play": [],
    "eat": ["健康轻食"],
    "drink": [],
    "delivery": []
  },
  "domain_tags": {
    "play": [],
    "eat": ["健康", "低卡", "轻食"],
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
    "play": false,
    "eat": true,
    "drink": false,
    "delivery": false
  },
  "domain_specs": [
    {
      "domain": "eat",
      "required": true,
      "categories": ["健康轻食"],
      "tags": ["健康", "低卡", "轻食"],
      "sub_categories": [],
      "query_reason": "用户明确说想吃清淡"
    }
  ],
  "explanations": []
}

规则：
- 只使用给定的可用标签和子品类，不允许编造。
- domains 只列出用户明确需要查询的领域；不要把 play/eat/drink/delivery 模板式全部返回。
- 未明确提到的领域必须省略，并把 domain_required 设为 false。
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
        valid_categories = set(info.get("categories", []))
        valid_tags = set(info.get("tags", [])) | valid_categories
        valid_sub_cats = set(info.get("sub_categories", []))
        result.setdefault("domain_categories", {}).setdefault(domain_name, [])
        result.setdefault("domain_tags", {}).setdefault(domain_name, [])
        result.setdefault("domain_sub_categories", {}).setdefault(domain_name, [])
        result["domain_categories"][domain_name] = [
            c for c in result["domain_categories"][domain_name] if c in valid_categories
        ]
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
        # 合并策略：
        # 1. 规则已明确的领域保留（有用户原话关键词支撑）
        # 2. LLM 新增领域必须同时满足：domain_required=true 且有有效标签/类目/子类目
        merged_domains = list(rule_result.get("domains", []))
        for domain_name in llm_result.get("domains", []):
            if domain_name in ("play", "eat", "drink", "delivery") and domain_name not in merged_domains:
                llm_required = llm_result.get("domain_required", {}).get(domain_name, False)
                has_valid_signals = any([
                    llm_result.get("domain_categories", {}).get(domain_name, []),
                    llm_result.get("domain_tags", {}).get(domain_name, []),
                    llm_result.get("domain_sub_categories", {}).get(domain_name, []),
                ])
                if llm_required and has_valid_signals:
                    merged_domains.append(domain_name)
        rule_result["domains"] = merged_domains
        for domain_name in ["play", "eat", "drink", "delivery"]:
            rule_required = rule_result.get("domain_required", {}).get(domain_name, False)
            llm_required = llm_result.get("domain_required", {}).get(domain_name, False)
            # LLM required 仅在域名实际存在时生效
            if domain_name in merged_domains:
                rule_result["domain_required"][domain_name] = bool(rule_required or llm_required)
            else:
                rule_result["domain_required"][domain_name] = False
        # 合并标签：只合并最终保留的领域
        for domain_name in merged_domains:
            llm_categories = set(llm_result.get("domain_categories", {}).get(domain_name, []))
            rule_categories = set(rule_result.get("domain_categories", {}).get(domain_name, []))
            rule_result["domain_categories"][domain_name] = list(llm_categories | rule_categories)
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

    _refresh_domain_specs(rule_result)
    return rule_result
