"""M1-C LLM 客户端测试：URL 安全校验（约束：仅 http/https，拒绝内网/环回/保留地址）与 mock 往返。"""
import httpx
import pytest

from vault_doctor.config import LLMConfig
from vault_doctor.llm.client import LLMClient, LLMError, assert_safe_url


@pytest.mark.parametrize("url", [
    "https://open.bigmodel.cn/api/paas/v4",
    "http://api.example.com/v4",
])
def test_safe_urls_pass(url):
    assert_safe_url(url)


@pytest.mark.parametrize("url", [
    "ftp://example.com",
    "https://localhost/api",
    "http://127.0.0.1/v4",
    "http://10.0.0.5/v4",
    "http://192.168.1.4/v4",
    "http://169.254.1.1/v4",
    "http://[::1]/v4",
    "http://0.0.0.0/v4",
])
def test_unsafe_urls_rejected(url):
    with pytest.raises(LLMError):
        assert_safe_url(url)


def _ok_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": "解释内容"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
    )


def test_chat_roundtrip():
    cfg = LLMConfig(api_key="sk-test")
    client = LLMClient(cfg, transport=httpx.MockTransport(_ok_handler))
    try:
        content, usage = client.chat("sys", "user")
        assert content == "解释内容"
        assert usage["prompt_tokens"] == 10
    finally:
        client.close()


def test_chat_http_error_readable():
    cfg = LLMConfig(api_key="sk-test")
    client = LLMClient(
        cfg,
        transport=httpx.MockTransport(lambda r: httpx.Response(401, text="unauthorized")),
    )
    try:
        with pytest.raises(LLMError, match="401"):
            client.chat("s", "u")
    finally:
        client.close()


def test_unsafe_base_url_rejected_before_any_request():
    cfg = LLMConfig(api_key="sk-test", base_url="http://127.0.0.1:8000/v4")
    with pytest.raises(LLMError, match="拒绝"):
        LLMClient(cfg)
