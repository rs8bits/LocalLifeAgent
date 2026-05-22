"""Input Safety 规则引擎 - 优先规则判断，必要时 LLM 辅助"""

import re
from typing import Any


# ── 白名单：不应被误杀的地名/博物馆/文化场所 ──────────────────────────
LANDMARK_SAFE_PATTERNS = [
    r"天安门",
    r"故宫",
    r"长城",
    r"颐和园",
    r"圆明园",
    r"国家博物馆",
    r"首都博物馆",
    r"军事博物馆",
    r"自然博物馆",
    r"科技馆",
    r"美术馆",
    r"展览馆",
    r"纪念馆",
    r"博物馆",
    r"图书馆",
    r"文化宫",
    r"中山公园",
    r"北海公园",
    r"景山公园",
    r"奥林匹克公园",
    r"朝阳公园",
    r"世纪坛",
    r"大剧院",
    r"音乐厅",
]

# 如果消息匹配到以上任何模式，政治动员类检查自动放行，避免误杀正常地名/场馆查询。
def _contains_landmark(text: str) -> bool:
    return any(re.search(p, text) for p in LANDMARK_SAFE_PATTERNS)


# ── 分类检查函数 ────────────────────────────────────────────────────

def _check_violence(text: str) -> dict[str, Any] | None:
    """检测暴力伤害、威胁他人、组织打架"""
    patterns = [
        (r"杀[人了人]|杀[死掉光]", "high"),
        (r"(打死|打残|废了|弄死)(你|他|她|谁|人)", "high"),
        (r"(砍|捅|炸|烧)(死|伤|了)(你|他|她|谁|人)", "high"),
        (r"组织.*打架|约架|群殴|械斗", "high"),
        (r"(威胁|恐吓).*(杀|死|伤|砍|打残)", "high"),
        (r"买枪|买刀.*砍人|自制.*炸弹|爆炸物", "high"),
        (r"(砍死|捅死|炸死|烧死|毒死)(你|他|她|谁|人|全家)", "high"),
    ]
    # 排除剧本杀/密室逃脱等正常娱乐
    safe_contexts = [r"剧本杀", r"密室.*杀", r"杀人游戏", r"狼人杀", r"三国杀"]
    for ctx in safe_contexts:
        if re.search(ctx, text):
            return None

    for pat, level in patterns:
        if re.search(pat, text):
            return {
                "category": "violence",
                "risk_level": level,
                "reason": "输入包含暴力伤害或威胁内容",
                "safe_message": "您的输入包含不当内容，无法继续处理。请调整后重试。",
            }
    return None


def _check_illegal(text: str) -> dict[str, Any] | None:
    """检测违法交易、毒品、武器、规避监管"""
    patterns = [
        (r"(买|卖|走私|贩卖)(毒品|白粉|冰毒|大麻|海洛因|摇头丸)", "high"),
        (r"(吸毒|嗑药|注射.*毒品)", "high"),
        (r"(买|卖|交易|走私).*(枪支|手枪|步枪|弹药|子弹)", "high"),
        (r"(伪造|造假).*(身份证|护照|驾照|学历|公章|发票)", "high"),
        (r"(套现|洗钱|非法集资|传销)", "high"),
        (r"(规避|绕过).*(监管|审查|备案|实名)", "medium"),
        (r"招嫖|卖淫|嫖娼|包养", "high"),
        (r"(赌博|赌场|赌球|赌马|网赌).*(平台|网站|APP)", "high"),
    ]
    for pat, level in patterns:
        if re.search(pat, text):
            return {
                "category": "illegal",
                "risk_level": level,
                "reason": "输入包含违法或违规内容",
                "safe_message": "您的输入包含不当内容，无法继续处理。请调整后重试。",
            }
    return None


def _check_nsfw_minors(text: str) -> dict[str, Any] | None:
    """检测色情/未成年人相关不当内容"""
    patterns = [
        (r"(未成年|儿童|小孩|孩子|幼女|幼童).*(色情|淫秽|裸|性交|性行为|性侵)", "high"),
        (r"(色情|淫秽|裸照|裸聊|性交|性行为).*(未成年|儿童|小孩|幼女)", "high"),
        (r"(儿童|未成年).*色[情情]", "high"),
        (r"恋童|幼女.*视频|儿童.*色[情情]", "high"),
    ]
    for pat, level in patterns:
        if re.search(pat, text):
            return {
                "category": "nsfw_minors",
                "risk_level": level,
                "reason": "输入包含不当内容",
                "safe_message": "您的输入包含不当内容，无法继续处理。请调整后重试。",
            }
    return None


