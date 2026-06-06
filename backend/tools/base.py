"""统一工具基类"""

from typing import Any
from pydantic import BaseModel


class ToolResult(BaseModel):
    tool: str
    status: str  # "ok" | "error"
    message: str
    data: Any = None
    error: str | None = None


class BaseTool:
    """所有工具必须继承此类"""

    name: str = "base"
    description: str = ""

    async def run(self, **kwargs) -> ToolResult:
        raise NotImplementedError
