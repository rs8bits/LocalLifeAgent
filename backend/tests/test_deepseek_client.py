"""DeepSeek 客户端测试"""

import httpx
import pytest

from backend.llm.deepseek_client import DeepSeekClient


class TestDeepSeekClientRetry:
    """DeepSeek 网络瞬断重试"""

    @pytest.mark.asyncio
    async def test_retries_transient_transport_error(self, monkeypatch):
        calls = {"count": 0}

        class FakeAsyncClient:
            def __init__(self, timeout):
                self.timeout = timeout

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def post(self, url, headers, json):
                calls["count"] += 1
                if calls["count"] == 1:
                    raise httpx.RemoteProtocolError(
                        "peer closed connection without sending complete message body"
                    )
                return httpx.Response(
                    200,
                    json={"choices": [{"message": {"content": "ok"}}]},
                )

        async def fake_sleep(seconds):
            return None

        monkeypatch.setattr(
            "backend.llm.deepseek_client.httpx.AsyncClient", FakeAsyncClient
        )
        monkeypatch.setattr("backend.llm.deepseek_client.asyncio.sleep", fake_sleep)

        client = DeepSeekClient()
        client.api_key = "test-key"
        client.available = True
        client.max_retries = 1
        client.retry_backoff_seconds = 0.1

        result = await client.chat([{"role": "user", "content": "hi"}])

        assert result.ok is True
        assert result.text == "ok"
        assert calls["count"] == 2

    @pytest.mark.asyncio
    async def test_reports_retry_count_after_transport_error(self, monkeypatch):
        class FakeAsyncClient:
            def __init__(self, timeout):
                self.timeout = timeout

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def post(self, url, headers, json):
                raise httpx.RemoteProtocolError("incomplete chunked read")

        async def fake_sleep(seconds):
            return None

        monkeypatch.setattr(
            "backend.llm.deepseek_client.httpx.AsyncClient", FakeAsyncClient
        )
        monkeypatch.setattr("backend.llm.deepseek_client.asyncio.sleep", fake_sleep)

        client = DeepSeekClient()
        client.api_key = "test-key"
        client.available = True
        client.max_retries = 2
        client.retry_backoff_seconds = 0.1

        result = await client.chat([{"role": "user", "content": "hi"}])

        assert result.ok is False
        assert "已重试 2 次" in result.error
        assert "incomplete chunked read" in result.error
