"""标签目录工具 - 查询标签字典和解析关键词"""

import json
from pathlib import Path
from typing import Optional

from backend.tools.base import BaseTool, ToolResult
from backend.config import DATA_DIR

TAG_CATALOG_FILE = "tag_catalog.json"


def _load_catalog() -> dict:
    file_path = DATA_DIR / TAG_CATALOG_FILE
    if not file_path.exists():
        return {"domains": {}}
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data
    return {"domains": {}}


def _resolve_keywords(domain_info: dict, keywords: list[str]) -> dict:
    """根据 tag_catalog 的 aliases 解析关键词，返回匹配的标签/类目"""
    aliases = domain_info.get("aliases", {})
    categories = set(domain_info.get("categories", []))
    tags = set(domain_info.get("tags", []))
    sub_categories = set(domain_info.get("sub_categories", []))

    matched_tags: list[str] = []
    matched_categories: list[str] = []
    matched_sub_categories: list[str] = []
    unmatched: list[str] = []
    explanations: list[str] = []

    for kw in keywords:
        kw_lower = kw.lower().strip()
        found = False

        # 先直接匹配 tags
        if kw in tags:
            matched_tags.append(kw)
            explanations.append(f"'{kw}' 直接匹配标签")
            found = True
            continue

        # 匹配 categories
        if kw in categories:
            matched_categories.append(kw)
            explanations.append(f"'{kw}' 直接匹配类目")
            found = True
            continue

        # 匹配 sub_categories
        if kw in sub_categories:
            matched_sub_categories.append(kw)
            explanations.append(f"'{kw}' 直接匹配子品类")
            found = True
            continue

        # 走 aliases
        for canonical, alias_list in aliases.items():
            alias_lower = [a.lower() for a in alias_list]
            if kw_lower in alias_lower or kw_lower == canonical.lower():
                if canonical in tags:
                    matched_tags.append(canonical)
                elif canonical in categories:
                    matched_categories.append(canonical)
                elif canonical in sub_categories:
                    matched_sub_categories.append(canonical)
                else:
                    matched_tags.append(canonical)
                explanations.append(f"'{kw}' 通过别名匹配到 '{canonical}'")
                found = True
                break

        if not found:
            unmatched.append(kw)
            explanations.append(f"'{kw}' 未匹配到任何标签")

    return {
        "matched_tags": list(dict.fromkeys(matched_tags)),
        "matched_categories": list(dict.fromkeys(matched_categories)),
        "matched_sub_categories": list(dict.fromkeys(matched_sub_categories)),
        "unmatched": unmatched,
        "explanations": explanations,
    }


class GetTagCatalogTool(BaseTool):
    name = "get_tag_catalog"
    description = "查询标签目录，可按领域过滤。返回该领域的所有类目、标签、别名和示例 POI"

    async def run(self, domain: Optional[str] = None) -> ToolResult:
        try:
            catalog = _load_catalog()
            domains = catalog.get("domains", {})

            if domain:
                domain_info = domains.get(domain)
                if domain_info is None:
                    return ToolResult(
                        tool=self.name, status="error",
                        message=f"未知领域: {domain}，可用: {list(domains.keys())}",
                    )
                return ToolResult(
                    tool=self.name, status="ok",
                    message=f"标签目录 ({domain})",
                    data={"domain": domain, **domain_info},
                )

            return ToolResult(
                tool=self.name, status="ok",
                message=f"完整标签目录 ({len(domains)}个领域)",
                data=catalog,
            )
        except Exception as e:
            return ToolResult(
                tool=self.name, status="error", message="查询标签目录失败", error=str(e),
            )


class ResolveTagsTool(BaseTool):
    name = "resolve_tags"
    description = "将 LLM 输出的自然语言/英文关键词解析为标签目录中的真实标签，支持 aliases 对齐"

    async def run(self, domain: str, keywords: list[str]) -> ToolResult:
        try:
            catalog = _load_catalog()
            domains = catalog.get("domains", {})

            domain_info = domains.get(domain)
            if domain_info is None:
                return ToolResult(
                    tool=self.name, status="error",
                    message=f"未知领域: {domain}，可用: {list(domains.keys())}",
                )

            result = _resolve_keywords(domain_info, keywords)
            result["domain"] = domain

            return ToolResult(
                tool=self.name, status="ok",
                message=f"解析完成: {len(result['matched_tags'])} 标签, {len(result['matched_categories'])} 类目, {len(result['unmatched'])} 未匹配",
                data=result,
            )
        except Exception as e:
            return ToolResult(
                tool=self.name, status="error", message="解析标签失败", error=str(e),
            )
