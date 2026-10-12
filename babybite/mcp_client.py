"""麦当劳 MCP（https://mcp.mcd.cn）的极简 Streamable HTTP 客户端，以及离线回放客户端。

接口事实见 docs/design.md 第 3 节。
"""
from __future__ import annotations

import http.client
import json
import os
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from . import __version__
from .errors import (APPLY_URL, AuthError, BabyBiteError, FixtureMissingError,
                     McdBusinessError, RateLimitError, TransportError)

MCD_ENDPOINT = "https://mcp.mcd.cn"
PROTOCOL_VERSION = "2025-06-18"
WRITE_TOOLS = frozenset({"create-order", "cancel-order"})
ONLINE_ONLY_TOOLS = WRITE_TOOLS | {"query-order", "delivery-query-addresses"}
EXACT_ONLY_TOOLS = frozenset({"calculate-price"})
DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "real"


def mask_token(text: str, token: Optional[str]) -> str:
    """把文本中出现的 Token 替换为 ***。"""
    if token:
        text = text.replace(token, "***")
    return text


def parse_http_body(raw: str, content_type: str) -> dict:
    """从 JSON 或 SSE 响应体中取出一条 JSON-RPC 消息。"""
    if "text/event-stream" in (content_type or ""):
        datas = [line[5:].strip() for line in raw.splitlines() if line.startswith("data:")]
        datas = [d for d in datas if d]
        if not datas:
            raise BabyBiteError("服务端返回了空的事件流")
        raw = datas[-1]
    try:
        message = json.loads(raw)
    except json.JSONDecodeError:
        raise BabyBiteError(f"无法解析服务端响应：{raw[:200]}") from None
    if not isinstance(message, dict):
        raise BabyBiteError(f"服务端响应不是 JSON 对象：{raw[:200]}")
    return message


def _payload_from_text(result: dict) -> Optional[dict]:
    decoder = json.JSONDecoder()
    for block in result.get("content") or []:
        text = block.get("text") if isinstance(block, dict) else None
        if not text:
            continue
        for marker in ('{"success"', '{"code"'):
            idx = text.find(marker)
            if idx < 0:
                continue
            try:
                obj, _ = decoder.raw_decode(text[idx:])
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                return obj
    return None


def unwrap_tool_result(result: dict) -> dict:
    """返回 tools/call 结果中的业务数据 {success, code, message, data}。

    优先使用 structuredContent；没有时从 content 文本里第一个 {"success" 处解析。
    code 不是 200 或 success 为 false 时抛 McdBusinessError。
    """
    payload = result.get("structuredContent")
    if not isinstance(payload, dict):
        payload = _payload_from_text(result)
    if payload is None:
        texts = " ".join(b.get("text", "") for b in result.get("content") or [] if isinstance(b, dict))
        prefix = "工具调用失败" if result.get("isError") else "无法从工具结果中解析业务数据"
        raise BabyBiteError(f"{prefix}：{texts[:200]}")
    code = payload.get("code")
    if payload.get("success") is False or (code is not None and str(code) != "200"):
        raise McdBusinessError(code, str(payload.get("message", "")))
    return payload


class McpHttpClient:
    """通用 MCP Streamable HTTP 客户端。读取类工具在 429 / 网络错误时指数退避重试；write_tools 中的工具从不重试。"""

    auth_hint = ""

    def __init__(self, endpoint: str, token: Optional[str] = None, timeout: float = 30.0,
                 max_retries: int = 3, sleep: Callable[[float], None] = time.sleep,
                 opener: Callable = urllib.request.urlopen, secrets: tuple = (),
                 write_tools: frozenset = WRITE_TOOLS):
        self._token = token
        self._secrets = tuple(s for s in (token, *secrets) if s)
        self.endpoint = endpoint
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self._sleep = sleep
        self._opener = opener
        self._write_tools = write_tools
        self._session_id: Optional[str] = None
        self._initialized = False
        self._next_id = 1

    def _mask(self, text: str) -> str:
        for secret in self._secrets:
            text = mask_token(text, secret)
        return text

    def call_tool_raw(self, name: str, arguments: dict) -> dict:
        """调用工具并返回原始 result 对象。"""
        self._ensure_initialized()
        message = self._rpc("tools/call", {"name": name, "arguments": arguments},
                            retry=name not in self._write_tools)
        if "error" in message:
            err = message.get("error") or {}
            raise BabyBiteError(self._mask(f"MCP 错误：{err.get('message', err)}"))
        result = message.get("result")
        if not isinstance(result, dict):
            raise BabyBiteError("MCP 响应缺少 result")
        return result

    def call_tool_text(self, name: str, arguments: dict) -> str:
        """调用工具并返回拼接后的文本内容；工具报错（isError）时抛 BabyBiteError。"""
        return _result_text(self.call_tool_raw(name, arguments), name, self._mask)

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        self._rpc("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "mcd-baby-bite", "version": __version__},
        }, retry=True)
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, retry=True)
        self._initialized = True

    def _rpc(self, method: str, params: dict, retry: bool) -> dict:
        body = {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params}
        self._next_id += 1
        raw, content_type = self._post(body, retry=retry)
        return parse_http_body(raw, content_type)

    def _headers(self) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    def _post(self, body: dict, retry: bool):
        attempts = self.max_retries if retry else 1
        delay = 1.0
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        for attempt in range(1, attempts + 1):
            request = urllib.request.Request(self.endpoint, data=data, headers=self._headers(), method="POST")
            try:
                with self._opener(request, timeout=self.timeout) as resp:
                    session_id = resp.headers.get("Mcp-Session-Id")
                    if session_id:
                        self._session_id = session_id
                    # 在唯一入口对整个响应体脱敏：之后任何解析错误、业务错误都不会带出凭证
                    return self._mask(resp.read().decode("utf-8")), resp.headers.get("Content-Type", "")
            except urllib.error.HTTPError as exc:
                try:
                    detail = self._mask(exc.read().decode("utf-8", "replace"))[:200]  # 先脱敏再截断
                except (OSError, http.client.HTTPException):
                    detail = "无法读取服务端错误响应"
                finally:
                    exc.close()
                if exc.code == 401:
                    raise AuthError(f"MCP 服务鉴权失败（HTTP 401）{self.auth_hint}") from None
                if exc.code == 429:
                    if attempt < attempts:
                        self._sleep(delay)
                        delay *= 2
                        continue
                    raise RateLimitError("触发限流（HTTP 429），请稍后再试") from None
                raise TransportError(f"HTTP {exc.code}：{detail}") from None
            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError,
                    http.client.HTTPException) as exc:
                if attempt < attempts:
                    self._sleep(delay)
                    delay *= 2
                    continue
                hint = "" if retry else "；操作结果可能不确定，请先在官方渠道核对状态，勿自动重试"
                raise TransportError(self._mask(f"网络错误：{exc}{hint}")) from None
        raise TransportError("请求失败")  # pragma: no cover


