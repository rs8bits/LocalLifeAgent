"""标签目录 Mock API"""

from typing import Optional
from fastapi import APIRouter, Query
from pydantic import BaseModel

from backend.mock_api.storage import read_json
from backend.tools.tag_tools import _load_catalog, _resolve_keywords

router = APIRouter(prefix="/api/mock", tags=["tags"])


@router.get("/tags")
async def get_tags(
    domain: Optional[str] = Query(None, description="领域过滤: play / eat / drink / add_on"),
):
    """查询标签目录，可按领域过滤"""
    catalog = _load_catalog()
    domains = catalog.get("domains", {})

    if domain:
        domain_info = domains.get(domain)
        if domain_info is None:
            return {"error": f"未知领域: {domain}", "available": list(domains.keys())}
        return {"domain": domain, **domain_info}

    return catalog


class ResolveRequest(BaseModel):
    domain: str
    keywords: list[str]


@router.post("/tags/resolve")
async def resolve_tags(req: ResolveRequest):
    """将关键词解析为标签目录中的真实标签，支持 aliases 对齐"""
    catalog = _load_catalog()
    domains = catalog.get("domains", {})

    domain_info = domains.get(req.domain)
    if domain_info is None:
        return {"error": f"未知领域: {req.domain}", "available": list(domains.keys())}

    result = _resolve_keywords(domain_info, req.keywords)
    result["domain"] = req.domain
    return result
