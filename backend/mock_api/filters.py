"""Mock 数据通用过滤函数。"""

from typing import Iterable


FAMILY_PARTY_TYPES = {"family_with_child", "family_elder", "family"}


def matches_scene(item: dict, scene: str) -> bool:
    """旧 scene/suitable_scenes 兼容过滤。新主路径使用 party_type。"""
    if item.get("scene") == scene:
        return True
    return scene in item.get("suitable_scenes", [])


def matches_party_type(item: dict, party_type: str) -> bool:
    """按真实同行人画像过滤，不做 couple -> friends 这类语义映射。"""
    party_types = set(item.get("party_types") or [])
    if not party_types:
        return True
    return party_type in party_types


def matches_any_tag(item: dict, tags: Iterable[str]) -> bool:
    item_tags = set(item.get("tags", []))
    return any(tag in item_tags for tag in tags)


def matches_all_tags(item: dict, tags: Iterable[str]) -> bool:
    item_tags = set(item.get("tags", []))
    return all(tag in item_tags for tag in tags)