class McdClient(McpHttpClient):
    """麦当劳 MCP 客户端：必须带 Token，call_tool 返回已 unwrap 的业务数据。"""

    auth_hint = f"：MCP Token 无效或已过期，请到 {APPLY_URL} 重新申请（每个 Token 每分钟最多 600 次）"

    def __init__(self, token: str, endpoint: str = MCD_ENDPOINT, **kwargs):
        if not token:
            raise AuthError(f"缺少 MCP Token，请到 {APPLY_URL} 申请")
        super().__init__(endpoint, token=token, **kwargs)

    def call_tool(self, name: str, arguments: dict) -> dict:
        return unwrap_tool_result(self.call_tool_raw(name, arguments))


def _result_text(result: dict, name: str, mask=lambda s: s) -> str:
    text = "\n".join(b.get("text", "") for b in result.get("content") or []
                     if isinstance(b, dict) and b.get("type") == "text")
    if result.get("isError"):
        raise BabyBiteError(mask(f"{name} 调用失败：{text[:200]}"))
    return text


class OfflineClient:
    """离线回放客户端：读取 fixtures/real/*.json。"""

    def __init__(self, fixture_dir: Path = DEFAULT_FIXTURE_DIR):
        self.fixture_dir = Path(fixture_dir)
        self.fixtures = [json.loads(p.read_text("utf-8")) for p in sorted(self.fixture_dir.glob("*.json"))]
        if not self.fixtures:
            raise FixtureMissingError(f"离线数据目录为空：{self.fixture_dir}")
        self.fell_back = False

    def call_tool(self, name: str, arguments: dict) -> dict:
        return unwrap_tool_result(self.call_tool_raw(name, arguments))

    def call_tool_raw(self, name: str, arguments: dict) -> dict:
        if name in ONLINE_ONLY_TOOLS:
            raise BabyBiteError("离线演示模式不支持下单、查单、取消和地址查询，请配置 MCD_MCP_TOKEN 后使用")
        same_tool = [f for f in self.fixtures if f.get("tool") == name]
        for fixture in same_tool:
            if fixture.get("args") == arguments:
                return fixture["result"]
        if name in EXACT_ONLY_TOOLS:
            raise FixtureMissingError(f"离线数据中没有这组参数的 {name} 结果")
        if name == "query-meal-detail":
            same_tool = [f for f in same_tool if f["args"].get("code") == arguments.get("code")]
            if not same_tool:
                raise FixtureMissingError(f"离线数据中没有餐品 {arguments.get('code')} 的详情")
        if not same_tool:
            raise FixtureMissingError(f"离线数据中没有 {name} 的录制结果")
        self.fell_back = True
        return same_tool[0]["result"]

    def call_tool_text(self, name: str, arguments: dict) -> str:
        return _result_text(self.call_tool_raw(name, arguments), name)


def client_from_env(offline: bool = False, fixture_dir: Optional[Path] = None):
    """按参数返回离线或在线客户端；在线模式从 MCD_MCP_TOKEN 读取 Token。"""
    if offline:
        return OfflineClient(fixture_dir or DEFAULT_FIXTURE_DIR)
    token = os.environ.get("MCD_MCP_TOKEN", "").strip()
    if not token:
        raise AuthError(f"未设置环境变量 MCD_MCP_TOKEN。请到 {APPLY_URL} 申请 Token，或加 --offline 体验离线演示")
    return McdClient(token)
