"""OpenAI 兼容 LLM 适配器：/chat/completions，非流式，可注入 transport 供测试。

安全约束（2026-09-21）：
- 仅允许 http/https scheme；
- 请求发出前校验 host：拒绝 localhost、环回、私有、链路本地、保留、组播、未指定地址。
"""
from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

import httpx

from vault_doctor.config import LLMConfig


class LLMError(RuntimeError):
    pass


def assert_safe_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise LLMError(f"base_url 协议非法（仅 http/https）：{url}")
    host = parsed.hostname
    if not host:
        raise LLMError(f"base_url 缺少主机名：{url}")
    lowered = host.lower()
    if lowered == "localhost" or lowered.endswith(".localhost"):
        raise LLMError(f"base_url 指向 localhost，已拒绝：{url}")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return  # 普通域名放行；显式写出的 IP 在此拦截
    if (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_unspecified
        or ip.is_multicast
    ):
        raise LLMError(f"base_url 指向非公网 IP（{ip}），已拒绝：{url}")


class LLMClient:
    """最小 OpenAI 兼容 chat 客户端。transport 参数用于测试注入 httpx.MockTransport。"""

    def __init__(self, cfg: LLMConfig, transport: httpx.BaseTransport | None = None):
        assert_safe_url(cfg.base_url)
        self._cfg = cfg
        self._http = httpx.Client(
            base_url=cfg.base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {cfg.api_key}"},
            timeout=cfg.timeout_seconds,
            transport=transport,
        )

    def chat(self, system: str, user: str) -> tuple[str, dict]:
        """单轮调用，返回 (回复文本, usage 统计)。"""
        payload = {
            "model": self._cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.3,
        }
        try:
            resp = self._http.post("/chat/completions", json=payload)
        except httpx.HTTPError as exc:
            raise LLMError(f"网络请求失败：{exc}") from exc
        if resp.status_code != 200:
            raise LLMError(f"API 返回 {resp.status_code}：{resp.text[:300]}")
        try:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError) as exc:
            raise LLMError(f"API 响应格式异常：{exc}") from exc
        return content, data.get("usage") or {}

    def close(self) -> None:
        self._http.close()
