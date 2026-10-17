"""Bounded Chat Completions transport: no retries, redirects, proxies or tools."""

# ruff: noqa: RUF001
from __future__ import annotations

import asyncio
import codecs
import ipaddress
import json
import socket
import time
from urllib.parse import urlsplit

import httpx

from .ai_config import AIError


def normalize_url(value):
    try:
        parsed = urlsplit(value.strip())
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.port == 0
            or "%" in value
            or "\\" in value
            or any(p in {".", ".."} for p in parsed.path.split("/"))
            or any(ord(c) < 33 for c in value.strip())
        ):
            raise ValueError
        port = parsed.port
        host = parsed.hostname.encode("idna").decode("ascii").lower()
        host = f"[{host}]" if ":" in host else host
        netloc = host + (
            f":{port}" if port and port != (443 if parsed.scheme == "https" else 80) else ""
        )
        return f"{parsed.scheme}://{netloc}{parsed.path.rstrip('/')}"
    except (ValueError, UnicodeError):
        raise AIError("Base URL 须为不含凭据、查询或片段的 HTTP(S) API 根地址。") from None


class EndpointPolicy:
    def __init__(self, private_urls=()):
        self.private_urls = {normalize_url(u) for u in private_urls}

    async def target(self, base_url):
        base_url = normalize_url(base_url)
        parsed = urlsplit(base_url)
        allowed_private = base_url in self.private_urls
        if not allowed_private and (parsed.scheme != "https" or parsed.port not in {None, 443}):
            raise AIError("默认仅允许 HTTPS 公网 443 端口；内网或其他端口须管理员明确放行。")
        try:
            addresses = await asyncio.wait_for(
                asyncio.to_thread(
                    socket.getaddrinfo,
                    parsed.hostname,
                    parsed.port or (443 if parsed.scheme == "https" else 80),
                    type=socket.SOCK_STREAM,
                ),
                5,
            )
            ips = list(dict.fromkeys(a[4][0] for a in addresses))
            if not ips or (
                not allowed_private and any(not ipaddress.ip_address(ip).is_global for ip in ips)
            ):
                raise AIError("API 地址解析到非公网目标，需要管理员明确放行。")
        except (OSError, TimeoutError, ValueError):
            raise AIError("API 地址解析失败，请检查配置。") from None
        # Pin the validated address, including TLS SNI/certificate hostname. DNS cannot
        # change between validation and connection. Host retains the selected authority.
        ip = f"[{ips[0]}]" if ":" in ips[0] else ips[0]
        port = f":{parsed.port}" if parsed.port else ""
        return (
            f"{parsed.scheme}://{ip}{port}{parsed.path}/chat/completions",
            parsed.netloc,
            parsed.hostname,
        )


async def bounded_lines(response, deadline):
    """Bound memory and wall time before SSE framing; no timeout spans a yield."""
    chunks = response.aiter_bytes().__aiter__()
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    buffer, size = "", 0
    while True:
        try:
            async with asyncio.timeout(max(0, deadline - time.monotonic())):
                chunk = await anext(chunks)
        except StopAsyncIteration:
            return
        size += len(chunk)
        if size > 2_000_000:
            raise AIError("AI 响应超过首版长度限制。", 502)
        try:
            buffer += decoder.decode(chunk)
        except UnicodeError:
            raise AIError("AI 服务返回了无效事件流。", 502) from None
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            if len(line) > 128_000:
                raise AIError("AI 响应超过首版长度限制。", 502)
            yield line.rstrip("\r")
        if len(buffer) > 128_000:
            raise AIError("AI 响应超过首版长度限制。", 502)


class ChatClient:
    def __init__(self, policy, *, transport=None, total_seconds=180):
        self.policy, self.transport = policy, transport
        self.total_seconds = total_seconds

    async def stream(self, config, messages):
        url, host, sni = await self.policy.target(config["base_url"])
        try:
            deadline = time.monotonic() + self.total_seconds
            async with httpx.AsyncClient(
                transport=self.transport,
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(30, connect=10),
            ) as client:
                request = client.build_request(
                    "POST",
                    url,
                    headers={
                        "Authorization": f"Bearer {config['key']}",
                        "Host": host,
                        "Accept-Encoding": "identity",
                    },
                    extensions={"sni_hostname": sni},
                    json={"model": config["model"], "messages": messages, "stream": True},
                )
                async with asyncio.timeout(self.total_seconds):
                    response = await client.send(request, stream=True)
                try:
                    if response.status_code != 200:
                        code = response.status_code
                        message = {
                            401: "AI 认证失败，请替换 API Key。",
                            403: "AI 服务拒绝访问，请检查权限。",
                            429: "AI 服务限流或额度不足，请稍后手动重试。",
                        }.get(code, "AI 服务请求失败，请检查地址和模型。")
                        raise AIError(message, 502, "ai_upstream")
                    if "text/event-stream" not in response.headers.get("content-type", ""):
                        raise AIError("AI 服务未返回有效事件流。", 502)
                    text_size, count = 0, 0
                    data_lines = []
                    async for line in bounded_lines(response, deadline):
                        if line.startswith("data:"):
                            data_lines.append(line[5:].lstrip())
                        elif not line and data_lines:
                            raw = "\n".join(data_lines)
                            data_lines = []
                            if raw == "[DONE]":
                                if not count:
                                    raise AIError("AI 服务返回了空回答。", 502)
                                return
                            try:
                                event = json.loads(raw)
                                if "error" in event:
                                    raise ValueError
                                choices = event["choices"]
                                if not isinstance(choices, list):
                                    raise ValueError
                                for choice in choices:
                                    if choice.get("index", 0) != 0:
                                        continue
                                    delta = choice["delta"]
                                    if delta.get("tool_calls") or delta.get("function_call"):
                                        raise ValueError
                                    content = delta.get("content")
                                    if content is not None:
                                        if not isinstance(content, str):
                                            raise ValueError
                                        text_size += len(content)
                                        if text_size > 64_000:
                                            raise AIError("AI 回答超过首版长度限制。", 502)
                                        if content:
                                            count += 1
                                            yield content
                            except (ValueError, TypeError, KeyError, AttributeError):
                                raise AIError("AI 服务返回了无效事件流。", 502) from None
                    raise AIError("AI 事件流提前结束，请手动重试。", 502)
                finally:
                    await response.aclose()
        except (httpx.TimeoutException, TimeoutError):
            raise AIError("AI 服务响应超时，请手动重试。", 504, "ai_timeout") from None
        except httpx.HTTPError:
            raise AIError("无法连接 AI 服务，请检查地址和网络。", 502) from None
