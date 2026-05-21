"""DeepSeek API 客户端封装"""

import json
import httpx

from backend.config import settings


class LLMError(Exception):
    """LLM 调用相关错误"""

    def __init__(self, message: str, error_type: str = "unknown"):
        self.message = message
        self.error_type = error_type
        super().__init__(message)


class LLMResult:
    """LLM 调用结果"""

    def __init__(
        self,
        text: str = "",
        error: str | None = None,
        json_data: dict | list | None = None,
    ):
        self.text = text
        self.error = error
        self.json_data = json_data

    @property
    def ok(self) -> bool:
        return self.error is None


class DeepSeekClient:
    """DeepSeek API 客户端"""

    def __init__(self):
        self.api_key = settings.DEEPSEEK_API_KEY
        self.base_url = settings.DEEPSEEK_BASE_URL.rstrip("/")
        self.model = settings.DEEPSEEK_MODEL
        self.timeout_seconds = settings.DEEPSEEK_TIMEOUT_SECONDS
        self.available = bool(self.api_key)

    def _build_url(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def chat(
        self, messages: list[dict[str, str]], temperature: float = 0.2
    ) -> LLMResult:
        """发送聊天请求，返回纯文本结果"""
        if not self.available:
            return LLMResult(error="DEEPSEEK_API_KEY 未配置，LLM 不可用")

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }

        try:
            timeout = httpx.Timeout(
                timeout=self.timeout_seconds,
                connect=min(10.0, self.timeout_seconds),
            )
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    self._build_url(), headers=self._headers(), json=payload
                )
        except httpx.TimeoutException:
            return LLMResult(error=f"DeepSeek API 请求超时（超过 {self.timeout_seconds:g} 秒）")
        except httpx.ConnectError:
            return LLMResult(error="无法连接 DeepSeek API")
        except Exception as e:
            return LLMResult(error=f"DeepSeek API 网络错误: {str(e)}")

        if resp.status_code == 401 or resp.status_code == 403:
            return LLMResult(error="DeepSeek API 鉴权失败，请检查 API Key")
        if resp.status_code != 200:
            return LLMResult(error=f"DeepSeek API 返回错误状态码 {resp.status_code}")

        try:
            body = resp.json()
            text = body["choices"][0]["message"]["content"]
            return LLMResult(text=text)
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            return LLMResult(error=f"DeepSeek API 响应解析失败: {str(e)}")

    async def chat_json(
        self, messages: list[dict[str, str]], temperature: float = 0.1
    ) -> LLMResult:
        """发送聊天请求，并尽量解析 JSON 到 result.json_data"""
        # 在 system prompt 中提示输出 JSON
        augmented = messages[:]
        if augmented and augmented[0].get("role") == "system":
            augmented[0] = {
                **augmented[0],
                "content": augmented[0]["content"] + "\n请严格输出 JSON 格式，不要包含其他文字。",
            }
        result = await self.chat(augmented, temperature=temperature)
        if not result.ok:
            return result

        try:
            text = _strip_json_fence(result.text)
            result.json_data = json.loads(text)
            result.text = text
        except json.JSONDecodeError as e:
            return LLMResult(text=result.text, error=f"LLM JSON 解析失败: {str(e)}")
        return result


def _strip_json_fence(text: str) -> str:
    """去掉常见 Markdown JSON 代码块包裹"""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped


# 全局单例
deepseek_client = DeepSeekClient()