def _check_hate_harassment(text: str) -> dict[str, Any] | None:
    """检测仇恨、骚扰"""
    patterns = [
        (r"(歧视|侮辱|辱骂).*(民族|种族|地域|性别|残疾|宗教)", "high"),
        (r"(地域黑|地图炮)", "medium"),
        (r"(跟踪|骚扰|人肉|曝光隐私).*(你|他|她|某人|别人)", "high"),
        (r"网络暴力|网暴", "medium"),
    ]
    for pat, level in patterns:
        if re.search(pat, text):
            return {
                "category": "hate_harassment",
                "risk_level": level,
                "reason": "输入包含仇恨或骚扰内容",
                "safe_message": "您的输入包含不当内容，无法继续处理。请调整后重试。",
            }
    return None


def _check_prompt_injection(text: str) -> dict[str, Any] | None:
    """检测明显的 prompt injection"""
    patterns = [
        # 直接要求忽略规则
        (r"(忽略|无视|忘记|跳过|不要管).{0,10}(系统|规则|指令|提示|设定|你的.*身份)", "high"),
        (r"(你.*现在.*是|你.*扮演|你.*角色.*是|从现在开始你是)", "medium"),
        # 伪造输出
        (r"(伪造|造假|虚构).*(真实|支付|订单|交易)", "high"),
        (r"(假装|装作).*(支付|下单|预订|交易).*(成功|完成|确认)", "high"),
        (r"直接说.*(已|已经).*(支付|下单|预订|交易|付款)", "high"),
        (r"(输出|显示|返回).*(真实|成功).*(支付|订单|交易|预订)", "high"),
        # 越狱/ token 注入
        (r"<\|im_start\|>|\[system\]|\[/INST\]|\[INST\]|DAN.*模式|开发者模式", "high"),
        (r"ignore.*(previous|above|system|instruction|rule)", "medium"),
        (r"override.*(system|prompt|instruction|rule)", "medium"),
        # 指令覆盖
        (r"(你.*必须|你必须|一定要).{0,15}(输出|返回|说).{0,10}(成功|完成|通过|真实)", "medium"),
    ]
    for pat, level in patterns:
        if re.search(pat, text):
            return {
                "category": "prompt_injection",
                "risk_level": level,
                "reason": "输入包含试图绕过系统规则的内容",
                "safe_message": "无法处理该请求。请重新描述您的本地生活需求。",
            }
    return None


def _check_political(text: str) -> dict[str, Any] | None:
    """检测与本地生活规划无关的政治动员/煽动"""
    if _contains_landmark(text):
        return None

    # 仅拦截明确的政治动员/煽动，不拦截普通讨论
    patterns = [
        (r"(组织|发起|参加|召集).*(抗议|游行|示威|集会|上访|静坐)", "high"),
        (r"(推翻|颠覆|打倒).*(政府|政权|制度|国家)", "high"),
        (r"煽动.*(颠覆|分裂|独立|暴动)", "high"),
        (r"(暴力|武装).*(革命|起义|政变)", "high"),
    ]
    for pat, level in patterns:
        if re.search(pat, text):
            return {
                "category": "political",
                "risk_level": level,
                "reason": "输入包含与本地生活无关的政治动员内容",
                "safe_message": "无法处理该请求。本地生活助手专注于吃喝玩乐等日常出行规划。",
            }
    return None


# ── 主入口 ───────────────────────────────────────────────────────────

async def check_input_safety(message: str) -> dict[str, Any]:
    """检查用户输入安全性。

    返回:
        {
            "passed": bool,
            "blocked": bool,
            "risk_level": "safe" | "low" | "medium" | "high",
            "categories": list[str],
            "reason": str,
            "safe_message": str,
        }
    """
    if not message or not message.strip():
        return {
            "passed": True,
            "blocked": False,
            "risk_level": "safe",
            "categories": [],
            "reason": "",
            "safe_message": "",
        }

    text = message.strip()
    checks = [
        _check_violence,
        _check_illegal,
        _check_nsfw_minors,
        _check_hate_harassment,
        _check_prompt_injection,
        _check_political,
    ]

    results: list[dict] = []
    for check_fn in checks:
        r = check_fn(text)
        if r:
            results.append(r)

    if not results:
        return {
            "passed": True,
            "blocked": False,
            "risk_level": "safe",
            "categories": [],
            "reason": "",
            "safe_message": "",
        }

    # 取最高风险等级
    risk_order = {"safe": 0, "low": 1, "medium": 2, "high": 3}
    worst = max(results, key=lambda r: risk_order.get(r["risk_level"], 0))

    return {
        "passed": False,
        "blocked": True,
        "risk_level": worst["risk_level"],
        "categories": [r["category"] for r in results],
        "reason": worst["reason"],
        "safe_message": worst["safe_message"],
    }
