# mcd-baby-bite 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现"小小麦门 · 带娃吃麦定制官"：基于麦当劳 MCP 真实菜单与营养数据，为 1-6 岁宝宝生成特制去料的套餐、份量与钠预算、店员话术卡，并支持确认后下单。

**Architecture:** 零依赖 Python 包 `babybite/`，按职责拆分为客户端、场景、营养、年龄规则、菜单解析、特制、规划、渲染、CLI 九个模块；`fixtures/real/` 存放用真实 Token 录制的接口响应，用于离线演示和测试。仓库根目录的 `SKILL.md` 让各类 Agent 直接加载。

**Tech Stack:** Python 3.9+ 标准库（urllib、json、dataclasses、argparse、unittest、http.server）。本机为 Python 3.14。

**Spec:** `docs/design.md`（执行者必须先读完第 3-8 节）

## Global Constraints

- 只用 Python 标准库；代码需兼容 Python 3.9（不使用 `match`，类型注解统一写 `from __future__ import annotations`）
- 包名 `babybite`，仓库名 `mcd-baby-bite`，入口 `python3 -m babybite`
- 所有用户可见文案为简体中文，不使用 emoji
- Token 只从环境变量 `MCD_MCP_TOKEN` 读取；任何输出、异常、文件中不得出现 Token
- `create-order`、`cancel-order` 永不自动重试；`create-order` 必须由 `order --confirm` 触发
- 特制 code 只能取自 `query-meal-detail`；开关型特制组（每项都有 `unselectedKey`）内只要有一项要去掉，整组全部传入：去掉的 `key=unselectedKey, quantity=0`，保留的 `key=selectedKey, quantity=selectedQuantity`
- 钠计算只用官方营养数据，匹配不到就标注"无官方营养数据"，不估算
- 文案禁止：与其他品牌比较、贬低麦当劳、"不健康 / 最健康 / 营养均衡 / 绝对安全"等措辞
- 测试命令：`python3 -m unittest discover -s tests -v`（在仓库根目录 `/Users/wenzhou/code/my/mc/mcd-baby-bite` 执行）
- 每个任务完成且全部测试通过后，执行者提交一次（分期提交）：`git add` 本任务文件后 `git commit -m "<type>(<scope>): <中文描述>"`，例如 `feat(client): 实现麦当劳 MCP 客户端与离线回放`；**不加任何署名 / Co-Authored-By 行**；不改 git 配置，不 push
- 不得修改 `fixtures/real/` 中已有文件（真实录制数据）
- 新功能的可选外部依赖（浏览器、小红书 MCP、高德 Key）缺失时必须优雅降级：给出提示，不影响定制单主流程

## Review Focus

1. 门店都不营业且没给 `--when`：应给出清晰中文提示并以非 0 退出，不能抛 Python 堆栈 → Task 9 `test_all_stores_closed_without_when`
2. 套餐子项名在营养表里匹配不到（新品、改名）：方案仍可生成，该项标注"无官方营养数据"、排序靠后 → Task 7 `test_unknown_nutrition_is_marked_and_ranked_lower`
3. 过敏原把饮料默认项排除（如乳制品过敏）：自动换成纯悦，并在"处理"列说明替换 → Task 6 `test_dairy_allergy_swaps_milk_to_water`、Task 8 `test_markdown_shows_swap`
4. 异常信息中带出 Token（例如 HTTP 500 响应体回显 Authorization）：必须打码 → Task 2 `test_error_message_masks_token`
5. 月龄边界（11 / 12 / 23 / 24 / 47 / 48、负数、超过 216）：12 月龄以下不调用任何接口直接给建议，非法值退出码 2 → Task 4 边界测试、Task 9 `test_infant_does_not_call_api`、`test_invalid_age_exit_code`

---

### Task 1: 包骨架、异常与场景规则

**Files:**
- Create: `babybite/__init__.py`, `babybite/errors.py`, `babybite/scenes.py`, `tests/__init__.py`, `tests/test_scenes.py`

**Interfaces:**
- Produces:
  - `babybite.__version__: str = "0.1.0"`
  - `errors`: `APPLY_URL`, `BabyBiteError`, `AuthError`, `RateLimitError`, `TransportError`, `FixtureMissingError`, `McdBusinessError(code, message)`（属性 `code`、`message`）
  - `scenes.Scene(key, label, be_type, order_type, needs_be_code, needs_take_way, needs_address)`、`SCENES: dict`、`get_scene(key) -> Scene`、`store_args(scene, store_code, be_code=None, reservation_date=None) -> dict`

- [ ] **Step 1: 写失败测试** `tests/test_scenes.py`

```python
import unittest

from babybite.errors import McdBusinessError
from babybite.scenes import get_scene, store_args


class SceneTest(unittest.TestCase):
    def test_pickup_never_sends_be_code(self):
        args = store_args(get_scene("pickup"), "1450713", be_code="X", reservation_date="2026-10-12 11:30")
        self.assertEqual(args, {"storeCode": "1450713", "orderType": 1, "beType": 1,
                                "reservationDate": "2026-10-12 11:30"})

    def test_drive_requires_be_code(self):
        with self.assertRaises(ValueError):
            store_args(get_scene("drive"), "1450713")
        self.assertEqual(store_args(get_scene("drive"), "S1", be_code="B1"),
                         {"storeCode": "S1", "orderType": 1, "beType": 5, "beCode": "B1"})

    def test_delivery_uses_order_type_2(self):
        scene = get_scene("delivery")
        self.assertEqual((scene.be_type, scene.order_type, scene.needs_address, scene.needs_take_way), (2, 2, True, False))

    def test_unknown_scene_and_empty_store(self):
        with self.assertRaises(ValueError):
            get_scene("teleport")
        with self.assertRaises(ValueError):
            store_args(get_scene("pickup"), "")

    def test_business_error_keeps_code(self):
        err = McdBusinessError(600057, "门店可能已关闭")
        self.assertEqual(err.code, 600057)
        self.assertIn("600057", str(err))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m unittest tests.test_scenes -v`
Expected: `ModuleNotFoundError: No module named 'babybite'`

- [ ] **Step 3: 实现**

`babybite/__init__.py`：

```python
"""mcd-baby-bite：小小麦门 · 带娃吃麦定制官。"""

__version__ = "0.1.0"
```

`tests/__init__.py`：空文件。

`babybite/errors.py`：

```python
"""mcd-baby-bite 的异常类型。所有 message 均为面向用户的中文。"""
from __future__ import annotations

APPLY_URL = "https://open.mcd.cn/mcp"


class BabyBiteError(Exception):
    """基础异常。"""


class AuthError(BabyBiteError):
    """Token 缺失、无效或过期。"""


class RateLimitError(BabyBiteError):
    """HTTP 429 限流。"""


class TransportError(BabyBiteError):
    """网络错误或非预期的 HTTP 状态。"""


class FixtureMissingError(BabyBiteError):
    """离线模式下找不到对应的录制数据。"""


class McdBusinessError(BabyBiteError):
    """麦当劳接口返回的业务错误（code != 200）。"""

    def __init__(self, code, message: str):
        self.code = code
        self.message = message
        super().__init__(f"麦当劳接口返回错误 code={code}：{message}")
```

`babybite/scenes.py`：

```python
"""到店自提 / 得来速 / 麦乐送 三种场景的参数规则（见 docs/design.md 3.1）。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Scene:
    key: str
    label: str
    be_type: int
    order_type: int
    needs_be_code: bool
    needs_take_way: bool
    needs_address: bool


SCENES = {
    "pickup": Scene("pickup", "到店自提", 1, 1, False, True, False),
    "drive": Scene("drive", "得来速", 5, 1, True, True, False),
    "delivery": Scene("delivery", "麦乐送", 2, 2, True, False, True),
}


def get_scene(key: str) -> Scene:
    try:
        return SCENES[key]
    except KeyError:
        raise ValueError(f"未知场景：{key}，可选：{'、'.join(SCENES)}") from None


def store_args(scene: Scene, store_code: str, be_code: Optional[str] = None,
               reservation_date: Optional[str] = None) -> dict:
    """生成 query-meals / query-meal-detail / calculate-price / create-order 共用的门店参数。"""
    if not store_code:
        raise ValueError("门店编码不能为空")
    if scene.needs_be_code and not be_code:
        raise ValueError(f"{scene.label}场景必须提供 beCode")
    args = {"storeCode": store_code, "orderType": scene.order_type, "beType": scene.be_type}
    if scene.needs_be_code:
        args["beCode"] = be_code
    if reservation_date:
        args["reservationDate"] = reservation_date
    return args
```

- [ ] **Step 4: 运行确认通过**

Run: `python3 -m unittest tests.test_scenes -v`
Expected: 5 tests OK

---

### Task 2: MCP 客户端（在线 + 离线回放）

**Files:**
- Create: `babybite/mcp_client.py`, `tests/fake_mcp.py`, `tests/test_mcp_client.py`

**Interfaces:**
- Consumes: Task 1 的 `errors`、`__version__`
- Produces:
  - 常量 `MCD_ENDPOINT`, `PROTOCOL_VERSION = "2025-06-18"`, `WRITE_TOOLS`, `DEFAULT_FIXTURE_DIR`
  - `mask_token(text, token) -> str`
  - `parse_http_body(raw: str, content_type: str) -> dict`
  - `unwrap_tool_result(result: dict) -> dict`（返回 `{success, code, message, data, ...}`）
  - `McdClient(token, endpoint=MCD_ENDPOINT, timeout=30.0, max_retries=3, sleep=time.sleep, opener=urllib.request.urlopen)`，方法 `call_tool(name, arguments) -> dict`（已 unwrap）、`call_tool_raw(name, arguments) -> dict`（原始 result）
  - `OfflineClient(fixture_dir=DEFAULT_FIXTURE_DIR)`，同名两个方法，属性 `fell_back: bool`
  - `client_from_env(offline=False, fixture_dir=None)`
- fixture 文件格式：`{"tool": str, "args": dict, "recordedAt": str, "result": <tools/call 原始 result>}`

- [ ] **Step 1: 写测试辅助** `tests/fake_mcp.py`

```python
"""按顺序返回预设响应的本地 MCP 假服务，供客户端测试使用。"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def rpc(result, id_=1):
    return json.dumps({"jsonrpc": "2.0", "id": id_, "result": result}, ensure_ascii=False)


INIT = (200, "application/json", rpc({"protocolVersion": "2025-06-18", "serverInfo": {"name": "fake"}}), {})
NOTIFIED = (202, "application/json", "", {})


def tool_ok(payload, sse=False):
    body = rpc({"content": [{"type": "text", "text": "字段说明\n" + json.dumps(payload, ensure_ascii=False)}],
                "structuredContent": payload, "isError": False}, 2)
    if sse:
        return 200, "text/event-stream", f"event: message\ndata: {body}\n\n", {}
    return 200, "application/json", body, {}


class FakeMcp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length else b"{}"
                outer.requests.append({"headers": {k.lower(): v for k, v in self.headers.items()},
                                       "body": json.loads(raw or b"{}")})
                status, ctype, body, extra = (outer.responses.pop(0) if outer.responses
                                              else (500, "text/plain", "no more responses", {}))
                data = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                for key, value in extra.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
```

- [ ] **Step 2: 写失败测试** `tests/test_mcp_client.py`

```python
import os
import unittest
from unittest import mock

from babybite.errors import AuthError, BabyBiteError, FixtureMissingError, McdBusinessError, RateLimitError, TransportError
from babybite.mcp_client import McdClient, OfflineClient, client_from_env, parse_http_body, unwrap_tool_result
from tests.fake_mcp import INIT, NOTIFIED, FakeMcp, rpc, tool_ok

TOKEN = "secret-token-1234567890"
OK = {"success": True, "code": 200, "message": "请求成功", "data": "x"}
LUNCH = "2026-10-12 11:30"


class OnlineClientTest(unittest.TestCase):
    def make(self, responses):
        self.fake = FakeMcp(responses)
        self.addCleanup(self.fake.close)
        self.sleeps = []
        return McdClient(TOKEN, endpoint=self.fake.url, timeout=5, sleep=self.sleeps.append)

    def test_handshake_headers_and_payload(self):
        client = self.make([INIT, NOTIFIED, tool_ok(OK)])
        self.assertEqual(client.call_tool("now-time-info", {})["data"], "x")
        methods = [r["body"].get("method") for r in self.fake.requests]
        self.assertEqual(methods, ["initialize", "notifications/initialized", "tools/call"])
        headers = self.fake.requests[2]["headers"]
        self.assertEqual(headers["authorization"], f"Bearer {TOKEN}")
        self.assertIn("text/event-stream", headers["accept"])
        self.assertEqual(headers["mcp-protocol-version"], "2025-06-18")
        self.assertEqual(self.fake.requests[2]["body"]["params"], {"name": "now-time-info", "arguments": {}})

    def test_sse_response_is_parsed(self):
        client = self.make([INIT, NOTIFIED, tool_ok(OK, sse=True)])
        self.assertEqual(client.call_tool("now-time-info", {})["data"], "x")

    def test_session_id_is_echoed(self):
        init = (200, "application/json", rpc({"protocolVersion": "2025-06-18"}), {"Mcp-Session-Id": "abc"})
        client = self.make([init, NOTIFIED, tool_ok(OK)])
        client.call_tool("now-time-info", {})
        self.assertEqual(self.fake.requests[2]["headers"].get("mcp-session-id"), "abc")

    def test_401_raises_auth_error_without_token(self):
        client = self.make([(401, "application/json", "{}", {})])
        with self.assertRaises(AuthError) as ctx:
            client.call_tool("now-time-info", {})
        self.assertNotIn(TOKEN, str(ctx.exception))
        self.assertIn("open.mcd.cn", str(ctx.exception))

    def test_429_retries_then_succeeds(self):
        client = self.make([INIT, NOTIFIED, (429, "application/json", "{}", {}), tool_ok(OK)])
        self.assertEqual(client.call_tool("query-meals", {})["data"], "x")
        self.assertEqual(self.sleeps, [1.0])

    def test_429_exhausted_raises(self):
        busy = (429, "application/json", "{}", {})
        client = self.make([INIT, NOTIFIED, busy, busy, busy])
        with self.assertRaises(RateLimitError):
            client.call_tool("query-meals", {})
        self.assertEqual(self.sleeps, [1.0, 2.0])

    def test_write_tool_is_never_retried(self):
        client = self.make([INIT, NOTIFIED, (429, "application/json", "{}", {}), tool_ok(OK)])
        with self.assertRaises(RateLimitError):
            client.call_tool("create-order", {})
        self.assertEqual(len(self.fake.requests), 3)

    def test_business_error(self):
        client = self.make([INIT, NOTIFIED, tool_ok({"success": False, "code": 600057, "message": "门店可能已关闭或不在营业时间"})])
        with self.assertRaises(McdBusinessError) as ctx:
            client.call_tool("query-meals", {})
        self.assertEqual(ctx.exception.code, 600057)

    def test_error_message_masks_token(self):
        client = self.make([INIT, NOTIFIED, (500, "text/plain", f"bad header Bearer {TOKEN}", {})])
        with self.assertRaises(TransportError) as ctx:
            client.call_tool("query-meals", {})
        self.assertNotIn(TOKEN, str(ctx.exception))
        self.assertIn("***", str(ctx.exception))


class UnwrapTest(unittest.TestCase):
    def test_text_fallback_when_no_structured_content(self):
        result = {"content": [{"type": "text", "text": "### 字段说明\n{\"success\":true,\"code\":200,\"data\":[1]}"}]}
        self.assertEqual(unwrap_tool_result(result)["data"], [1])

    def test_unparsable_raises(self):
        with self.assertRaises(BabyBiteError):
            unwrap_tool_result({"content": [{"type": "text", "text": "纯文本"}], "isError": True})

    def test_string_code_200_is_ok(self):
        self.assertEqual(unwrap_tool_result({"structuredContent": {"success": True, "code": "200", "data": 1}})["data"], 1)

    def test_parse_http_body_empty_sse(self):
        with self.assertRaises(BabyBiteError):
            parse_http_body("event: ping\n\n", "text/event-stream")


class OfflineClientTest(unittest.TestCase):
    def test_exact_match_real_fixture(self):
        args = {"storeCode": "1450713", "orderType": 1, "beType": 1, "code": "1120", "reservationDate": LUNCH}
        payload = OfflineClient().call_tool("query-meal-detail", args)
        self.assertEqual(payload["data"]["name"], "双层吉士汉堡")

    def test_detail_falls_back_by_code(self):
        client = OfflineClient()
        args = {"storeCode": "1450713", "orderType": 1, "beType": 1, "code": "1120", "reservationDate": "2027-01-01 12:00"}
        self.assertEqual(client.call_tool("query-meal-detail", args)["data"]["code"], "1120")
        self.assertTrue(client.fell_back)

    def test_detail_unknown_code_raises(self):
        with self.assertRaises(FixtureMissingError):
            OfflineClient().call_tool("query-meal-detail", {"code": "000"})

    def test_calculate_price_is_exact_only(self):
        with self.assertRaises(FixtureMissingError):
            OfflineClient().call_tool("calculate-price", {"storeCode": "1450713", "items": []})

    def test_write_tools_rejected(self):
        for tool in ("create-order", "cancel-order", "query-order"):
            with self.assertRaises(BabyBiteError):
                OfflineClient().call_tool(tool, {})

    def test_client_from_env_requires_token(self):
        with mock.patch.dict(os.environ, {"MCD_MCP_TOKEN": ""}):
            with self.assertRaises(AuthError) as ctx:
                client_from_env()
        self.assertIn("--offline", str(ctx.exception))
        self.assertIsInstance(client_from_env(offline=True), OfflineClient)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: 运行确认失败**

Run: `python3 -m unittest tests.test_mcp_client -v`
Expected: `ModuleNotFoundError: No module named 'babybite.mcp_client'`

- [ ] **Step 4: 实现** `babybite/mcp_client.py`

```python
"""麦当劳 MCP（https://mcp.mcd.cn）的极简 Streamable HTTP 客户端，以及离线回放客户端。

接口事实见 docs/design.md 第 3 节。
"""
from __future__ import annotations

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


class McdClient:
    """在线客户端。读取类工具在 429 / 网络错误时指数退避重试；写操作（下单、取消）从不重试。"""

    def __init__(self, token: str, endpoint: str = MCD_ENDPOINT, timeout: float = 30.0,
                 max_retries: int = 3, sleep: Callable[[float], None] = time.sleep,
                 opener: Callable = urllib.request.urlopen):
        if not token:
            raise AuthError(f"缺少 MCP Token，请到 {APPLY_URL} 申请")
        self._token = token
        self.endpoint = endpoint
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self._sleep = sleep
        self._opener = opener
        self._session_id: Optional[str] = None
        self._initialized = False
        self._next_id = 1

    def call_tool(self, name: str, arguments: dict) -> dict:
        """调用工具并返回业务数据（已 unwrap）。"""
        return unwrap_tool_result(self.call_tool_raw(name, arguments))

    def call_tool_raw(self, name: str, arguments: dict) -> dict:
        """调用工具并返回原始 result 对象（录制 fixtures 用）。"""
        self._ensure_initialized()
        message = self._rpc("tools/call", {"name": name, "arguments": arguments},
                            retry=name not in WRITE_TOOLS)
        if "error" in message:
            err = message.get("error") or {}
            raise BabyBiteError(f"MCP 错误：{err.get('message', err)}")
        result = message.get("result")
        if not isinstance(result, dict):
            raise BabyBiteError("MCP 响应缺少 result")
        return result

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
            "Authorization": f"Bearer {self._token}",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
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
                    return resp.read().decode("utf-8"), resp.headers.get("Content-Type", "")
            except urllib.error.HTTPError as exc:
                if exc.code == 401:
                    raise AuthError(f"MCP Token 无效或已过期（HTTP 401），请到 {APPLY_URL} 重新申请") from None
                if exc.code == 429:
                    if attempt < attempts:
                        self._sleep(delay)
                        delay *= 2
                        continue
                    raise RateLimitError("触发限流（HTTP 429，每个 Token 每分钟最多 600 次），请稍后再试") from None
                detail = exc.read().decode("utf-8", "replace")[:200]
                raise TransportError(mask_token(f"HTTP {exc.code}：{detail}", self._token)) from None
            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as exc:
                if attempt < attempts:
                    self._sleep(delay)
                    delay *= 2
                    continue
                raise TransportError(mask_token(f"网络错误：{exc}", self._token)) from None
        raise TransportError("请求失败")  # pragma: no cover


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


def client_from_env(offline: bool = False, fixture_dir: Optional[Path] = None):
    """按参数返回离线或在线客户端；在线模式从 MCD_MCP_TOKEN 读取 Token。"""
    if offline:
        return OfflineClient(fixture_dir or DEFAULT_FIXTURE_DIR)
    token = os.environ.get("MCD_MCP_TOKEN", "").strip()
    if not token:
        raise AuthError(f"未设置环境变量 MCD_MCP_TOKEN。请到 {APPLY_URL} 申请 Token，或加 --offline 体验离线演示")
    return McdClient(token)
```

- [ ] **Step 5: 运行确认通过**

Run: `python3 -m unittest tests.test_mcp_client -v`
Expected: 19 tests OK

---

### Task 3: 营养表解析与名称匹配

**Files:**
- Create: `babybite/nutrition.py`, `tests/helpers.py`, `tests/test_nutrition.py`

**Interfaces:**
- Consumes: `OfflineClient`（测试中读真实 fixture）
- Produces:
  - `NutritionFact(name, energy_kcal, protein_g, fat_g, carb_g, sodium_mg, calcium_mg)`（数值均为 `Optional[float]`）
  - `normalize_name(name) -> str`
  - `parse_nutrition_table(data: str) -> list[NutritionFact]`
  - `NutritionIndex(facts)`，方法 `lookup(name) -> Optional[NutritionFact]`、`__len__`
  - `ALIASES: dict`
  - `tests/helpers.py`：`LUNCH`, `STORE_ARGS`, `load_index()`, `load_detail(code)`, `load_menu()`（后续任务复用）

- [ ] **Step 1: 写测试辅助** `tests/helpers.py`

```python
"""测试共用：从真实录制的 fixtures 构造对象。"""
from babybite.mcp_client import OfflineClient

LUNCH = "2026-10-12 11:30"
STORE_ARGS = {"storeCode": "1450713", "orderType": 1, "beType": 1, "reservationDate": LUNCH}


def load_index():
    from babybite.nutrition import NutritionIndex, parse_nutrition_table
    payload = OfflineClient().call_tool("list-nutrition-foods", {})
    return NutritionIndex(parse_nutrition_table(payload["data"]))


def load_detail(code):
    from babybite.menu import parse_meal_detail
    return parse_meal_detail(OfflineClient().call_tool("query-meal-detail", dict(STORE_ARGS, code=code)))


def load_menu():
    from babybite.menu import parse_menu
    return parse_menu(OfflineClient().call_tool("query-meals", STORE_ARGS))
```

（`load_detail` / `load_menu` 依赖 Task 5 的 `babybite.menu`，采用函数内导入，本任务不调用它们。）

- [ ] **Step 2: 写失败测试** `tests/test_nutrition.py`

```python
import unittest

from babybite.errors import BabyBiteError
from babybite.mcp_client import OfflineClient
from babybite.nutrition import NutritionIndex, normalize_name, parse_nutrition_table
from tests.helpers import load_index


class ParseTest(unittest.TestCase):
    def test_real_table_has_160_rows(self):
        data = OfflineClient().call_tool("list-nutrition-foods", {})["data"]
        facts = parse_nutrition_table(data)
        self.assertEqual(len(facts), 160)
        burger = next(f for f in facts if f.name == "汉堡包")
        self.assertEqual((burger.energy_kcal, burger.sodium_mg, burger.calcium_mg), (248.0, 492.0, 61.0))

    def test_null_values_and_comma_in_name(self):
        table = ("[2]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:\n"
                 "  测试,新品,null,1,2,3,4,5,null,7\n"
                 "  普通,null,10,20,1,1,1,null,0")
        facts = parse_nutrition_table(table)
        self.assertEqual(facts[0].name, "测试,新品")
        self.assertIsNone(facts[0].sodium_mg)
        self.assertIsNone(facts[1].sodium_mg)
        self.assertEqual(facts[1].energy_kcal, 20.0)

    def test_bad_header_raises(self):
        with self.assertRaises(BabyBiteError):
            parse_nutrition_table("no header\n a,b")
        with self.assertRaises(BabyBiteError):
            parse_nutrition_table("[1]{productName,energyKcal}:\n a,1")

    def test_empty_table(self):
        self.assertEqual(parse_nutrition_table(""), [])


class LookupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = load_index()

    def test_combo_item_names_resolve(self):
        cases = {"麦乐鸡-4块": 337, "苹果片一袋(60g)": 0, "纯牛奶": 73, "100% 苹果汁(盒装)": 0,
                 "鱼排堡": 442, "小杯玉米杯": 1, "迷你薯条": 61, "汉堡包": 492, "吉士汉堡包": 673}
        for name, sodium in cases.items():
            with self.subTest(name=name):
                self.assertEqual(self.index.lookup(name).sodium_mg, sodium)

    def test_unknown_returns_none(self):
        self.assertIsNone(self.index.lookup("海绵宝宝×航海王系列玩具"))
        self.assertIsNone(self.index.lookup(""))

    def test_normalize(self):
        self.assertEqual(normalize_name("纯牛奶（盒装）"), "纯牛奶")
        self.assertEqual(normalize_name("麦咖啡™ 美式"), "麦咖啡美式")
        self.assertEqual(len(NutritionIndex([])), 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: 运行确认失败**

Run: `python3 -m unittest tests.test_nutrition -v`
Expected: `ModuleNotFoundError: No module named 'babybite.nutrition'`

- [ ] **Step 4: 实现** `babybite/nutrition.py`

```python
"""解析 list-nutrition-foods 返回的营养表，并按名称匹配菜单单品。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional

from .errors import BabyBiteError

_PAREN = re.compile(r"[（(][^（()）]*[）)]")
_NOISE = re.compile(r"[\s　™®“”\"'·\-—_]")
REQUIRED_FIELDS = ("productName", "energyKcal", "protein", "fat", "carbohydrate", "sodium", "calcium")
# 套餐子项名 -> 营养表名。只收录用真实数据核对过的别名，不做模糊猜测。
ALIASES = {"鱼排堡": "儿童鱼排堡"}


@dataclass(frozen=True)
class NutritionFact:
    name: str
    energy_kcal: Optional[float]
    protein_g: Optional[float]
    fat_g: Optional[float]
    carb_g: Optional[float]
    sodium_mg: Optional[float]
    calcium_mg: Optional[float]


def normalize_name(name: str) -> str:
    text = _PAREN.sub("", name or "")
    text = text.replace("一袋", "")
    text = _NOISE.sub("", text)
    return text.lower()


def _num(value: str) -> Optional[float]:
    value = value.strip()
    if value in ("", "null", "None", "-"):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_nutrition_table(data: str) -> list:
    """解析形如 `[160]{productName,...}:` 表头 + 逗号分隔行的营养表。"""
    lines = [line for line in (data or "").splitlines() if line.strip()]
    if not lines:
        return []
    match = re.search(r"\{([^}]*)\}", lines[0])
    if not match:
        raise BabyBiteError("营养数据表头格式无法识别")
    fields = [f.strip() for f in match.group(1).split(",")]
    missing = [f for f in REQUIRED_FIELDS if f not in fields]
    if missing:
        raise BabyBiteError(f"营养数据缺少字段：{', '.join(missing)}")
    idx = {f: i for i, f in enumerate(fields)}
    name_at = idx["productName"]
    facts = []
    for line in lines[1:]:
        cols = [c.strip() for c in line.split(",")]
        extra = len(cols) - len(fields)
        if extra < 0:
            continue
        if extra > 0:  # 名称里带逗号：把多出来的列并回名称
            cols = cols[:name_at] + [",".join(cols[name_at:name_at + extra + 1])] + cols[name_at + extra + 1:]
        facts.append(NutritionFact(
            name=cols[name_at],
            energy_kcal=_num(cols[idx["energyKcal"]]),
            protein_g=_num(cols[idx["protein"]]),
            fat_g=_num(cols[idx["fat"]]),
            carb_g=_num(cols[idx["carbohydrate"]]),
            sodium_mg=_num(cols[idx["sodium"]]),
            calcium_mg=_num(cols[idx["calcium"]]),
        ))
    return facts


class NutritionIndex:
    """按规范化名称索引营养数据；重名时保留第一条。"""

    def __init__(self, facts: Iterable[NutritionFact]):
        self._by_key = {}
        for fact in facts:
            self._by_key.setdefault(normalize_name(fact.name), fact)

    def __len__(self) -> int:
        return len(self._by_key)

    def lookup(self, name: str) -> Optional[NutritionFact]:
        key = normalize_name(name)
        if not key:
            return None
        if key in self._by_key:
            return self._by_key[key]
        alias = ALIASES.get(key)
        return self._by_key.get(normalize_name(alias)) if alias else None
```

- [ ] **Step 5: 运行确认通过**

Run: `python3 -m unittest tests.test_nutrition -v`
Expected: 7 tests OK（若 `test_real_table_has_160_rows` 行数不符，打印实际行数并对照 fixture 表头的 `[160]`，不要改 fixture）

---

### Task 4: 年龄档位、钠预算与适配规则

**Files:**
- Create: `babybite/age_rules.py`, `tests/test_age_rules.py`

**Interfaces:**
- Produces:
  - 常量 `GRAMS_SALT_TO_MG_SODIUM = 393`, `SOURCE_SALT`, `SOURCE_INFANT`, `INFANT_ADVICE`, `MAX_AGE_MONTHS = 216`
  - `AgeBand(min_months, max_months, label, daily_salt_g, source)`、`BANDS`
  - `SodiumBudget(band, daily_sodium_mg, meal_sodium_mg, meal_share)`
  - `band_for(age_months) -> AgeBand`、`sodium_budget(age_months, meal_share=1/3) -> Optional[SodiumBudget]`
  - `parse_allergies(text) -> tuple[str, ...]`（类别：`鱼类`、`乳制品`、`蛋类`、`小麦麸质`）
  - `possible_allergens(name) -> tuple[str, ...]`
  - `Verdict(allowed, reason, preferred, allergens)`、`kid_item_verdict(name, age_months, allergies=()) -> Verdict`

- [ ] **Step 1: 写失败测试** `tests/test_age_rules.py`

```python
import unittest

from babybite.age_rules import (INFANT_ADVICE, band_for, kid_item_verdict, parse_allergies,
                                possible_allergens, sodium_budget)


class BudgetTest(unittest.TestCase):
    def test_bands_and_budgets(self):
        cases = {12: (590, 197), 23: (590, 197), 24: (786, 262), 47: (786, 262),
                 48: (1179, 393), 83: (1179, 393), 84: (1572, 524), 132: (1965, 655), 216: (1965, 655)}
        for months, (daily, meal) in cases.items():
            with self.subTest(months=months):
                budget = sodium_budget(months)
                self.assertEqual((budget.daily_sodium_mg, budget.meal_sodium_mg), (daily, meal))

    def test_infant_gets_no_budget(self):
        self.assertIsNone(sodium_budget(11))
        self.assertIsNone(sodium_budget(0))
        self.assertIn("不建议外食", INFANT_ADVICE)

    def test_invalid_age(self):
        for bad in (-1, 217, True, 1.5):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    band_for(bad)

    def test_meal_share(self):
        self.assertEqual(sodium_budget(24, 0.5).meal_sodium_mg, 393)
        with self.assertRaises(ValueError):
            sodium_budget(24, 0.1)
        with self.assertRaises(ValueError):
            sodium_budget(24, 0.6)

    def test_sources_are_cited(self):
        self.assertIn("T/CNSS 022-2023", band_for(30).source)
        self.assertIn("2022", band_for(18).source)


class VerdictTest(unittest.TestCase):
    def test_excluded_for_everyone(self):
        for name in ("可乐中杯", "麦咖啡™冰美式中杯", "麦辣鸡腿汉堡", "【美汁源】“多汁柠柠”", "热浓浓黑巧中杯"):
            with self.subTest(name=name):
                self.assertFalse(kid_item_verdict(name, 60).allowed)

    def test_juice_and_dessert_only_after_36_months(self):
        self.assertFalse(kid_item_verdict("100%苹果汁", 30).allowed)
        self.assertTrue(kid_item_verdict("100%苹果汁", 40).allowed)
        self.assertFalse(kid_item_verdict("圆筒冰淇淋", 35).allowed)

    def test_preferred(self):
        for name in ("小杯玉米杯", "苹果片一袋(60g)", "纯牛奶", "纯悦"):
            with self.subTest(name=name):
                verdict = kid_item_verdict(name, 18)
                self.assertTrue(verdict.allowed and verdict.preferred)

    def test_allergies(self):
        self.assertEqual(parse_allergies("鱼、蛋 奶,麸质"), ("鱼类", "蛋类", "乳制品", "小麦麸质"))
        self.assertEqual(parse_allergies(None), ())
        with self.assertRaises(ValueError):
            parse_allergies("榴莲")
        verdict = kid_item_verdict("鱼排堡开心乐园餐", 30, ("鱼类",))
        self.assertFalse(verdict.allowed)
        self.assertIn("鱼类", verdict.reason)

    def test_possible_allergens(self):
        self.assertEqual(possible_allergens("麦乐鸡-4块"), ("小麦麸质",))
        self.assertEqual(possible_allergens("纯牛奶"), ("乳制品",))
        self.assertEqual(set(possible_allergens("鱼排堡")), {"鱼类", "小麦麸质"})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m unittest tests.test_age_rules -v`
Expected: `ModuleNotFoundError: No module named 'babybite.age_rules'`

- [ ] **Step 3: 实现** `babybite/age_rules.py`

```python
"""年龄档位、钠预算与"宝宝能不能吃"的规则。常量出处见 docs/design.md 第 4 节。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

GRAMS_SALT_TO_MG_SODIUM = 393  # 1g 食盐约含 393mg 钠
SOURCE_SALT = "中国营养学会《家庭减盐行为指南》T/CNSS 022-2023"
SOURCE_INFANT = "《中国居民膳食指南（2022）》7～24 月龄婴幼儿平衡膳食宝塔"
MAX_AGE_MONTHS = 216
MIN_MEAL_SHARE, MAX_MEAL_SHARE = 0.2, 0.5


@dataclass(frozen=True)
class AgeBand:
    min_months: int
    max_months: Optional[int]  # 不含
    label: str
    daily_salt_g: Optional[float]
    source: str


BANDS = (
    AgeBand(0, 12, "12 月龄以下", None, SOURCE_INFANT),
    AgeBand(12, 24, "1-2 岁", 1.5, SOURCE_INFANT),
    AgeBand(24, 48, "2-3 岁", 2.0, SOURCE_SALT),
    AgeBand(48, 84, "4-6 岁", 3.0, SOURCE_SALT),
    AgeBand(84, 132, "7-10 岁", 4.0, SOURCE_SALT),
    AgeBand(132, None, "11 岁及以上", 5.0, SOURCE_SALT),
)

INFANT_ADVICE = (
    "12 月龄以下的宝宝不建议外食：辅食应单独制作、保持原味、不额外加盐"
    f"（依据：{SOURCE_INFANT}）。带宝宝出门可以自带辅食，大人照常点餐即可。"
)


@dataclass(frozen=True)
class SodiumBudget:
    band: AgeBand
    daily_sodium_mg: int
    meal_sodium_mg: int
    meal_share: float


def band_for(age_months: int) -> AgeBand:
    if isinstance(age_months, bool) or not isinstance(age_months, int) \
            or not 0 <= age_months <= MAX_AGE_MONTHS:
        raise ValueError(f"月龄需为 0 到 {MAX_AGE_MONTHS} 之间的整数")
    for band in BANDS:
        if age_months >= band.min_months and (band.max_months is None or age_months < band.max_months):
            return band
    raise ValueError("月龄超出范围")  # pragma: no cover


def sodium_budget(age_months: int, meal_share: float = 1 / 3) -> Optional[SodiumBudget]:
    """返回钠预算；12 月龄以下返回 None（不推荐外食）。"""
    if not MIN_MEAL_SHARE <= meal_share <= MAX_MEAL_SHARE:
        raise ValueError(f"单餐占比需在 {MIN_MEAL_SHARE} 到 {MAX_MEAL_SHARE} 之间")
    band = band_for(age_months)
    if band.daily_salt_g is None:
        return None
    daily = round(band.daily_salt_g * GRAMS_SALT_TO_MG_SODIUM)
    return SodiumBudget(band, daily, round(daily * meal_share), meal_share)


EXCLUDE_ALL = ("咖啡", "拿铁", "奶铁", "美式", "摩卡", "卡布奇诺", "浓缩", "黑巧", "可乐", "雪碧",
               "芬达", "汽水", "气泡", "怡泉", "红茶", "柠", "橙", "辣")
EXCLUDE_UNDER_36 = ("冰淇淋", "新地", "麦旋风", "圆筒", "派", "奶昔", "果汁", "粥")
PREFERRED = ("玉米杯", "苹果片", "纯牛奶", "纯悦")
ALLERGEN_KEYWORDS = {
    "鱼类": ("鱼", "鳕"),
    "乳制品": ("吉士", "芝士", "奶酪", "牛奶", "奶"),
    "蛋类": ("蛋",),
    "小麦麸质": ("堡", "面包", "派", "麦满分", "卷", "麦乐鸡", "鸡块"),
}
ALLERGY_ALIASES = {
    "鱼": "鱼类", "鱼类": "鱼类", "海鲜": "鱼类",
    "奶": "乳制品", "牛奶": "乳制品", "乳": "乳制品", "乳制品": "乳制品",
    "蛋": "蛋类", "鸡蛋": "蛋类", "蛋类": "蛋类",
    "麸质": "小麦麸质", "小麦": "小麦麸质", "小麦麸质": "小麦麸质",
}


def parse_allergies(text: Optional[str]) -> tuple:
    if not text:
        return ()
    out = []
    for token in re.split(r"[,，、;；\s]+", text.strip()):
        if not token:
            continue
        category = ALLERGY_ALIASES.get(token)
        if category is None:
            raise ValueError(f"不认识的过敏原：{token}，可选：鱼、奶、蛋、麸质")
        if category not in out:
            out.append(category)
    return tuple(out)


def possible_allergens(name: str) -> tuple:
    """按名称关键词判断"可能含"的过敏原类别（官方未提供过敏原数据）。"""
    return tuple(cat for cat, words in ALLERGEN_KEYWORDS.items() if any(w in name for w in words))


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    reason: Optional[str]
    preferred: bool
    allergens: tuple


def kid_item_verdict(name: str, age_months: int, allergies: tuple = ()) -> Verdict:
    allergens = possible_allergens(name)
    preferred = any(word in name for word in PREFERRED)
    for word in EXCLUDE_ALL:
        if word in name:
            return Verdict(False, f"含“{word}”，不适合宝宝", False, allergens)
    if age_months < 36:
        for word in EXCLUDE_UNDER_36:
            if word in name:
                return Verdict(False, f"3 岁以下不建议：{word}", False, allergens)
    hit = [a for a in allergens if a in allergies]
    if hit:
        return Verdict(False, f"可能含{'、'.join(hit)}", preferred, allergens)
    return Verdict(True, None, preferred, allergens)
```

- [ ] **Step 4: 运行确认通过**

Run: `python3 -m unittest tests.test_age_rules -v`
Expected: 10 tests OK

---

### Task 5: 门店、菜单、套餐详情解析

**Files:**
- Create: `babybite/menu.py`, `tests/test_menu.py`

**Interfaces:**
- Produces:
  - `Store(code, name, address, distance_m, open_now, hours, be_code, reservation, reservation_options)`
  - `MenuItem(code, name, price_yuan, category)`
  - `ModValue(code, name, selected_key, unselected_key, selected_quantity)`、`ModGroup(values)`（属性 `toggleable`）
  - `Choice(code, name, is_default, mod_groups)`、`Round(id, name, quantity, choices)`、`MealDetail(code, name, rounds, mod_groups)`
  - `parse_stores(payload) -> list[Store]`、`parse_menu(payload) -> list[MenuItem]`、`parse_meal_detail(payload) -> MealDetail`

- [ ] **Step 1: 写失败测试** `tests/test_menu.py`

```python
import unittest

from babybite.mcp_client import OfflineClient
from babybite.menu import parse_meal_detail, parse_menu, parse_stores
from tests.helpers import load_detail, load_menu


class StoreTest(unittest.TestCase):
    def test_real_stores(self):
        args = {"beType": 1, "searchType": 2, "city": "上海市", "keyword": "人民广场"}
        stores = parse_stores(OfflineClient().call_tool("query-nearby-stores", args))
        first = stores[0]
        self.assertEqual((first.code, first.name), ("1450713", "麦当劳上海黄浦华旭国际大厦餐厅"))
        self.assertEqual((first.distance_m, first.open_now, first.hours), (144, True, "00:00-23:59"))
        self.assertTrue(first.reservation)
        self.assertIsNone(first.be_code)
        self.assertEqual(len(first.reservation_options), 2)
        self.assertEqual(first.reservation_options[0][:2], ("2026-10-12", True))
        self.assertFalse(stores[1].open_now)

    def test_empty_payload(self):
        self.assertEqual(parse_stores({"data": None}), [])
        self.assertEqual(parse_menu({}), [])


class MenuTest(unittest.TestCase):
    def test_real_menu(self):
        menu = load_menu()
        self.assertEqual(len(menu), 86)
        happy = next(m for m in menu if m.code == "9900016057")
        self.assertEqual((happy.name, happy.price_yuan, happy.category), ("汉堡开心乐园餐", 23.5, "开心乐园"))
        self.assertTrue(all("\n" not in m.category for m in menu))


class DetailTest(unittest.TestCase):
    def test_happy_meal_rounds(self):
        detail = load_detail("9900016057")
        self.assertEqual(detail.name, "汉堡开心乐园餐")
        self.assertEqual([r.id for r in detail.rounds], ["1", "2", "3", "4", "5"])
        burger = detail.rounds[0].choices[0]
        self.assertEqual(burger.code, "1000")
        self.assertTrue(burger.mod_groups[0].toggleable)
        self.assertEqual([v.name for v in burger.mod_groups[0].values], ["酸黄瓜", "洋葱粒", "番茄酱", "芥末酱"])
        self.assertEqual(burger.mod_groups[0].values[0].unselected_key, "0-0")
        self.assertEqual([c.is_default for c in detail.rounds[2].choices], [True, True])

    def test_single_item_modification(self):
        detail = load_detail("1120")
        self.assertEqual(detail.rounds, ())
        self.assertEqual([v.name for v in detail.mod_groups[0].values], ["吉士", "酸黄瓜", "洋葱粒", "番茄酱", "芥末酱"])

    def test_ice_group_is_not_toggleable(self):
        detail = load_detail("9900016055")
        cola = detail.rounds[6].choices[0]
        self.assertEqual(cola.name, "可乐中杯")
        self.assertFalse(cola.mod_groups[0].toggleable)

    def test_missing_data(self):
        detail = parse_meal_detail({"data": None})
        self.assertEqual((detail.code, detail.rounds, detail.mod_groups), ("", (), ()))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m unittest tests.test_menu -v`
Expected: `ModuleNotFoundError: No module named 'babybite.menu'`

- [ ] **Step 3: 实现** `babybite/menu.py`

```python
"""门店、菜单、套餐详情的结构化解析（字段见 docs/design.md 3.2）。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Store:
    code: str
    name: str
    address: str
    distance_m: Optional[int]
    open_now: bool
    hours: str
    be_code: Optional[str]
    reservation: bool
    reservation_options: tuple  # ((date, today, text), ...)


@dataclass(frozen=True)
class MenuItem:
    code: str
    name: str
    price_yuan: Optional[float]
    category: str


@dataclass(frozen=True)
class ModValue:
    code: str
    name: str
    selected_key: str
    unselected_key: Optional[str]
    selected_quantity: int


@dataclass(frozen=True)
class ModGroup:
    values: tuple

    @property
    def toggleable(self) -> bool:
        """开关型特制组（每项都有 unselectedKey），例如酱料；冰量这类单选组为 False。"""
        return bool(self.values) and all(v.unselected_key for v in self.values)


@dataclass(frozen=True)
class Choice:
    code: str
    name: str
    is_default: bool
    mod_groups: tuple


@dataclass(frozen=True)
class Round:
    id: str
    name: str
    quantity: int
    choices: tuple


@dataclass(frozen=True)
class MealDetail:
    code: str
    name: str
    rounds: tuple
    mod_groups: tuple


def _clean(text) -> str:
    return str(text or "").replace("\n", "").strip()


def _price(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_stores(payload: dict) -> list:
    stores = []
    for raw in payload.get("data") or []:
        options = tuple(
            (o.get("date", ""), bool(o.get("today")), o.get("reservationOptionText", ""))
            for o in raw.get("reservationTimeOptions") or []
        )
        distance = raw.get("distance")
        stores.append(Store(
            code=str(raw.get("storeCode", "")),
            name=_clean(raw.get("storeName")),
            address=_clean(raw.get("address")),
            distance_m=int(distance) if isinstance(distance, (int, float)) else None,
            open_now=bool(raw.get("businessStatus")),
            hours=f"{raw.get('businessStartTime', '')}-{raw.get('businessEndTime', '')}",
            be_code=raw.get("beCode") or None,
            reservation=bool(raw.get("reservation")),
            reservation_options=options,
        ))
    return stores


def parse_menu(payload: dict) -> list:
    """按分类顺序展开菜单，同一餐品出现在多个分类时只保留第一次。"""
    data = payload.get("data") or {}
    meals = data.get("meals") or {}
    items, seen = [], set()
    for category in data.get("categories") or []:
        cat_name = _clean(category.get("name"))
        for entry in category.get("meals") or []:
            code = str(entry.get("code", ""))
            if code in seen or code not in meals:
                continue
            seen.add(code)
            meal = meals[code]
            items.append(MenuItem(code, _clean(meal.get("name")), _price(meal.get("currentPrice")), cat_name))
    for code, meal in meals.items():  # 未归入任何分类的餐品
        if code not in seen:
            seen.add(code)
            items.append(MenuItem(code, _clean(meal.get("name")), _price(meal.get("currentPrice")), ""))
    return items


def _mod_groups(modification) -> tuple:
    groups = []
    for item in (modification or {}).get("items") or []:
        values = tuple(
            ModValue(
                code=str(v.get("code", "")),
                name=_clean(v.get("name")),
                selected_key=str(v.get("selectedKey", "")),
                unselected_key=v.get("unselectedKey") or None,
                selected_quantity=int(v.get("selectedQuantity") or 0),
            )
            for v in item.get("values") or []
        )
        groups.append(ModGroup(values))
    return tuple(groups)


def parse_meal_detail(payload: dict) -> MealDetail:
    data = payload.get("data") or {}
    rounds = tuple(
        Round(
            id=str(r.get("id", "")),
            name=_clean(r.get("name")),
            quantity=int(r.get("quantity") or 1),
            choices=tuple(
                Choice(str(c.get("code", "")), _clean(c.get("name")), c.get("isDefault") == 1,
                       _mod_groups(c.get("modification")))
                for c in r.get("choices") or []
            ),
        )
        for r in data.get("rounds") or []
    )
    return MealDetail(str(data.get("code", "")), _clean(data.get("name")), rounds,
                      _mod_groups(data.get("modification")))
```

- [ ] **Step 4: 运行确认通过**

Run: `python3 -m unittest tests.test_menu -v`
Expected: 7 tests OK

---

### Task 6: 宝宝特制（换搭配 + 去料 + 下单入参）

**Files:**
- Create: `babybite/customize.py`, `tests/test_customize.py`

**Interfaces:**
- Consumes: `age_rules.kid_item_verdict`；`menu.MealDetail/Round/Choice/ModGroup`
- Produces:
  - `CustomizedLine(round_id, round_name, code, name, quantity, modification, removed, swapped_from)`
  - `CustomizedItem(product_code, name, quantity, lines, salt_requests)`，属性 `removed_all`
  - `should_remove(ingredient, age_months, keep=()) -> bool`
  - `modification_payload(groups, age_months, keep=()) -> (list[dict], list[str])`
  - `pick_choice(round_, age_months, allergies=()) -> Choice`
  - `customize_meal(detail, age_months, allergies=(), keep=(), quantity=1) -> CustomizedItem`
  - `to_order_item(item) -> dict`

- [ ] **Step 1: 写失败测试** `tests/test_customize.py`

```python
import json
import unittest
from pathlib import Path

from babybite.customize import customize_meal, modification_payload, pick_choice, should_remove, to_order_item
from tests.helpers import load_detail

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "real"


def recorded_items(name):
    return json.loads((FIXTURES / name).read_text("utf-8"))["args"]["items"]


class CustomizeTest(unittest.TestCase):
    def test_toddler_burger_happy_meal_matches_real_priced_payload(self):
        item = customize_meal(load_detail("9900016057"), 18)
        self.assertEqual([to_order_item(item)], recorded_items("calculate-price__9900016057_toddler.json"))
        self.assertEqual(item.removed_all, ("酸黄瓜", "洋葱粒", "番茄酱", "芥末酱"))
        self.assertEqual(item.salt_requests, ("牛肉饼不撒盐", "薯条不加盐"))

    def test_nuggets_happy_meal_matches_real_priced_payload(self):
        item = customize_meal(load_detail("9900016056"), 18)
        self.assertEqual([to_order_item(item)], recorded_items("calculate-price__9900016056_toddler.json"))
        self.assertEqual(item.salt_requests, ())

    def test_whole_toggle_group_is_sent(self):
        item = customize_meal(load_detail("9900016058"), 30)
        fish = item.lines[0]
        self.assertEqual(list(fish.modification), [
            {"code": "100214", "key": "0-0", "quantity": 0},
            {"code": "102225", "key": "0-1", "quantity": 1},
        ])
        self.assertEqual(fish.removed, ("番茄酱",))

    def test_cheese_kept_from_48_months_and_keep_option(self):
        detail = load_detail("1120")
        young, older = customize_meal(detail, 30), customize_meal(detail, 48)
        self.assertIn("吉士", young.removed_all)
        self.assertNotIn("吉士", older.removed_all)
        self.assertIn({"code": "100141", "key": "0-1", "quantity": 1}, list(older.lines[0].modification))
        kept = customize_meal(detail, 30, keep=("洋葱",))
        self.assertNotIn("洋葱粒", kept.removed_all)

    def test_single_item_payload_uses_top_level_modification(self):
        payload = to_order_item(customize_meal(load_detail("1406"), 30))
        self.assertNotIn("roundList", payload)
        self.assertEqual(payload["modification"]["values"][0], {"code": "102201", "key": "0-0", "quantity": 0})
        self.assertEqual(payload["modification"]["values"][1], {"code": "120512", "key": "0-1", "quantity": 1})

    def test_group_without_removals_is_omitted_and_ice_group_untouched(self):
        detail = load_detail("9900016055")
        values, removed = modification_payload(detail.rounds[6].choices[0].mod_groups, 30)
        self.assertEqual((values, removed), ([], []))

    def test_snack_round_swaps_fries_to_corn(self):
        detail = load_detail("9900016055")
        choice = pick_choice(detail.rounds[4], 30)
        self.assertEqual(choice.name, "小杯玉米杯")
        line = customize_meal(detail, 30).lines[4]
        self.assertEqual(line.swapped_from, "中薯条")

    def test_dairy_allergy_swaps_milk_to_water(self):
        line = customize_meal(load_detail("9900016058"), 30, allergies=("乳制品",)).lines[3]
        self.assertEqual((line.name, line.swapped_from), ("纯悦", "纯牛奶"))

    def test_should_remove(self):
        self.assertTrue(should_remove("麦香鱼酱", 30))
        self.assertFalse(should_remove("切块生菜", 30))
        self.assertFalse(should_remove("番茄片", 30))
        self.assertFalse(should_remove("吉士", 60))

    def test_quantity_for_two_kids(self):
        self.assertEqual(to_order_item(customize_meal(load_detail("9900016056"), 30, quantity=2))["quantity"], 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m unittest tests.test_customize -v`
Expected: `ModuleNotFoundError: No module named 'babybite.customize'`

- [ ] **Step 3: 实现** `babybite/customize.py`

```python
"""宝宝特制：rounds 换搭配 + modification 去料，生成下单入参（规则见 docs/design.md 3.3、4.2、4.3）。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .age_rules import kid_item_verdict
from .menu import Choice, MealDetail, Round

REMOVE_KEYWORDS = ("酱", "吉士", "芝士", "奶酪", "酸黄瓜", "洋葱", "芥末", "沙拉", "黑椒", "胡椒", "辣", "培根")
CHEESE_WORDS = ("吉士", "芝士", "奶酪")
KEEP_CHEESE_FROM_MONTHS = 48
DRINK_ORDER = ("纯牛奶", "牛奶", "纯悦", "苹果汁")
SNACK_ORDER = ("玉米杯", "苹果片")
PATTY_WORDS = ("汉堡包", "吉士汉堡", "牛堡", "巨无霸", "牛肉")
FRIES_WORD = "薯条"


@dataclass(frozen=True)
class CustomizedLine:
    round_id: Optional[str]
    round_name: str
    code: str
    name: str
    quantity: int
    modification: tuple  # 下单用的特制 values（dict）
    removed: tuple  # 线上已去掉的配料名
    swapped_from: Optional[str]  # 被替换掉的默认选项名


@dataclass(frozen=True)
class CustomizedItem:
    product_code: str
    name: str
    quantity: int
    lines: tuple
    salt_requests: tuple  # 线上做不到、需要请店员帮忙的诉求

    @property
    def removed_all(self) -> tuple:
        seen = []
        for line in self.lines:
            for name in line.removed:
                if name not in seen:
                    seen.append(name)
        return tuple(seen)


def should_remove(ingredient: str, age_months: int, keep: tuple = ()) -> bool:
    if any(k and k in ingredient for k in keep):
        return False
    if age_months >= KEEP_CHEESE_FROM_MONTHS and any(w in ingredient for w in CHEESE_WORDS):
        return False
    return any(k in ingredient for k in REMOVE_KEYWORDS)


def modification_payload(groups: tuple, age_months: int, keep: tuple = ()):
    """按官方 key 规则生成特制 values：开关型组内只要有一项要去掉，整组全部传入。"""
    values, removed = [], []
    for group in groups:
        if not group.toggleable:
            continue
        decisions = [(v, should_remove(v.name, age_months, keep)) for v in group.values]
        if not any(flag for _, flag in decisions):
            continue
        for value, flag in decisions:
            if flag:
                values.append({"code": value.code, "key": value.unselected_key, "quantity": 0})
                removed.append(value.name)
            else:
                values.append({"code": value.code, "key": value.selected_key, "quantity": value.selected_quantity})
    return values, removed


def _rank(name: str, order: tuple) -> Optional[int]:
    for i, keyword in enumerate(order):
        if keyword in name:
            return i
    return None


def pick_choice(round_: Round, age_months: int, allergies: tuple = ()) -> Choice:
    """饮料轮优先牛奶/水，小食轮优先玉米杯/苹果片；其余取默认项。"""
    allowed = [c for c in round_.choices if kid_item_verdict(c.name, age_months, allergies).allowed]
    pool = allowed or list(round_.choices)
    for order in (DRINK_ORDER, SNACK_ORDER):
        ranked = [(rank, i, c) for i, c in enumerate(pool) for rank in [_rank(c.name, order)] if rank is not None]
        if ranked:
            return min(ranked, key=lambda x: (x[0], x[1]))[2]
    defaults = [c for c in pool if c.is_default]
    return (defaults or pool)[0]


def customize_meal(detail: MealDetail, age_months: int, allergies: tuple = (), keep: tuple = (),
                   quantity: int = 1) -> CustomizedItem:
    lines = []
    if detail.rounds:
        for round_ in detail.rounds:
            choice = pick_choice(round_, age_months, allergies)
            values, removed = modification_payload(choice.mod_groups, age_months, keep)
            default = next((c for c in round_.choices if c.is_default), None)
            swapped = default.name if default is not None and default.code != choice.code else None
            lines.append(CustomizedLine(round_.id, round_.name, choice.code, choice.name, round_.quantity,
                                        tuple(values), tuple(removed), swapped))
    else:
        values, removed = modification_payload(detail.mod_groups, age_months, keep)
        lines.append(CustomizedLine(None, detail.name, detail.code, detail.name, 1,
                                    tuple(values), tuple(removed), None))
    names = " ".join(line.name for line in lines)
    salt = []
    if any(word in names for word in PATTY_WORDS):
        salt.append("牛肉饼不撒盐")
    if FRIES_WORD in names:
        salt.append("薯条不加盐")
    return CustomizedItem(detail.code, detail.name, max(1, quantity), tuple(lines), tuple(salt))


def _combo(line: CustomizedLine) -> dict:
    entry = {"code": line.code, "quantity": line.quantity}
    if line.modification:
        entry["modification"] = {"values": [dict(v) for v in line.modification]}
    return entry


def to_order_item(item: CustomizedItem) -> dict:
    """生成 calculate-price / create-order 的 items[] 元素（结构见 docs/design.md 3.3）。"""
    out = {"productCode": item.product_code, "quantity": item.quantity}
    round_lines = [line for line in item.lines if line.round_id is not None]
    if round_lines:
        out["roundList"] = [{"round": line.round_id, "comboItemList": [_combo(line)]} for line in round_lines]
    elif item.lines and item.lines[0].modification:
        out["modification"] = {"values": [dict(v) for v in item.lines[0].modification]}
    return out
```

- [ ] **Step 4: 运行确认通过**

Run: `python3 -m unittest tests.test_customize -v`
Expected: 10 tests OK。`test_toddler_burger_happy_meal_matches_real_priced_payload` 证明生成的入参与已被真实 `calculate-price` 接受的入参逐字段一致。

---

### Task 7: 宝宝餐规划（候选、份量、钠预算、排序）

**Files:**
- Create: `babybite/planner.py`, `tests/test_planner.py`

**Interfaces:**
- Consumes: `age_rules.SodiumBudget/kid_item_verdict/possible_allergens`、`customize.customize_meal/CustomizedItem/CustomizedLine`、`menu.MenuItem/MealDetail/Store`、`nutrition.NutritionIndex`、`scenes.Scene`
- Produces:
  - `PORTIONS`, `PORTION_LABELS`, `FRIES_NOTE`
  - `floor_portion(ratio) -> Optional[float]`、`role_of(name) -> str`（`main/side/fries/skip`）
  - `Component(name, role, sodium_mg, portion, note)`，属性 `kid_sodium_mg`
  - `KidPlan(item, menu_price_yuan, components, kid_sodium_mg, budget, unknown_nutrition, score)`，属性 `meal_pct`、`day_pct`
  - `plan_for_item(item, index, budget, menu_price_yuan=None) -> Optional[KidPlan]`
  - `rank_candidates(menu, age_months, allergies=()) -> list[MenuItem]`
  - `build_plans(candidates, details, index, budget, age_months, allergies=(), keep=(), kids=1) -> (list[KidPlan], list[tuple[str, str]])`
  - `adult_suggestions(menu, limit=3) -> list[MenuItem]`
  - `PlanResult`（dataclass，字段见代码）

- [ ] **Step 1: 写失败测试** `tests/test_planner.py`

```python
import unittest

from babybite.age_rules import sodium_budget
from babybite.customize import CustomizedItem, CustomizedLine, customize_meal
from babybite.menu import MenuItem
from babybite.planner import (adult_suggestions, build_plans, floor_portion, plan_for_item,
                              rank_candidates, role_of)
from tests.helpers import load_detail, load_index, load_menu


def details_for(candidates):
    return {m.code: load_detail(m.code) for m in candidates}


class PortionTest(unittest.TestCase):
    def test_floor_portion(self):
        self.assertEqual([floor_portion(x) for x in (1.2, 0.8, 0.6, 0.4, 0.3, 0.25)],
                         [1.0, 0.75, 0.5, 1 / 3, 0.25, 0.25])
        self.assertIsNone(floor_portion(0.2))

    def test_roles(self):
        self.assertEqual([role_of(n) for n in ("汉堡包", "迷你薯条", "纯牛奶", "海绵宝宝×航海王系列玩具")],
                         ["main", "fries", "side", "skip"])


class PlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = load_index()
        cls.menu = load_menu()

    def test_burger_meal_at_18_months(self):
        budget = sodium_budget(18)
        plan = plan_for_item(customize_meal(load_detail("9900016057"), 18), self.index, budget, 23.5)
        comps = {c.name: c for c in plan.components}
        self.assertEqual(comps["汉堡包"].portion, 0.25)
        self.assertEqual(comps["迷你薯条"].portion, 0.0)
        self.assertEqual(comps["纯牛奶"].portion, 1.0)
        self.assertAlmostEqual(plan.kid_sodium_mg, 197.0)
        self.assertEqual((plan.meal_pct, plan.day_pct), (100, 33))
        self.assertEqual(plan.unknown_nutrition, ())

    def test_nuggets_meal_at_30_months_shows_pieces(self):
        plan = plan_for_item(customize_meal(load_detail("9900016056"), 30), self.index, sodium_budget(30))
        nuggets = plan.components[0]
        self.assertEqual((nuggets.portion, nuggets.note), (0.5, "1/2 份（约 2 块）"))
        self.assertAlmostEqual(plan.kid_sodium_mg, 242.5)

    def test_candidates_and_ranking_at_18_months(self):
        candidates = rank_candidates(self.menu, 18)
        self.assertEqual([m.code for m in candidates], ["9900016057", "9900016058", "9900016056", "1406"])
        plans, excluded = build_plans(candidates, details_for(candidates), self.index, sodium_budget(18), 18)
        self.assertEqual([p.item.name for p in plans], ["汉堡开心乐园餐", "鱼排堡开心乐园餐", "麦乐鸡开心乐园餐"])
        self.assertEqual(excluded, [("板烧鸡腿堡", "即使只吃 1/4 份也会超出本餐钠预算")])

    def test_fish_allergy_removes_fish_candidates(self):
        candidates = rank_candidates(self.menu, 30, ("鱼类",))
        self.assertEqual([m.code for m in candidates], ["9900016057", "9900016056", "1406", "1120"])

    def test_unknown_nutrition_is_marked_and_ranked_lower(self):
        line = CustomizedLine("1", "主食", "X1", "神秘新品堡", 1, (), (), None)
        milk = CustomizedLine("2", "饮料", "3755", "纯牛奶", 1, (), (), None)
        item = CustomizedItem("X", "神秘开心乐园餐", 1, (line, milk), ())
        plan = plan_for_item(item, self.index, sodium_budget(30))
        self.assertEqual(plan.unknown_nutrition, ("神秘新品堡",))
        self.assertIn("无官方营养数据", plan.components[0].note)
        self.assertAlmostEqual(plan.kid_sodium_mg, 73.0)
        known = plan_for_item(customize_meal(load_detail("9900016056"), 30), self.index, sodium_budget(30))
        self.assertLess(plan.score, known.score)

    def test_missing_detail_is_reported(self):
        candidates = rank_candidates(self.menu, 30)[:1]
        plans, excluded = build_plans(candidates, {}, self.index, sodium_budget(30), 30)
        self.assertEqual(plans, [])
        self.assertEqual(excluded, [("汉堡开心乐园餐", "未取到套餐详情")])

    def test_breakfast_muffin_is_a_candidate(self):
        menu = [MenuItem("B1", "烟肉蛋麦满分", 12.0, "麦满分"), MenuItem("B2", "麦满分单人餐", 19.9, "人气热卖"),
                MenuItem("B3", "皮蛋鸡肉粥", 9.0, "粥王系列")]
        self.assertEqual([m.code for m in rank_candidates(menu, 18)], ["B1"])
        line = CustomizedLine(None, "烟肉蛋麦满分", "B1", "烟肉蛋麦满分", 1, (), (), None)
        plan = plan_for_item(CustomizedItem("B1", "烟肉蛋麦满分", 1, (line,), ()), self.index, sodium_budget(18))
        self.assertEqual(plan.components[0].note, "1/3 份")
        self.assertAlmostEqual(plan.kid_sodium_mg, 161.0)

    def test_adult_suggestions(self):
        self.assertEqual([m.name for m in adult_suggestions(self.menu)],
                         ["人气超值四件套随心选", "鱼牛汉堡四件套随心选", "“我就喜欢”鸡薯双全盒"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m unittest tests.test_planner -v`
Expected: `ModuleNotFoundError: No module named 'babybite.planner'`

- [ ] **Step 3: 实现** `babybite/planner.py`

```python
"""在门店真实菜单中挑选宝宝餐并计算份量（规则见 docs/design.md 第 5 节）。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .age_rules import SodiumBudget, kid_item_verdict, possible_allergens
from .customize import CustomizedItem, customize_meal
from .menu import Store
from .nutrition import NutritionIndex
from .scenes import Scene

PORTIONS = (1.0, 0.75, 0.5, 1 / 3, 0.25)
PORTION_LABELS = {1.0: "整份", 0.75: "3/4 份", 0.5: "1/2 份", 1 / 3: "1/3 份", 0.25: "1/4 份"}
SIDE_WORDS = ("玉米杯", "苹果片", "纯牛奶", "牛奶", "纯悦", "苹果汁")
SKIP_WORDS = ("玩具",)
KID_MEAL_WORD = "开心乐园"
SINGLE_MAIN_WORDS = ("汉堡包", "吉士汉堡", "鱼排堡", "麦香鱼", "麦乐鸡", "板烧鸡腿堡", "麦满分")  # 麦满分：早餐时段
COMBO_WORDS = ("套餐", "件套", "亲子", "双人", "随心", "精选", "单人餐")
MAX_CANDIDATES = 4
MAX_PLANS = 3
CUSTOMIZE_BONUS = 0.05  # 每去掉一种配料 / 每条减盐诉求：实际钠低于官方整份数值
ADULT_CATEGORY_WORDS = ("精选单人餐", "人气热卖")
FRIES_NOTE = "建议大人吃，宝宝最多尝 2-3 根"
UNKNOWN_NOTE = "无官方营养数据，未计入钠合计，建议先给 1/2 份"


def floor_portion(ratio: float) -> Optional[float]:
    """向下取到最近的份量档位；不足 1/4 返回 None。"""
    for portion in PORTIONS:
        if ratio >= portion - 1e-9:
            return portion
    return None


def role_of(name: str) -> str:
    if any(w in name for w in SKIP_WORDS):
        return "skip"
    if "薯条" in name:
        return "fries"
    if any(w in name for w in SIDE_WORDS):
        return "side"
    return "main"


def _portion_note(name: str, portion: float) -> str:
    label = PORTION_LABELS[portion]
    match = re.search(r"(\d+)\s*块", name)
    if match and portion < 1.0:
        pieces = max(1, round(int(match.group(1)) * portion))
        return f"{label}（约 {pieces} 块）"
    return label


@dataclass(frozen=True)
class Component:
    name: str
    role: str  # main / side / fries / skip
    sodium_mg: Optional[float]
    portion: float
    note: str

    @property
    def kid_sodium_mg(self) -> Optional[float]:
        return None if self.sodium_mg is None else self.sodium_mg * self.portion


@dataclass(frozen=True)
class KidPlan:
    item: CustomizedItem
    menu_price_yuan: Optional[float]
    components: tuple  # 与 item.lines 一一对应
    kid_sodium_mg: float
    budget: SodiumBudget
    unknown_nutrition: tuple
    score: float

    @property
    def meal_pct(self) -> int:
        return round(self.kid_sodium_mg / self.budget.meal_sodium_mg * 100)

    @property
    def day_pct(self) -> int:
        return round(self.kid_sodium_mg / self.budget.daily_sodium_mg * 100)


def plan_for_item(item: CustomizedItem, index: NutritionIndex, budget: SodiumBudget,
                  menu_price_yuan: Optional[float] = None) -> Optional[KidPlan]:
    """配菜饮品整份计入，剩余预算平均分给主食；任一主食不足 1/4 份时返回 None。"""
    rows = []
    for line in item.lines:
        role = role_of(line.name)
        fact = index.lookup(line.name) if role != "skip" else None
        rows.append((line, role, fact.sodium_mg if fact else None))
    unknown = tuple(line.name for line, role, sodium in rows if role != "skip" and sodium is None)
    side_sodium = sum(s for _, role, s in rows if role == "side" and s is not None)
    known_mains = [s for _, role, s in rows if role == "main" and s is not None]
    per_main = (budget.meal_sodium_mg - side_sodium) / len(known_mains) if known_mains else 0.0
    components = []
    for line, role, sodium in rows:
        if role == "side":
            components.append(Component(line.name, role, sodium, 1.0, "整份"))
        elif role == "fries":
            components.append(Component(line.name, role, sodium, 0.0, FRIES_NOTE))
        elif role == "skip":
            components.append(Component(line.name, role, None, 0.0, "不计入"))
        elif sodium is None:
            components.append(Component(line.name, role, None, 0.5, UNKNOWN_NOTE))
        else:
            portion = floor_portion(per_main / sodium) if sodium > 0 else 1.0
            if portion is None:
                return None
            components.append(Component(line.name, role, sodium, portion, _portion_note(line.name, portion)))
    kid_sodium = sum(c.kid_sodium_mg for c in components if c.kid_sodium_mg is not None)
    allergens = {a for line, role, _ in rows if role != "skip" for a in possible_allergens(line.name)}
    score = (1 - kid_sodium / budget.meal_sodium_mg) + (2.0 if KID_MEAL_WORD in item.name else 0.0) \
        + CUSTOMIZE_BONUS * (len(item.removed_all) + len(item.salt_requests)) \
        - len(unknown) - 0.1 * len(allergens)
    return KidPlan(item, menu_price_yuan, tuple(components), kid_sodium, budget, unknown, score)


def rank_candidates(menu: list, age_months: int, allergies: tuple = ()) -> list:
    """开心乐园餐优先，其次单点主食；最多 MAX_CANDIDATES 个，控制接口调用次数。"""
    kid_meals = [m for m in menu if KID_MEAL_WORD in m.category and not any(w in m.name for w in ("亲子", "双人"))]
    singles = [m for m in menu if any(w in m.name for w in SINGLE_MAIN_WORDS)
               and not any(w in m.name for w in COMBO_WORDS)]
    out, seen = [], set()
    for item in kid_meals + singles:
        if item.code in seen or not kid_item_verdict(item.name, age_months, allergies).allowed:
            continue
        seen.add(item.code)
        out.append(item)
    return out[:MAX_CANDIDATES]


def build_plans(candidates: list, details: dict, index: NutritionIndex, budget: SodiumBudget,
                age_months: int, allergies: tuple = (), keep: tuple = (), kids: int = 1):
    plans, excluded = [], []
    for menu_item in candidates:
        detail = details.get(menu_item.code)
        if detail is None:
            excluded.append((menu_item.name, "未取到套餐详情"))
            continue
        item = customize_meal(detail, age_months, allergies, keep, quantity=kids)
        bad = [line.name for line in item.lines
               if role_of(line.name) != "skip" and not kid_item_verdict(line.name, age_months, allergies).allowed]
        if bad:
            excluded.append((menu_item.name, f"含不适合宝宝的子项：{'、'.join(bad)}"))
            continue
        plan = plan_for_item(item, index, budget, menu_item.price_yuan)
        if plan is None:
            excluded.append((menu_item.name, "即使只吃 1/4 份也会超出本餐钠预算"))
            continue
        plans.append(plan)
    plans.sort(key=lambda p: -p.score)
    return plans[:MAX_PLANS], excluded


def adult_suggestions(menu: list, limit: int = 3) -> list:
    picks = []
    for word in ADULT_CATEGORY_WORDS:
        for item in menu:
            if word in item.category and item not in picks and KID_MEAL_WORD not in item.name:
                picks.append(item)
    return picks[:limit]


@dataclass
class PlanResult:
    age_months: int
    kids: int
    adults: int
    scene: Scene
    store: Store
    reservation_date: Optional[str]
    budget: SodiumBudget
    plans: list
    excluded: list
    adult_suggestions: list
    price_cents: Optional[int] = None
    take_ways: list = field(default_factory=list)
    offline: bool = False
    notices: list = field(default_factory=list)
    address_id: Optional[str] = None
```

- [ ] **Step 4: 运行确认通过**

Run: `python3 -m unittest tests.test_planner -v`
Expected: 9 tests OK。若 `test_candidates_and_ranking_at_18_months` 的排序与预期不符，打印每个方案的 `score` 与 `kid_sodium_mg` 报告给控制者，**不要修改测试期望值**。

---

### Task 8: 渲染（Markdown / JSON / HTML / 话术卡 / 外送备注）

**Files:**
- Create: `babybite/cards.py`, `tests/test_cards.py`

**Interfaces:**
- Consumes: `planner.PlanResult/KidPlan`、`customize.CustomizedItem/to_order_item`、`age_rules.GRAMS_SALT_TO_MG_SODIUM`
- Produces:
  - `REMARK_MAX = 50`、`BANNED_PHRASES`、`OFFLINE_NOTICE`、`DISCLAIMER`、`TIPS`
  - `age_label(age_months) -> str`
  - `staff_script(item, age_months) -> str`
  - `delivery_remark(item) -> str`
  - `plan_to_dict(result) -> dict`、`render_json(result) -> str`、`render_markdown(result) -> str`、`render_html(result) -> str`

- [ ] **Step 1: 写失败测试** `tests/test_cards.py`

```python
import json
import unittest

from babybite.age_rules import sodium_budget
from babybite.cards import (BANNED_PHRASES, REMARK_MAX, age_label, delivery_remark, render_html,
                            render_json, render_markdown, staff_script)
from babybite.customize import CustomizedItem, customize_meal
from babybite.menu import Store
from babybite.planner import PlanResult, adult_suggestions, build_plans, rank_candidates
from babybite.scenes import get_scene
from tests.helpers import LUNCH, load_detail, load_index, load_menu

STORE = Store("1450713", "麦当劳上海黄浦华旭国际大厦餐厅", "南京东路街道西藏中路336号", 144, True,
              "00:00-23:59", None, True, ())


def make_result(age=18, allergies=(), scene="pickup"):
    menu = load_menu()
    candidates = rank_candidates(menu, age, allergies)
    details = {m.code: load_detail(m.code) for m in candidates}
    budget = sodium_budget(age)
    plans, excluded = build_plans(candidates, details, load_index(), budget, age, allergies)
    return PlanResult(age, 1, 2, get_scene(scene), STORE, LUNCH, budget, plans, excluded,
                      adult_suggestions(menu), price_cents=2350, offline=True)


class TextTest(unittest.TestCase):
    def test_age_label(self):
        self.assertEqual([age_label(m) for m in (9, 12, 18, 30, 48)],
                         ["9 个月", "1 岁", "1 岁 6 个月", "2 岁 6 个月", "4 岁"])

    def test_staff_script(self):
        item = customize_meal(load_detail("9900016057"), 18)
        text = staff_script(item, 18)
        self.assertIn("给 1 岁 6 个月宝宝吃的", text)
        self.assertIn("酸黄瓜、洋葱粒、番茄酱、芥末酱", text)
        self.assertIn("牛肉饼不撒盐、薯条不加盐", text)
        self.assertIn("做不到也没关系", text)

    def test_staff_script_without_salt_request(self):
        text = staff_script(customize_meal(load_detail("9900016056"), 18), 18)
        self.assertNotIn("做不到", text)
        self.assertNotIn("线上已经去掉", text)
        self.assertIn("按正常出餐即可", text)

    def test_delivery_remark(self):
        item = customize_meal(load_detail("9900016057"), 18)
        remark = delivery_remark(item)
        self.assertTrue(remark.startswith("宝宝餐："))
        self.assertLessEqual(len(remark), REMARK_MAX)
        long_item = CustomizedItem("X", "X", 1, (), tuple(["牛肉饼不撒盐"] * 20))
        self.assertEqual(len(delivery_remark(long_item)), REMARK_MAX)
        self.assertEqual(delivery_remark(CustomizedItem("X", "X", 1, (), ())), "")


class RenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = make_result()

    def test_markdown_sections_and_numbers(self):
        text = render_markdown(self.result)
        for part in ("# 小小麦门 · 带娃吃麦定制单", "## 主推：汉堡开心乐园餐 × 1", "### 店员话术卡",
                     "## 备选", "## 未推荐", "## 大人餐参考", "## 温馨提示", "## 说明",
                     "本餐 197mg", "实时核价 ¥23.50", "离线演示",
                     "| 汉堡包 | 线上已去：酸黄瓜、洋葱粒、番茄酱、芥末酱 | 492mg | 1/4 份 | ≤123mg |",
                     "| 纯牛奶 | - | 73mg | 整份 | 73mg |", "本餐宝宝钠合计 ≤197mg",
                     "麦乐鸡开心乐园餐：麦乐鸡-4块 1/3 份（约 1 块）；宝宝钠 约 186mg"):
            with self.subTest(part=part):
                self.assertIn(part, text)

    def test_markdown_shows_swap(self):
        text = render_markdown(make_result(age=30, allergies=("乳制品",)))
        self.assertIn("已换成纯悦（原：纯牛奶）", text)

    def test_no_banned_phrases(self):
        for text in (render_markdown(self.result), render_html(self.result)):
            for phrase in BANNED_PHRASES:
                self.assertNotIn(phrase, text)

    def test_json_contains_order_item(self):
        data = json.loads(render_json(self.result))
        self.assertEqual(data["plans"][0]["productCode"], "9900016057")
        self.assertEqual(data["plans"][0]["orderItem"]["productCode"], "9900016057")
        self.assertEqual(data["store"]["code"], "1450713")
        self.assertTrue(data["offline"])

    def test_html_escapes(self):
        store = Store("1", "<script>alert(1)</script>", "addr", None, True, "-", None, False, ())
        result = make_result()
        result.store = store
        html_text = render_html(result)
        self.assertTrue(html_text.startswith("<!doctype html>"))
        self.assertNotIn("<script>alert(1)</script>", html_text)
        self.assertIn("&lt;script&gt;", html_text)

    def test_store_line_skips_missing_fields(self):
        result = make_result()
        result.store = Store("1", "麦当劳某外送店", "", None, True, "00:00-23:59", "BE1", False, ())
        self.assertIn("- 门店：麦当劳某外送店（营业 00:00-23:59）\n", render_markdown(result))
        result.store = Store("1", "门店 1", "", None, True, "-", None, False, ())
        self.assertIn("- 门店：门店 1\n", render_markdown(result))

    def test_no_plans(self):
        result = make_result()
        result.plans = []
        self.assertIn("## 暂无合适的宝宝餐", render_markdown(result))
        self.assertIn("暂无合适的宝宝餐", render_html(result))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m unittest tests.test_cards -v`
Expected: `ModuleNotFoundError: No module named 'babybite.cards'`

- [ ] **Step 3: 实现** `babybite/cards.py`

```python
"""把 PlanResult 渲染为终端 Markdown、JSON、HTML 卡片，以及店员话术卡和外送备注。"""
from __future__ import annotations

import html
import json
from typing import Optional

from .age_rules import GRAMS_SALT_TO_MG_SODIUM
from .customize import CustomizedItem, to_order_item
from .planner import KidPlan, PlanResult

REMARK_MAX = 50
BANNED_PHRASES = ("肯德基", "汉堡王", "KFC", "垃圾食品", "不健康", "最健康", "营养均衡", "绝对安全")
TIPS = (
    "偶尔吃，吃得明白：外食不宜频繁，回家后搭配蔬果和白水。",
    "拿到餐先尝一口温度和咸淡，再分给宝宝。",
    "3 岁以下把汉堡、鸡块撕成小块，全程看护进食。",
)
DISCLAIMER = (
    "营养数据来自麦当劳 MCP 官方实时接口，为默认配方整份数值；线上去料后实际钠更低，但官方未提供分项数据，"
    "本工具只按“不高于”计算。过敏原为按名称的提示，请以门店信息为准。本项目为参赛作品，非麦当劳官方产品，"
    "不构成医疗或营养建议；餐品、价格与供应以麦当劳官方渠道为准。"
)
OFFLINE_NOTICE = "离线演示：数据为 2026-10-12 用真实 Token 录制的上海黄浦华旭国际大厦餐厅午餐时段结果。"
NO_PLAN_TEXT = "这家店当前菜单里没有能放进本餐钠预算的组合，可以换个门店或时间再试。"


def age_label(age_months: int) -> str:
    if age_months < 12:
        return f"{age_months} 个月"
    years, months = divmod(age_months, 12)
    return f"{years} 岁" + (f" {months} 个月" if months else "")


def staff_script(item: CustomizedItem, age_months: int) -> str:
    text = f"您好，这份{item.name}是给 {age_label(age_months)}宝宝吃的。"
    if not item.removed_all and not item.salt_requests:
        return text + "按正常出餐即可，谢谢您！"
    if item.removed_all:
        text += f"线上已经去掉：{'、'.join(item.removed_all)}。"
    if item.salt_requests:
        text += f"如果方便的话，麻烦{'、'.join(item.salt_requests)}。做不到也没关系，"
    return text + "谢谢您！"


def delivery_remark(item: CustomizedItem) -> str:
    """外送订单备注（≤50 字）；没有需要店员帮忙的诉求时返回空串。"""
    if not item.salt_requests:
        return ""
    return ("宝宝餐：" + "，".join(item.salt_requests) + "，谢谢")[:REMARK_MAX]


def _mg(value: Optional[float]) -> str:
    return "无官方数据" if value is None else f"{value:.0f}mg"


def _handling(line) -> str:
    parts = []
    if line.removed:
        parts.append("线上已去：" + "、".join(line.removed))
    if line.swapped_from:
        parts.append(f"已换成{line.name}（原：{line.swapped_from}）")
    return "；".join(parts) or "-"


def _kid_mg(line, comp) -> str:
    if comp.kid_sodium_mg is None or comp.portion == 0:
        return "-"
    return f"{'≤' if line.removed else ''}{comp.kid_sodium_mg:.0f}mg"


def _total_prefix(plan: KidPlan) -> str:
    """有去料或减盐诉求时实际钠低于官方数值，写"≤"；否则按官方数值写"约"。"""
    return "≤" if plan.item.removed_all or plan.item.salt_requests else "约 "


def _rows(plan: KidPlan):
    """(子项名, 处理, 官方钠, 份量, 宝宝摄入钠)，跳过玩具等不计入项。"""
    for line, comp in zip(plan.item.lines, plan.components):
        if comp.role != "skip":
            yield line.name, _handling(line), _mg(comp.sodium_mg), comp.note, _kid_mg(line, comp)


def _price_text(plan: KidPlan, price_cents: Optional[int]) -> str:
    parts = []
    if plan.menu_price_yuan is not None:
        parts.append(f"菜单价 ¥{plan.menu_price_yuan:g}")
    if price_cents is not None:
        parts.append(f"实时核价 ¥{price_cents / 100:.2f}")
    return " / ".join(parts)


def _summary(plan: KidPlan) -> str:
    return (f"本餐宝宝钠合计 {_total_prefix(plan)}{plan.kid_sodium_mg:.0f}mg，约占本餐预算 {plan.meal_pct}%、"
            f"全天上限 {plan.day_pct}%。")


def _budget_text(result: PlanResult) -> str:
    b = result.budget
    return (f"本餐 {b.meal_sodium_mg}mg（全天上限 {b.daily_sodium_mg}mg = 食盐 {b.band.daily_salt_g:g}g × "
            f"{GRAMS_SALT_TO_MG_SODIUM}，按 {round(b.meal_share * 100)}% 分到这一餐；依据：{b.band.source}）")


def _alt_text(plan: KidPlan) -> str:
    mains = "、".join(f"{c.name} {c.note}" for c in plan.components if c.role == "main")
    return f"{plan.item.name}：{mains}；宝宝钠 {_total_prefix(plan)}{plan.kid_sodium_mg:.0f}mg（本餐预算 {plan.meal_pct}%）"


def render_markdown(result: PlanResult) -> str:
    out = ["# 小小麦门 · 带娃吃麦定制单", ""]
    if result.offline:
        out += [f"> {OFFLINE_NOTICE}", ""]
    out += [f"> {notice}" for notice in result.notices] + ([""] if result.notices else [])
    store = result.store
    where = [part for part in (store.address,
                               f"距离 {store.distance_m}m" if store.distance_m is not None else "",
                               f"营业 {store.hours}" if store.hours.strip("- ") else "") if part]
    when = f"预约 {result.reservation_date}" if result.reservation_date else "现在"
    out += [
        f"- 门店：{store.name}" + (f"（{'，'.join(where)}）" if where else ""),
        f"- 方式：{result.scene.label}；时间：{when}",
        f"- 宝宝：{age_label(result.age_months)} × {result.kids}；大人 × {result.adults}",
        f"- 钠预算：{_budget_text(result)}",
        "",
    ]
    if not result.plans:
        out += ["## 暂无合适的宝宝餐", "", NO_PLAN_TEXT, ""]
    else:
        top = result.plans[0]
        out += [f"## 主推：{top.item.name} × {top.item.quantity}", ""]
        price = _price_text(top, result.price_cents)
        if price:
            out += [price, ""]
        out += ["| 组成 | 处理 | 官方钠 | 宝宝份量 | 宝宝摄入钠 |", "|---|---|---|---|---|"]
        out += [f"| {' | '.join(row)} |" for row in _rows(top)]
        out += ["", _summary(top), "", "### 店员话术卡", "", "> " + staff_script(top.item, result.age_months), ""]
        if result.scene.key == "delivery" and delivery_remark(top.item):
            out += [f"外送订单备注（下单时自动填写）：{delivery_remark(top.item)}", ""]
        if len(result.plans) > 1:
            out += ["## 备选", ""] + [f"- {_alt_text(p)}" for p in result.plans[1:]] + [""]
    if result.excluded:
        out += ["## 未推荐", ""] + [f"- {name}：{reason}" for name, reason in result.excluded] + [""]
    if result.adult_suggestions:
        out += ["## 大人餐参考", ""]
        out += [f"- {m.name}" + (f" ¥{m.price_yuan:g}" if m.price_yuan is not None else "")
                for m in result.adult_suggestions]
        out.append("")
    out += ["## 温馨提示", ""] + [f"- {tip}" for tip in TIPS] + [""]
    out += ["## 说明", "", DISCLAIMER, ""]
    return "\n".join(out)


def plan_to_dict(result: PlanResult) -> dict:
    def plan_dict(plan: KidPlan) -> dict:
        return {
            "name": plan.item.name,
            "productCode": plan.item.product_code,
            "quantity": plan.item.quantity,
            "menuPriceYuan": plan.menu_price_yuan,
            "kidSodiumMg": round(plan.kid_sodium_mg, 1),
            "mealBudgetPct": plan.meal_pct,
            "dayLimitPct": plan.day_pct,
            "removed": list(plan.item.removed_all),
            "saltRequests": list(plan.item.salt_requests),
            "components": [{"name": c.name, "role": c.role, "sodiumMg": c.sodium_mg,
                            "portion": round(c.portion, 3), "note": c.note} for c in plan.components],
            "unknownNutrition": list(plan.unknown_nutrition),
            "staffScript": staff_script(plan.item, result.age_months),
            "orderItem": to_order_item(plan.item),
        }

    store = result.store
    remark = delivery_remark(result.plans[0].item) if result.plans and result.scene.key == "delivery" else ""
    return {
        "version": 1,
        "ageMonths": result.age_months,
        "kids": result.kids,
        "adults": result.adults,
        "scene": result.scene.key,
        "store": {"code": store.code, "name": store.name, "address": store.address, "beCode": store.be_code},
        "addressId": result.address_id,
        "reservationDate": result.reservation_date,
        "budget": {"dailySodiumMg": result.budget.daily_sodium_mg, "mealSodiumMg": result.budget.meal_sodium_mg,
                   "dailySaltG": result.budget.band.daily_salt_g, "source": result.budget.band.source},
        "plans": [plan_dict(p) for p in result.plans],
        "excluded": [{"name": n, "reason": r} for n, r in result.excluded],
        "priceCents": result.price_cents,
        "remark": remark,
        "offline": result.offline,
        "notices": list(result.notices),
    }


def render_json(result: PlanResult) -> str:
    return json.dumps(plan_to_dict(result), ensure_ascii=False, indent=2)


_CSS = """
body{margin:0;background:#fff8e7;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;color:#2b2b2b}
.wrap{max-width:720px;margin:0 auto;padding:24px}
.hero{background:#da291c;color:#fff;border-radius:20px;padding:20px 24px}
.hero h1{margin:0 0 8px;font-size:24px}.hero p{margin:3px 0}
.card{background:#fff;border-radius:16px;padding:18px 20px;margin-top:16px;box-shadow:0 2px 10px rgba(0,0,0,.06)}
.card h2{margin:0 0 10px;font-size:18px}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{padding:8px 6px;border-bottom:1px solid #f1e6c8;text-align:left;vertical-align:top}
.bar{height:12px;background:#f6e7b5;border-radius:6px;overflow:hidden;margin:10px 0}.bar i{display:block;height:100%;background:#ffbc0d}
.script{background:#ffbc0d;border-radius:16px;padding:20px;font-size:20px;line-height:1.6;font-weight:600}
.muted{color:#7a6f5a;font-size:13px;line-height:1.6}ul{padding-left:20px;margin:0}
"""


def render_html(result: PlanResult) -> str:
    e = html.escape
    store = result.store
    parts = [
        "<!doctype html>",
        '<html lang="zh-CN"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        "<title>小小麦门 · 带娃吃麦定制单</title>",
        f"<style>{_CSS}</style></head><body><div class=\"wrap\">",
        '<div class="hero"><h1>小小麦门 · 带娃吃麦定制单</h1>',
        f"<p>{e(store.name)}</p>",
        f"<p>宝宝 {e(age_label(result.age_months))} × {result.kids} · {e(result.scene.label)}</p>",
        f"<p>本餐钠预算 {result.budget.meal_sodium_mg}mg</p></div>",
    ]
    if result.offline:
        parts.append(f'<p class="muted">{e(OFFLINE_NOTICE)}</p>')
    if not result.plans:
        parts.append(f'<div class="card"><h2>暂无合适的宝宝餐</h2><p>{e(NO_PLAN_TEXT)}</p></div>')
    else:
        top = result.plans[0]
        rows = "".join("<tr>" + "".join(f"<td>{e(cell)}</td>" for cell in row) + "</tr>" for row in _rows(top))
        width = max(0, min(top.meal_pct, 100))
        price = _price_text(top, result.price_cents)
        parts += [
            f'<div class="card"><h2>主推：{e(top.item.name)} × {top.item.quantity}</h2>',
            f'<p class="muted">{e(price)}</p>' if price else "",
            "<table><tr><th>组成</th><th>处理</th><th>官方钠</th><th>宝宝份量</th><th>宝宝摄入钠</th></tr>",
            rows, "</table>",
            f'<div class="bar"><i style="width:{width}%"></i></div><p>{e(_summary(top))}</p></div>',
            f'<div class="card"><h2>店员话术卡</h2><div class="script">{e(staff_script(top.item, result.age_months))}</div></div>',
        ]
        if len(result.plans) > 1:
            items = "".join(f"<li>{e(_alt_text(p))}</li>" for p in result.plans[1:])
            parts.append(f'<div class="card"><h2>备选</h2><ul>{items}</ul></div>')
    tips = "".join(f"<li>{e(t)}</li>" for t in TIPS)
    parts += [
        f'<div class="card"><h2>温馨提示</h2><ul>{tips}</ul></div>',
        f'<p class="muted">{e(_budget_text(result))}</p>',
        f'<p class="muted">{e(DISCLAIMER)}</p>',
        "</div></body></html>",
    ]
    return "\n".join(p for p in parts if p)
```

- [ ] **Step 4: 运行确认通过**

Run: `python3 -m unittest tests.test_cards -v`
Expected: 10 tests OK

---

### Task 9: 命令行（plan / stores / order / verify / cancel）与离线黄金输出

**Files:**
- Create: `babybite/cli.py`, `babybite/__main__.py`, `tests/test_cli.py`, `tests/golden/plan_18m_offline.md`

**Interfaces:**
- Consumes: 前述所有模块
- Produces:
  - `main(argv=None, client_factory=None, out=None) -> int`；`client_factory(offline: bool)` 返回带 `call_tool(name, args)` 的客户端
  - 退出码：`EXIT_OK=0`、`EXIT_USAGE=2`、`EXIT_AUTH=3`、`EXIT_BUSINESS=4`、`EXIT_ERROR=5`
  - 常量 `OFFLINE_WHEN = "2026-10-12 11:30"`、`OFFLINE_CITY = "上海市"`、`OFFLINE_KEYWORD = "人民广场"`

- [ ] **Step 1: 写失败测试** `tests/test_cli.py`

```python
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from babybite.cli import EXIT_AUTH, EXIT_BUSINESS, EXIT_ERROR, EXIT_OK, EXIT_USAGE, main
from babybite.errors import AuthError, McdBusinessError
from babybite.mcp_client import OfflineClient

GOLDEN = Path(__file__).resolve().parent / "golden" / "plan_18m_offline.md"


def run(argv, factory=None):
    out = io.StringIO()
    with redirect_stderr(io.StringIO()):
        code = main(argv, client_factory=factory, out=out)
    return code, out.getvalue()


class ScriptedClient:
    """按工具名返回预设 payload；记录调用。"""

    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = []

    def call_tool(self, name, args):
        self.calls.append((name, args))
        value = self.payloads[name]
        if isinstance(value, Exception):
            raise value
        return value


def forbid(offline):
    raise AssertionError("不应创建客户端")


class PlanCommandTest(unittest.TestCase):
    def test_offline_plan_matches_golden(self):
        code, text = run(["plan", "--age-months", "18", "--offline", "--adults", "2"])
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(text, GOLDEN.read_text("utf-8"))

    def test_infant_does_not_call_api(self):
        code, text = run(["plan", "--age-months", "9", "--city", "上海市", "--keyword", "人民广场"], forbid)
        self.assertEqual(code, EXIT_OK)
        self.assertIn("不建议外食", text)

    def test_invalid_age_exit_code(self):
        self.assertEqual(run(["plan", "--age-months", "300", "--offline"], forbid)[0], EXIT_USAGE)
        self.assertEqual(run(["plan", "--age-months", "18", "--offline", "--allergy", "榴莲"], forbid)[0], EXIT_USAGE)

    def test_json_and_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            saved, card = Path(tmp) / "plan.json", Path(tmp) / "card.html"
            code, text = run(["plan", "--age-months", "18", "--offline", "--json", "--save", str(saved), "--card", str(card)])
            self.assertEqual(code, EXIT_OK)
            data = json.loads(text)
            self.assertEqual(data["priceCents"], 2350)
            self.assertEqual(json.loads(saved.read_text("utf-8"))["plans"][0]["productCode"], "9900016057")
            self.assertTrue(card.read_text("utf-8").startswith("<!doctype html>"))

    def test_all_stores_closed_without_when(self):
        store = {"storeCode": "1", "storeName": "店", "businessStatus": False, "reservation": True}
        client = ScriptedClient({"query-nearby-stores": {"data": [store]}})
        code, _ = run(["plan", "--age-months", "18", "--city", "上海市", "--keyword", "某地"], lambda offline: client)
        self.assertEqual(code, EXIT_ERROR)

    def test_closed_store_business_error_hint(self):
        store = {"storeCode": "1", "storeName": "店", "businessStatus": True}
        client = ScriptedClient({"query-nearby-stores": {"data": [store]},
                                 "query-meals": McdBusinessError(600057, "门店可能已关闭或不在营业时间")})
        code, _ = run(["plan", "--age-months", "18", "--city", "上海市", "--keyword", "某地"], lambda offline: client)
        self.assertEqual(code, EXIT_BUSINESS)

    def test_auth_error_exit_code(self):
        def no_token(offline):
            raise AuthError("未设置环境变量 MCD_MCP_TOKEN")
        self.assertEqual(run(["plan", "--age-months", "18", "--city", "上海市", "--keyword", "x"], no_token)[0], EXIT_AUTH)

    def test_drive_store_requires_be_code(self):
        self.assertEqual(run(["plan", "--age-months", "18", "--scene", "drive", "--store", "1"], forbid)[0], EXIT_USAGE)


class OrderCommandTest(unittest.TestCase):
    def saved_plan(self, tmp, offline=False):
        path = Path(tmp) / "plan.json"
        run(["plan", "--age-months", "18", "--offline", "--save", str(path)])
        data = json.loads(path.read_text("utf-8"))
        data["offline"] = offline
        path.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
        return path

    def test_order_without_confirm_only_prices(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.saved_plan(tmp)
            client = ScriptedClient({"calculate-price": {"data": {"price": 2500, "takeWayList": [{"code": "locker-out"}]}}})
            code, text = run(["order", "--plan", str(path)], lambda offline: client)
            self.assertEqual(code, EXIT_OK)
            self.assertIn("¥25.00", text)
            self.assertEqual([c[0] for c in client.calls], ["calculate-price"])

    def test_order_confirm_creates_once_with_take_way(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.saved_plan(tmp)
            client = ScriptedClient({"calculate-price": {"data": {"price": 2500, "takeWayList": [{"code": "locker-out"}]}},
                                     "create-order": {"data": {"orderId": "T1"}}})
            code, text = run(["order", "--plan", str(path), "--confirm"], lambda offline: client)
            self.assertEqual(code, EXIT_OK)
            name, args = client.calls[1]
            self.assertEqual(name, "create-order")
            self.assertEqual(args["takeWayCode"], "locker-out")
            self.assertEqual(args["items"][0]["productCode"], "9900016057")
            self.assertIn("T1", text)

    def test_offline_plan_cannot_be_ordered(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.saved_plan(tmp, offline=True)
            self.assertEqual(run(["order", "--plan", str(path), "--confirm"], forbid)[0], EXIT_ERROR)

    def test_verify_and_cancel(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.json"
            path.write_text(json.dumps({"plans": [{"removed": ["酸黄瓜", "洋葱粒"]}]}, ensure_ascii=False), "utf-8")
            client = ScriptedClient({"query-order": {"data": {"items": [{"name": "汉堡包", "spec": "去酸黄瓜"}]}},
                                     "cancel-order": {"data": None}})
            code, text = run(["verify", "--order-id", "T1", "--plan", str(path)], lambda offline: client)
            self.assertEqual(code, EXIT_OK)
            self.assertIn("订单详情中出现的特制项：酸黄瓜", text)
            self.assertIn("未出现：洋葱粒", text)
            code, _ = run(["cancel", "--order-id", "T1"], lambda offline: client)
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(client.calls[-1], ("cancel-order", {"orderId": "T1", "cancelReasonCode": "1"}))


class FileErrorTest(unittest.TestCase):
    def test_missing_plan_file(self):
        self.assertEqual(run(["order", "--plan", "/nonexistent/plan.json"], forbid)[0], EXIT_USAGE)

    def test_invalid_json_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{oops", "utf-8")
            self.assertEqual(run(["order", "--plan", str(path)], forbid)[0], EXIT_USAGE)
            self.assertEqual(run(["verify", "--order-id", "T1", "--plan", str(path)], forbid)[0], EXIT_USAGE)

    def test_plan_missing_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.json"
            path.write_text(json.dumps({"plans": [{"name": "x"}]}), "utf-8")
            self.assertEqual(run(["order", "--plan", str(path)], forbid)[0], EXIT_USAGE)

    def test_unwritable_card_path(self):
        code, _ = run(["plan", "--age-months", "18", "--offline", "--card", "/nonexistent-dir/x.html"])
        self.assertEqual(code, EXIT_ERROR)


class StoresCommandTest(unittest.TestCase):
    def test_offline_stores(self):
        code, text = run(["stores", "--city", "上海市", "--keyword", "人民广场", "--offline"])
        self.assertEqual(code, EXIT_OK)
        self.assertIn("1450713", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m unittest tests.test_cli -v`
Expected: `ModuleNotFoundError: No module named 'babybite.cli'`

- [ ] **Step 3: 实现** `babybite/__main__.py`

```python
from .cli import main

raise SystemExit(main())
```

`babybite/cli.py`：

```python
"""命令行入口：python3 -m babybite <command>。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, Optional

from .age_rules import INFANT_ADVICE, band_for, parse_allergies, sodium_budget
from .cards import render_html, render_json, render_markdown
from .customize import to_order_item
from .errors import AuthError, BabyBiteError, FixtureMissingError, McdBusinessError
from .mcp_client import client_from_env
from .menu import Store, parse_meal_detail, parse_menu, parse_stores
from .nutrition import NutritionIndex, parse_nutrition_table
from .planner import PlanResult, adult_suggestions, build_plans, rank_candidates
from .scenes import get_scene, store_args

OFFLINE_WHEN = "2026-10-12 11:30"
OFFLINE_CITY, OFFLINE_KEYWORD = "上海市", "人民广场"
EXIT_OK, EXIT_USAGE, EXIT_AUTH, EXIT_BUSINESS, EXIT_ERROR = 0, 2, 3, 4, 5
CLOSED_HINT = "（门店可能不在营业时间，可用 --when \"yyyy-MM-dd HH:mm\" 预约）"
VERIFY_PRINT_LIMIT = 4000


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="babybite", description="小小麦门 · 带娃吃麦定制官（mcd-baby-bite）")
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="生成宝宝定制单")
    plan.add_argument("--age-months", type=int, required=True, help="宝宝月龄，如 18")
    plan.add_argument("--kids", type=int, default=1)
    plan.add_argument("--adults", type=int, default=1)
    plan.add_argument("--scene", choices=["pickup", "drive"], default="pickup", help="到店自提 / 得来速")
    plan.add_argument("--city")
    plan.add_argument("--keyword", help="位置关键词，如 人民广场")
    plan.add_argument("--store", help="门店编码（跳过门店搜索）")
    plan.add_argument("--be-code", help="得来速门店的 beCode")
    plan.add_argument("--when", help="预约时间 yyyy-MM-dd HH:mm")
    plan.add_argument("--allergy", help="过敏原，逗号分隔：鱼、奶、蛋、麸质")
    plan.add_argument("--keep", help="不想去掉的配料，逗号分隔，如 生菜,吉士")
    plan.add_argument("--meal-share", type=float, default=1 / 3, help="本餐占全天钠的比例，0.2-0.5")
    plan.add_argument("--json", action="store_true")
    plan.add_argument("--card", help="输出 HTML 卡片路径")
    plan.add_argument("--save", help="保存方案 JSON，供 order 使用")
    plan.add_argument("--offline", action="store_true", help="用录制的真实数据离线演示，无需 Token")

    stores = sub.add_parser("stores", help="查询附近门店")
    stores.add_argument("--city", required=True)
    stores.add_argument("--keyword", required=True)
    stores.add_argument("--scene", choices=["pickup", "drive"], default="pickup")
    stores.add_argument("--offline", action="store_true")

    order = sub.add_parser("order", help="按保存的方案算价；加 --confirm 才会下单")
    order.add_argument("--plan", required=True)
    order.add_argument("--confirm", action="store_true")
    order.add_argument("--take-way", help="取餐方式 code，默认取算价返回的第一个")

    verify = sub.add_parser("verify", help="查询订单并核验特制")
    verify.add_argument("--order-id", required=True)
    verify.add_argument("--plan", help="对照的方案 JSON")

    cancel = sub.add_parser("cancel", help="取消订单")
    cancel.add_argument("--order-id", required=True)
    cancel.add_argument("--reason", default="1", help="1=改主意了 2=重复下单 3=点错了 -1=其它")
    return parser


def _split(text: Optional[str]) -> tuple:
    return tuple(t.strip() for t in (text or "").replace("，", ",").split(",") if t.strip())


def _resolve_store(client, scene, args, when) -> Store:
    if args.store:
        if scene.needs_be_code and not args.be_code:
            raise ValueError(f"{scene.label}指定门店时需要同时提供 --be-code")
        return Store(args.store, f"门店 {args.store}", "", None, True, "-", args.be_code, bool(when), ())
    city = args.city or (OFFLINE_CITY if args.offline else None)
    keyword = args.keyword or (OFFLINE_KEYWORD if args.offline else None)
    if not city or not keyword:
        raise ValueError("请提供 --city 和 --keyword（或用 --store 指定门店）")
    stores = parse_stores(client.call_tool("query-nearby-stores", {
        "beType": scene.be_type, "searchType": 2, "city": city, "keyword": keyword}))
    if not stores:
        raise BabyBiteError(f"在 {city}{keyword} 附近没有找到支持{scene.label}的门店")
    usable = [s for s in stores if (s.reservation if when else s.open_now)]
    if not usable:
        raise BabyBiteError("附近门店当前都不在营业时间" + CLOSED_HINT)
    return usable[0]


def _attach_price(client, base: dict, result: PlanResult) -> None:
    try:
        payload = client.call_tool("calculate-price", dict(base, items=[to_order_item(result.plans[0].item)]))
    except (FixtureMissingError, McdBusinessError) as exc:
        result.notices.append(f"实时核价未完成（{exc}），以菜单价为准。")
        return
    data = payload.get("data") or {}
    price = data.get("price")
    result.price_cents = int(price) if isinstance(price, (int, float)) else None
    result.take_ways = list(data.get("takeWayList") or [])


def _emit(result: PlanResult, args, out) -> None:
    print(render_json(result) if args.json else render_markdown(result), file=out)
    if args.card:
        Path(args.card).write_text(render_html(result), encoding="utf-8")
        print(f"HTML 卡片已保存：{args.card}", file=sys.stderr)
    if args.save:
        if not result.plans:
            raise BabyBiteError("没有可保存的方案")
        Path(args.save).write_text(render_json(result), encoding="utf-8")
        print(f"方案已保存：{args.save}（下单：python3 -m babybite order --plan {args.save} --confirm）", file=sys.stderr)


def cmd_plan(args, factory, out) -> int:
    band_for(args.age_months)
    allergies = parse_allergies(args.allergy)
    if args.kids < 1 or args.adults < 0:
        raise ValueError("--kids 至少为 1，--adults 不能为负数")
    budget = sodium_budget(args.age_months, args.meal_share)
    if budget is None:
        print(INFANT_ADVICE, file=out)
        return EXIT_OK
    scene = get_scene(args.scene)
    if args.store and scene.needs_be_code and not args.be_code:
        raise ValueError(f"{scene.label}指定门店时需要同时提供 --be-code")
    client = factory(args.offline)
    when = args.when or (OFFLINE_WHEN if args.offline else None)
    store = _resolve_store(client, scene, args, when)
    base = store_args(scene, store.code, store.be_code, when)
    menu = parse_menu(client.call_tool("query-meals", base))
    index = NutritionIndex(parse_nutrition_table(client.call_tool("list-nutrition-foods", {}).get("data") or ""))
    candidates = rank_candidates(menu, args.age_months, allergies)
    notices, details = [], {}
    for item in candidates:
        try:
            details[item.code] = parse_meal_detail(client.call_tool("query-meal-detail", dict(base, code=item.code)))
        except (McdBusinessError, FixtureMissingError) as exc:
            notices.append(f"{item.name} 详情获取失败：{exc}")
    plans, excluded = build_plans(candidates, details, index, budget, args.age_months, allergies,
                                  _split(args.keep), args.kids)
    result = PlanResult(args.age_months, args.kids, args.adults, scene, store, when, budget, plans, excluded,
                        adult_suggestions(menu), offline=args.offline, notices=notices)
    if plans:
        _attach_price(client, base, result)
    _emit(result, args, out)
    return EXIT_OK


def cmd_stores(args, factory, out) -> int:
    scene = get_scene(args.scene)
    client = factory(args.offline)
    stores = parse_stores(client.call_tool("query-nearby-stores", {
        "beType": scene.be_type, "searchType": 2, "city": args.city, "keyword": args.keyword}))
    if not stores:
        print("附近没有找到门店", file=out)
    for s in stores:
        status = "营业中" if s.open_now else "未营业"
        extra = ("，可预约" if s.reservation else "") + (f"，beCode={s.be_code}" if s.be_code else "")
        distance = f"{s.distance_m}m" if s.distance_m is not None else "-"
        print(f"{s.code}  {s.name}  {distance}  {s.hours} {status}{extra}\n    {s.address}", file=out)
    return EXIT_OK


def _read_plan_file(path: str) -> dict:
    try:
        data = json.loads(Path(path).read_text("utf-8"))
    except OSError as exc:
        raise ValueError(f"无法读取方案文件 {path}：{exc.strerror or exc}") from None
    except json.JSONDecodeError:
        raise ValueError(f"方案文件 {path} 不是有效的 JSON，请用 plan --save 重新生成") from None
    if not isinstance(data, dict):
        raise ValueError(f"方案文件 {path} 格式不正确，请用 plan --save 重新生成")
    return data


def _load_plan(path: str) -> dict:
    saved = _read_plan_file(path)
    if not saved.get("plans"):
        raise BabyBiteError("方案文件里没有可下单的宝宝餐")
    if saved.get("offline"):
        raise BabyBiteError("这是离线演示方案，不能用于真实下单，请去掉 --offline 重新生成")
    store, top = saved.get("store"), saved["plans"][0]
    if not saved.get("scene") or not isinstance(store, dict) or not store.get("code") \
            or not isinstance(top, dict) or not top.get("orderItem"):
        raise ValueError("方案文件缺少 scene / store.code / plans[0].orderItem，请用 plan --save 重新生成")
    return saved


def cmd_order(args, factory, out) -> int:
    saved = _load_plan(args.plan)
    scene = get_scene(saved["scene"])
    store, top = saved["store"], saved["plans"][0]
    base = store_args(scene, store["code"], store.get("beCode"), saved.get("reservationDate"))
    items = [top["orderItem"]]
    client = factory(False)
    data = client.call_tool("calculate-price", dict(base, items=items)).get("data") or {}
    price = data.get("price")
    print(f"门店：{store['name']}；餐品：{top['name']} × {top['quantity']}", file=out)
    print(f"实时核价：¥{price / 100:.2f}" if isinstance(price, (int, float)) else "实时核价：未返回金额", file=out)
    print("线上去料：" + ("、".join(top.get("removed") or []) or "无"), file=out)
    if not args.confirm:
        print("未加 --confirm，仅算价不下单。", file=out)
        return EXIT_OK
    order_args = dict(base, items=items)
    if scene.needs_take_way:
        codes = [t.get("code") for t in data.get("takeWayList") or [] if t.get("code")]
        if args.take_way and args.take_way not in codes:
            raise ValueError(f"--take-way 需为：{'、'.join(codes)}")
        take_way = args.take_way or (codes[0] if codes else None)
        if not take_way:
            raise BabyBiteError("算价结果没有返回取餐方式，已中止下单")
        order_args["takeWayCode"] = take_way
    created = client.call_tool("create-order", order_args)
    print("已创建订单，请在支付链接或麦当劳 App 中完成支付：", file=out)
    print(json.dumps(created.get("data"), ensure_ascii=False, indent=2), file=out)
    return EXIT_OK


def cmd_verify(args, factory, out) -> int:
    saved = _read_plan_file(args.plan) if args.plan else None
    payload = factory(False).call_tool("query-order", {"orderId": args.order_id})
    text = json.dumps(payload.get("data"), ensure_ascii=False)
    print(text if len(text) <= VERIFY_PRINT_LIMIT else text[:VERIFY_PRINT_LIMIT] + "…", file=out)
    if saved is not None:
        removed = (saved.get("plans") or [{}])[0].get("removed") or []
        found = [name for name in removed if name in text]
        missing = [name for name in removed if name not in text]
        print(f"订单详情中出现的特制项：{'、'.join(found) or '无'}", file=out)
        if missing:
            print(f"订单详情中未出现：{'、'.join(missing)}（接口可能不回显特制，请以小票为准）", file=out)
    return EXIT_OK


def cmd_cancel(args, factory, out) -> int:
    factory(False).call_tool("cancel-order", {"orderId": args.order_id, "cancelReasonCode": str(args.reason)})
    print(f"订单 {args.order_id} 已提交取消。", file=out)
    return EXIT_OK


COMMANDS = {"plan": cmd_plan, "stores": cmd_stores, "order": cmd_order, "verify": cmd_verify, "cancel": cmd_cancel}


def main(argv=None, client_factory: Optional[Callable] = None, out=None) -> int:
    out = out or sys.stdout
    args = build_parser().parse_args(argv)
    factory = client_factory or (lambda offline: client_from_env(offline=offline))
    try:
        return COMMANDS[args.command](args, factory, out)
    except AuthError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return EXIT_AUTH
    except McdBusinessError as exc:
        hint = CLOSED_HINT if str(exc.code) == "600057" else ""
        print(f"错误：{exc}{hint}", file=sys.stderr)
        return EXIT_BUSINESS
    except ValueError as exc:
        print(f"参数错误：{exc}", file=sys.stderr)
        return EXIT_USAGE
    except BabyBiteError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return EXIT_ERROR
    except OSError as exc:
        print(f"错误：文件读写失败：{exc}", file=sys.stderr)
        return EXIT_ERROR
```

- [ ] **Step 4: 生成黄金输出**

Run: `mkdir -p tests/golden && python3 -m babybite plan --age-months 18 --offline --adults 2 > tests/golden/plan_18m_offline.md`

人工核对（把以下检查结果写进任务报告）：
- 主推为"汉堡开心乐园餐 × 1"，含"菜单价 ¥23.5 / 实时核价 ¥23.50"
- 表格中 汉堡包 为"线上已去：酸黄瓜、洋葱粒、番茄酱、芥末酱"、"1/4 份"、"≤123mg"；迷你薯条为"建议大人吃，宝宝最多尝 2-3 根"；纯牛奶、小杯玉米杯为"整份"
- 店员话术卡含"牛肉饼不撒盐、薯条不加盐"
- "本餐 197mg（全天上限 590mg = 食盐 1.5g × 393"
- 备选含麦乐鸡开心乐园餐（麦乐鸡-4块 1/3 份，约 1 块）与鱼排堡开心乐园餐；未推荐含"板烧鸡腿堡：即使只吃 1/4 份也会超出本餐钠预算"

- [ ] **Step 5: 运行确认通过**

Run: `python3 -m unittest discover -s tests -v`
Expected: 全部测试 OK（约 87 个）

---

### Task 10: 真实录制与冒烟脚本

**Files:**
- Create: `scripts/record_fixtures.py`, `scripts/smoke_real.py`

**Interfaces:**
- Consumes: `McdClient.call_tool_raw`、`menu`、`nutrition`、`planner`、`customize`、`scenes`
- Produces: 两个可执行脚本（需真实 Token，由控制者运行验证；单元测试不覆盖）

- [ ] **Step 1: 实现** `scripts/record_fixtures.py`

```python
"""用真实 Token 重新录制离线演示数据（只调用只读接口），写入 fixtures/real/。

用法：MCD_MCP_TOKEN=... python3 scripts/record_fixtures.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from babybite.age_rules import sodium_budget  # noqa: E402
from babybite.cli import OFFLINE_CITY, OFFLINE_KEYWORD, OFFLINE_WHEN  # noqa: E402
from babybite.customize import to_order_item  # noqa: E402
from babybite.mcp_client import client_from_env, unwrap_tool_result  # noqa: E402
from babybite.menu import parse_meal_detail, parse_menu, parse_stores  # noqa: E402
from babybite.nutrition import NutritionIndex, parse_nutrition_table  # noqa: E402
from babybite.planner import build_plans, rank_candidates  # noqa: E402
from babybite.scenes import get_scene, store_args  # noqa: E402

OUT = ROOT / "fixtures" / "real"
DEMO_AGES = (18, 30)
EXTRA_DETAIL_CODES = ("1120", "4437", "1401", "1600", "1406", "9900016055")


def sanitize(result: dict) -> dict:
    content = result.get("structuredContent")
    if isinstance(content, dict) and "traceId" in content:
        content["traceId"] = "recorded"
    for block in result.get("content") or []:
        if block.get("type") == "text":
            block["text"] = re.sub(r'"traceId":"[0-9a-f]+"', '"traceId":"recorded"', block["text"])
    return result


def save(client, tool: str, args: dict, filename: str) -> dict:
    result = sanitize(client.call_tool_raw(tool, args))
    record = {"tool": tool, "args": args, "recordedAt": OFFLINE_WHEN[:10], "result": result}
    (OUT / filename).write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"saved {filename}")
    return unwrap_tool_result(result)


def main() -> int:
    client = client_from_env(offline=False)
    scene = get_scene("pickup")
    stores_args = {"beType": 1, "searchType": 2, "city": OFFLINE_CITY, "keyword": OFFLINE_KEYWORD}
    store = parse_stores(save(client, "query-nearby-stores", stores_args,
                              "query-nearby-stores__pickup_renminguangchang.json"))[0]
    base = store_args(scene, store.code, None, OFFLINE_WHEN)
    menu = parse_menu(save(client, "query-meals", base, f"query-meals__{store.code}_lunch.json"))
    index = NutritionIndex(parse_nutrition_table(
        save(client, "list-nutrition-foods", {}, "list-nutrition-foods.json")["data"]))
    codes = {m.code for age in DEMO_AGES for m in rank_candidates(menu, age)}
    codes |= {m.code for m in rank_candidates(menu, 30, ("鱼类",))} | set(EXTRA_DETAIL_CODES)
    details = {code: parse_meal_detail(save(client, "query-meal-detail", dict(base, code=code),
                                            f"query-meal-detail__{code}.json")) for code in sorted(codes)}
    priced = set()
    for age in DEMO_AGES:
        plans, _ = build_plans(rank_candidates(menu, age), details, index, sodium_budget(age), age)
        for plan in plans:
            item = to_order_item(plan.item)
            key = json.dumps(item, sort_keys=True)
            if key in priced:
                continue
            priced.add(key)
            save(client, "calculate-price", dict(base, items=[item]),
                 f"calculate-price__{plan.item.product_code}_{age}m.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 实现** `scripts/smoke_real.py`

```python
"""真实只读冒烟：门店 → 菜单 → 营养 → 详情 → 特制算价。不下单。

用法：MCD_MCP_TOKEN=... python3 scripts/smoke_real.py [--city 上海市 --keyword 人民广场 --age-months 18]
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from babybite.age_rules import sodium_budget  # noqa: E402
from babybite.customize import to_order_item  # noqa: E402
from babybite.mcp_client import client_from_env  # noqa: E402
from babybite.menu import parse_meal_detail, parse_menu, parse_stores  # noqa: E402
from babybite.nutrition import NutritionIndex, parse_nutrition_table  # noqa: E402
from babybite.planner import build_plans, rank_candidates  # noqa: E402
from babybite.scenes import get_scene, store_args  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", default="上海市")
    parser.add_argument("--keyword", default="人民广场")
    parser.add_argument("--age-months", type=int, default=18)
    args = parser.parse_args()
    when = (dt.date.today() + dt.timedelta(days=1)).strftime("%Y-%m-%d") + " 11:30"
    client = client_from_env(offline=False)
    stores = parse_stores(client.call_tool("query-nearby-stores", {
        "beType": 1, "searchType": 2, "city": args.city, "keyword": args.keyword}))
    store = next(s for s in stores if s.reservation)
    print(f"[1/5] 门店 {store.code} {store.name}")
    base = store_args(get_scene("pickup"), store.code, None, when)
    menu = parse_menu(client.call_tool("query-meals", base))
    print(f"[2/5] 菜单 {len(menu)} 个餐品（预约 {when}）")
    index = NutritionIndex(parse_nutrition_table(client.call_tool("list-nutrition-foods", {})["data"]))
    print(f"[3/5] 营养数据 {len(index)} 条")
    candidates = rank_candidates(menu, args.age_months)
    details = {m.code: parse_meal_detail(client.call_tool("query-meal-detail", dict(base, code=m.code)))
               for m in candidates}
    plans, excluded = build_plans(candidates, details, index, sodium_budget(args.age_months), args.age_months)
    print(f"[4/5] 方案 {len(plans)} 个，未推荐 {len(excluded)} 个")
    if not plans:
        print("失败：没有生成方案", file=sys.stderr)
        return 1
    data = client.call_tool("calculate-price", dict(base, items=[to_order_item(plans[0].item)]))["data"]
    print(f"[5/5] {plans[0].item.name} 宝宝特制算价成功：¥{data['price'] / 100:.2f}，"
          f"线上去料：{'、'.join(plans[0].item.removed_all) or '无'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: 语法检查**

Run: `python3 -m py_compile scripts/record_fixtures.py scripts/smoke_real.py && python3 -m unittest discover -s tests`
Expected: 无输出错误，测试全部 OK。真实运行由控制者执行。

---

### Task 11: 麦乐送场景（地址选择 + 订单备注）

**Files:**
- Modify: `babybite/cli.py`（`build_parser`、`_resolve_store`、`cmd_plan`、`cmd_order`、`COMMANDS`）
- Test: `tests/test_cli.py`（追加 `DeliveryTest`）

**Interfaces:**
- Consumes: `scenes.get_scene("delivery")`、`cards.delivery_remark`、`PlanResult.address_id`、`plan_to_dict` 中的 `addressId` / `remark`
- Produces:
  - `plan --scene delivery --address-id ID`：用 `delivery-query-stores {beType: 2, addressId}` 选门店（取第一个 `businessStatus` 为真的门店，需含 beCode）
  - `addresses` 子命令：调用 `delivery-query-addresses`，每个地址只显示 `addressId` 与脱敏摘要
  - `order`：外送场景传 `addressId`，方案里 `remark` 非空时传 `remark`，不传 `takeWayCode`

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_cli.py`）

```python
class DeliveryTest(unittest.TestCase):
    def delivery_client(self):
        offline = OfflineClient()
        store = {"storeCode": "1450713", "storeName": "麦当劳上海黄浦华旭国际大厦餐厅", "beCode": "BE1",
                 "businessStatus": True, "address": "西藏中路336号"}

        class Client(ScriptedClient):
            def call_tool(self, name, args):
                self.calls.append((name, args))
                if name == "delivery-query-stores":
                    return {"data": [store]}
                if name == "delivery-query-addresses":
                    return {"data": {"addresses": [{"addressId": "A1", "fullAddress": "上海市黄浦区人民大道200号3楼",
                                                    "contactName": "张三", "phone": "13800001234"}]}}
                if name == "calculate-price":
                    return {"data": {"price": 2350}}
                if name == "create-order":
                    return {"data": {"orderId": "D1"}}
                return offline.call_tool(name, {k: v for k, v in args.items() if k != "beCode"})
        return Client({})

    def test_plan_delivery_uses_address_store_and_remark(self):
        client = self.delivery_client()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "d.json"
            code, text = run(["plan", "--age-months", "18", "--scene", "delivery", "--address-id", "A1",
                              "--when", "2026-10-12 11:30", "--save", str(path)], lambda offline: client)
            self.assertEqual(code, EXIT_OK)
            self.assertIn(("delivery-query-stores", {"beType": 2, "addressId": "A1"}), client.calls)
            meals_args = next(a for n, a in client.calls if n == "query-meals")
            self.assertEqual((meals_args["orderType"], meals_args["beType"], meals_args["beCode"]), (2, 2, "BE1"))
            saved = json.loads(path.read_text("utf-8"))
            self.assertEqual(saved["addressId"], "A1")
            saved["offline"] = False
            path.write_text(json.dumps(saved, ensure_ascii=False), "utf-8")
            code, _ = run(["order", "--plan", str(path), "--confirm"], lambda offline: client)
            self.assertEqual(code, EXIT_OK)
            order_args = next(a for n, a in client.calls if n == "create-order")
            self.assertEqual(order_args["addressId"], "A1")
            self.assertNotIn("takeWayCode", order_args)
            self.assertEqual(order_args.get("remark", ""), saved["remark"])

    def test_delivery_requires_address(self):
        self.assertEqual(run(["plan", "--age-months", "18", "--scene", "delivery"], forbid)[0], EXIT_USAGE)

    def test_addresses_are_masked(self):
        code, text = run(["addresses"], lambda offline: self.delivery_client())
        self.assertEqual(code, EXIT_OK)
        self.assertIn("A1", text)
        self.assertIn("上海市黄浦区***", text)
        for secret in ("13800001234", "张三", "人民大道200号"):
            self.assertNotIn(secret, text)
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m unittest tests.test_cli.DeliveryTest -v`
Expected: 失败（`--scene delivery` 不在可选值中 / 无 `addresses` 子命令）

- [ ] **Step 3: 实现**

在 `build_parser` 中：
- `plan.add_argument("--scene", choices=["pickup", "drive", "delivery"], default="pickup", help="到店自提 / 得来速 / 麦乐送")`
- 新增 `plan.add_argument("--address-id", help="外送地址 ID（见 addresses 命令）")`
- 新增子命令：`sub.add_parser("addresses", help="列出外送地址（脱敏显示）")`

在 `cli.py` 中新增：

```python
def _mask(text: str, keep: int = 2) -> str:
    text = str(text or "")
    return text[:keep] + "***" if len(text) > keep else "***"


def _resolve_delivery_store(client, scene, address_id: Optional[str]) -> Store:
    if not address_id:
        raise ValueError("麦乐送需要 --address-id，可先运行 addresses 命令查看")
    stores = parse_stores(client.call_tool("delivery-query-stores", {"beType": scene.be_type, "addressId": address_id}))
    usable = [s for s in stores if s.open_now and s.be_code]
    if not usable:
        raise BabyBiteError("该地址附近暂无可配送的营业门店" + CLOSED_HINT)
    return usable[0]


def cmd_addresses(args, factory, out) -> int:
    payload = factory(False).call_tool("delivery-query-addresses", {})
    rows = payload.get("data") or []
    if isinstance(rows, dict):
        rows = rows.get("addresses") or rows.get("list") or []
    if not rows:
        print("还没有配送地址，请先在麦当劳 App 中添加。", file=out)
    for row in rows:
        address_id = row.get("addressId") or row.get("id")
        full = row.get("fullAddress") or row.get("address") or ""  # 实测字段：addressId/contactName/fullAddress/phone
        print(f"{address_id}  {_mask(full, keep=6)}", file=out)
    return EXIT_OK
```

修改 `cmd_plan`：在 `client = factory(args.offline)` 之前加入
```python
    if scene.needs_address and not args.address_id:
        raise ValueError("麦乐送需要 --address-id，可先运行 addresses 命令查看")
```
将 `store = _resolve_store(client, scene, args, when)` 改为：
```python
    store = (_resolve_delivery_store(client, scene, args.address_id) if scene.needs_address
             else _resolve_store(client, scene, args, when))
```
构造 `PlanResult` 时追加参数 `address_id=args.address_id if scene.needs_address else None`。

修改 `cmd_order`：在 `if scene.needs_take_way:` 代码块之后加入
```python
    if scene.needs_address:
        if not saved.get("addressId"):
            raise BabyBiteError("方案缺少 addressId，无法外送下单")
        order_args["addressId"] = saved["addressId"]
        if saved.get("remark"):
            order_args["remark"] = saved["remark"]
```

`COMMANDS` 增加 `"addresses": cmd_addresses`。

`delivery-query-addresses` 实测返回 `data` 为字典，地址列表中的字段为 `addressId`、`contactName`、`fullAddress`、`phone`；只展示 `addressId` 与 `fullAddress` 的前 6 个字。

- [ ] **Step 4: 运行确认通过**

Run: `python3 -m unittest discover -s tests -v`
Expected: 全部 OK，黄金输出测试不受影响

---

### Task 12: 手机卡片（店员出示卡 + 按年龄速查卡，HTML / PNG）

**Files:**
- Create: `babybite/snapshot.py`, `babybite/phone_cards.py`, `tests/test_phone_cards.py`
- Modify: `babybite/cli.py`（`plan` 增加 `--phone-card DIR`）

**Interfaces:**
- Consumes: `cards.age_label`、`planner.build_plans/rank_candidates/KidPlan`、`age_rules.sodium_budget`、`errors.BabyBiteError`
- Produces:
  - `snapshot.BROWSER_ENV = "BABYBITE_BROWSER"`、`CARD_SIZE = (1080, 1440)`、`find_browser() -> Optional[str]`、`html_to_png(html_path, png_path, size=CARD_SIZE, browser=None, timeout=60) -> bool`
  - `phone_cards.AGE_CARD_AGES = (18, 30, 60)`、`AgeRow(age_months, band_label, daily_salt_g, meal_sodium_mg, plan)`
  - `phone_cards.card_candidate_codes(menu, ages=AGE_CARD_AGES, allergies=()) -> list[str]`
  - `phone_cards.age_rows(menu, details, index, ages=AGE_CARD_AGES, allergies=(), keep=()) -> list[AgeRow]`
  - `phone_cards.render_staff_card(item, age_months, store_name) -> str`、`render_age_card(rows, store_name, when) -> str`
  - CLI：`plan --phone-card DIR` 写出 `staff-card.html`、`age-card.html`，有浏览器时同时写出同名 `.png`

- [ ] **Step 1: 写失败测试** `tests/test_phone_cards.py`

```python
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from babybite.age_rules import sodium_budget
from babybite.errors import BabyBiteError
from babybite.customize import customize_meal
from babybite.phone_cards import age_rows, card_candidate_codes, render_age_card, render_staff_card
from babybite.snapshot import find_browser, html_to_png
from tests.helpers import load_detail, load_index, load_menu
from tests.test_cli import run

FAKE_BROWSER = """#!/usr/bin/env python3
import sys
for arg in sys.argv[1:]:
    if arg.startswith("--screenshot="):
        open(arg.split("=", 1)[1], "wb").write(b"\\x89PNG fake")
"""
HANGING_BROWSER = FAKE_BROWSER + "import time\ntime.sleep(30)\n"
FAILING_BROWSER = "#!/usr/bin/env python3\nimport sys\nsys.exit(3)\n"


def make_fake_browser(folder, script=FAKE_BROWSER, name="fake-chrome"):
    path = Path(folder) / name
    path.write_text(script, "utf-8")
    path.chmod(0o755)
    return str(path)


class StaffCardTest(unittest.TestCase):
    def test_staff_card_content(self):
        item = customize_meal(load_detail("9900016057"), 18)
        page = render_staff_card(item, 18, "麦当劳上海黄浦华旭国际大厦餐厅")
        self.assertTrue(page.startswith("<!doctype html>"))
        for part in ("给店员看", "1 岁 6 个月", "酸黄瓜、洋葱粒、番茄酱、芥末酱", "牛肉饼不撒盐", "薯条不加盐", "做不到也没关系"):
            self.assertIn(part, page)

    def test_staff_card_escapes(self):
        item = customize_meal(load_detail("9900016056"), 18)
        page = render_staff_card(item, 18, "<b>店</b>")
        self.assertNotIn("<b>店</b>", page)
        self.assertIn("按正常出餐即可", page)
        self.assertNotIn("线上已经去掉", page)
        self.assertNotIn("做不到也没关系", page)


class AgeCardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        menu = load_menu()
        details = {code: load_detail(code) for code in card_candidate_codes(menu)}
        cls.rows = age_rows(menu, details, load_index())

    def test_rows_follow_bands_and_budgets(self):
        self.assertEqual([r.band_label for r in self.rows], ["1-2 岁", "2-3 岁", "4-6 岁"])
        self.assertEqual([r.meal_sodium_mg for r in self.rows], [197, 262, 393])
        self.assertEqual(self.rows[0].plan.item.name, "汉堡开心乐园餐")
        for row in self.rows:
            self.assertIsNotNone(row.plan)
            self.assertLessEqual(row.plan.kid_sodium_mg, row.meal_sodium_mg)

    def test_age_card_content(self):
        page = render_age_card(self.rows, "麦当劳上海黄浦华旭国际大厦餐厅", "2026-10-12 11:30")
        for part in ("宝宝点餐速查卡", "1-2 岁", "2-3 岁", "4-6 岁", "每天盐 ≤1.5g", "T/CNSS 022-2023", "偶尔吃"):
            self.assertIn(part, page)

    def test_missing_plan_row(self):
        rows = list(self.rows)
        rows[2] = rows[2].__class__(60, "4-6 岁", 3.0, 393, None)
        self.assertIn("暂无合适组合", render_age_card(rows, "店", None))


class SnapshotTest(unittest.TestCase):
    def test_env_pointing_nowhere_disables_browser(self):
        with mock.patch.dict(os.environ, {"BABYBITE_BROWSER": "/nonexistent/chrome"}):
            self.assertIsNone(find_browser())
            with tempfile.TemporaryDirectory() as tmp:
                html = Path(tmp) / "a.html"
                html.write_text("<p>x</p>", "utf-8")
                self.assertFalse(html_to_png(html, Path(tmp) / "a.png"))

    def test_fake_browser_writes_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = Path(tmp) / "a.html"
            html.write_text("<p>x</p>", "utf-8")
            self.assertTrue(html_to_png(html, Path(tmp) / "a.png", browser=make_fake_browser(tmp)))
            self.assertTrue((Path(tmp) / "a.png").read_bytes().startswith(b"\x89PNG"))

    def test_browser_that_never_exits_is_stopped_after_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = Path(tmp) / "a.html"
            html.write_text("<p>x</p>", "utf-8")
            started = time.monotonic()
            ok = html_to_png(html, Path(tmp) / "a.png", browser=make_fake_browser(tmp, HANGING_BROWSER, "hang"))
            self.assertTrue(ok)
            self.assertLess(time.monotonic() - started, 10)

    def test_browser_without_png_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = Path(tmp) / "a.html"
            html.write_text("<p>x</p>", "utf-8")
            with self.assertRaises(BabyBiteError):
                html_to_png(html, Path(tmp) / "a.png", browser=make_fake_browser(tmp, FAILING_BROWSER, "fail"))

    def test_cli_phone_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"BABYBITE_BROWSER": make_fake_browser(tmp)}):
                out_dir = Path(tmp) / "cards"
                code, _ = run(["plan", "--age-months", "18", "--offline", "--phone-card", str(out_dir)])
            self.assertEqual(code, 0)
            names = sorted(p.name for p in out_dir.iterdir())
            self.assertEqual(names, ["age-card.html", "age-card.png", "staff-card.html", "staff-card.png"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m unittest tests.test_phone_cards -v`
Expected: `ModuleNotFoundError: No module named 'babybite.phone_cards'`

- [ ] **Step 3: 实现** `babybite/snapshot.py`

```python
"""用本机 Chrome / Edge / Chromium 无头模式把 HTML 卡片渲染成 PNG（可选能力，没有浏览器时跳过）。"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from .errors import BabyBiteError

BROWSER_ENV = "BABYBITE_BROWSER"
CARD_SIZE = (1080, 1440)
POLL_INTERVAL = 0.2
MAC_BROWSERS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
)
PATH_BROWSERS = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "chrome")


def find_browser() -> Optional[str]:
    """环境变量 BABYBITE_BROWSER 优先（指向不存在的路径即视为禁用）；否则按常见安装位置查找。"""
    configured = os.environ.get(BROWSER_ENV, "").strip()
    if configured:
        return configured if Path(configured).exists() else None
    for path in MAC_BROWSERS:
        if Path(path).exists():
            return path
    for name in PATH_BROWSERS:
        found = shutil.which(name)
        if found:
            return found
    return None


def _wait_for_png(proc, png_path: Path, timeout: float) -> bool:
    """部分 Chrome 版本（实测 154）截图后进程不退出：图片已写出且大小稳定即视为成功。"""
    deadline = time.monotonic() + timeout
    last_size = -1
    while time.monotonic() < deadline:
        exited = proc.poll() is not None
        size = png_path.stat().st_size if png_path.exists() else -1
        if size > 0 and (exited or size == last_size):
            return True
        if exited:
            return False
        last_size = size
        time.sleep(POLL_INTERVAL)
    return False


def html_to_png(html_path, png_path, size=CARD_SIZE, browser: Optional[str] = None, timeout: int = 60) -> bool:
    """渲染成功返回 True；找不到浏览器返回 False；浏览器执行失败或超时抛 BabyBiteError。"""
    browser = browser or find_browser()
    if not browser:
        return False
    html_path, png_path = Path(html_path).resolve(), Path(png_path).resolve()
    if png_path.exists():
        png_path.unlink()
    with tempfile.TemporaryDirectory() as profile:
        cmd = [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
               "--no-default-browser-check", f"--user-data-dir={profile}", "--force-device-scale-factor=1",
               f"--window-size={size[0]},{size[1]}", f"--screenshot={png_path}", html_path.as_uri()]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            raise BabyBiteError(f"浏览器渲染卡片失败：{exc}") from None
        try:
            ok = _wait_for_png(proc, png_path, timeout)
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
    if not ok:
        raise BabyBiteError("浏览器渲染卡片失败：未生成图片")
    return True
```

- [ ] **Step 4: 实现** `babybite/phone_cards.py`

```python
"""手机竖版卡片（1080×1440）：给店员看的话术卡、按年龄推荐搭配的速查卡。适合存相册或发小红书。"""
from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Optional

from .age_rules import sodium_budget
from .cards import age_label
from .planner import KidPlan, build_plans, rank_candidates

AGE_CARD_AGES = (18, 30, 60)  # 分别代表 1-2 岁、2-3 岁、4-6 岁

_BASE_CSS = """
*{box-sizing:border-box}html,body{margin:0;width:1080px;height:1440px;overflow:hidden}
body{background:#fff8e7;font-family:-apple-system,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;color:#2b2b2b}
.page{width:1080px;height:1440px;padding:64px 72px;display:flex;flex-direction:column}
.tag{align-self:flex-start;background:#da291c;color:#fff;border-radius:999px;padding:10px 28px;font-size:30px;font-weight:700}
h1{font-size:64px;margin:28px 0 12px;line-height:1.25}
.sub{font-size:30px;color:#7a6f5a;margin:0 0 16px}
.foot{margin-top:auto;font-size:24px;color:#7a6f5a;line-height:1.5}
"""
_STAFF_CSS = """
h1{font-size:76px}
.box{background:#fff;border-radius:36px;padding:48px 52px;margin-top:40px;box-shadow:0 4px 16px rgba(0,0,0,.06)}
.ask{background:#ffbc0d}
.label{font-size:34px;color:#7a6f5a;margin-bottom:16px}.ask .label{color:#5a4300}
.big{font-size:64px;font-weight:800;line-height:1.4;margin:0;padding:0;list-style:none}
.soft{font-size:40px;margin-top:20px;font-weight:600}
"""
_AGE_CSS = """
.row{display:flex;background:#fff;border-radius:28px;margin-top:22px;overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,.06)}
.age{width:230px;background:#da291c;color:#fff;padding:28px 24px;display:flex;flex-direction:column;justify-content:center}
.age b{font-size:44px}.age span{font-size:24px;margin-top:8px}
.info{padding:24px 30px;flex:1}.dish{font-size:38px;font-weight:800;margin-bottom:8px}
.line{font-size:27px;line-height:1.5;color:#4a4a4a}
"""
AGE_CARD_FOOT = ("菜单为门店实时数据；盐上限依据：中国营养学会《家庭减盐行为指南》T/CNSS 022-2023、《中国居民膳食指南（2022）》。"
                 "营养数据来自麦当劳 MCP 官方接口，去料后实际更低。偶尔吃，吃得明白；不构成营养建议。")


@dataclass(frozen=True)
class AgeRow:
    age_months: int
    band_label: str
    daily_salt_g: float
    meal_sodium_mg: int
    plan: Optional[KidPlan]


def card_candidate_codes(menu: list, ages: tuple = AGE_CARD_AGES, allergies: tuple = ()) -> list:
    codes = []
    for age in ages:
        for item in rank_candidates(menu, age, allergies):
            if item.code not in codes:
                codes.append(item.code)
    return codes


def age_rows(menu: list, details: dict, index, ages: tuple = AGE_CARD_AGES, allergies: tuple = (),
             keep: tuple = ()) -> list:
    rows = []
    for age in ages:
        budget = sodium_budget(age)
        plans, _ = build_plans(rank_candidates(menu, age, allergies), details, index, budget, age, allergies, keep)
        rows.append(AgeRow(age, budget.band.label, budget.band.daily_salt_g, budget.meal_sodium_mg,
                           plans[0] if plans else None))
    return rows


def _page(title: str, css: str, body: str) -> str:
    return ("<!doctype html>\n<html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
            f"<meta name=\"viewport\" content=\"width=1080\"><title>{html.escape(title)}</title>"
            f"<style>{_BASE_CSS}{css}</style></head><body><div class=\"page\">{body}</div></body></html>")


def render_staff_card(item, age_months: int, store_name: str) -> str:
    e = html.escape
    removed_box = (f'<div class="box"><div class="label">线上已经去掉</div>'
                   f'<div class="big">{e("、".join(item.removed_all))}</div></div>') if item.removed_all else ""
    if item.salt_requests:
        asks = "".join(f"<li>{e(s)}</li>" for s in item.salt_requests)
        ask_box = (f'<div class="box ask"><div class="label">如果方便，麻烦您</div><ul class="big">{asks}</ul>'
                   '<div class="soft">做不到也没关系，谢谢您！</div></div>')
    else:
        ask_box = '<div class="box ask"><div class="big">按正常出餐即可，谢谢您！</div></div>'
    body = (
        '<span class="tag">给店员看 · 宝宝餐</span>'
        f"<h1>您好，这份是给<br>{e(age_label(age_months))}宝宝吃的</h1>"
        f'<p class="sub">{e(item.name)} × {item.quantity}</p>'
        + removed_box + ask_box
        + f'<div class="foot">{e(store_name)} · 由 mcd-baby-bite 生成，非麦当劳官方</div>'
    )
    return _page("店员话术卡", _STAFF_CSS, body)


def render_age_card(rows: list, store_name: str, when: Optional[str]) -> str:
    e = html.escape
    blocks = []
    for row in rows:
        if row.plan is None:
            info = '<div class="dish">这家店暂无合适组合</div>'
        else:
            mains = "、".join(f"{c.name} {c.note}" for c in row.plan.components if c.role == "main")
            removed = "、".join(row.plan.item.removed_all) or "无需去料"
            info = (f'<div class="dish">{e(row.plan.item.name)}</div>'
                    f'<div class="line">宝宝吃：{e(mains)}</div>'
                    f'<div class="line">线上去：{e(removed)}</div>'
                    f'<div class="line">本餐宝宝钠 ≤{row.plan.kid_sodium_mg:.0f}mg / 预算 {row.meal_sodium_mg}mg</div>')
        blocks.append(f'<div class="row"><div class="age"><b>{e(row.band_label)}</b>'
                      f'<span>每天盐 ≤{row.daily_salt_g:g}g</span></div><div class="info">{info}</div></div>')
    when_text = f" · {when}" if when else ""
    body = (
        '<span class="tag">宝宝点餐速查卡</span>'
        "<h1>带娃吃麦当劳<br>按年龄这样点</h1>"
        f'<p class="sub">{e(store_name)}{e(when_text)}</p>'
        + "".join(blocks)
        + f'<div class="foot">{e(AGE_CARD_FOOT)}</div>'
    )
    return _page("宝宝点餐速查卡", _AGE_CSS, body)
```

- [ ] **Step 5: 修改** `babybite/cli.py`

在 `build_parser` 的 `plan` 参数中加入：

```python
    plan.add_argument("--phone-card", help="输出手机竖版卡片的目录（HTML；本机有 Chrome/Edge 时同时输出 PNG）")
```

新增 import：

```python
from .phone_cards import age_rows, card_candidate_codes, render_age_card, render_staff_card
from .snapshot import find_browser, html_to_png
```

新增函数：

```python
def _write_phone_cards(client, base, menu, index, details, result, out_dir, allergies, keep) -> None:
    folder = Path(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    for code in card_candidate_codes(menu, allergies=allergies):
        if code in details:
            continue
        try:
            details[code] = parse_meal_detail(client.call_tool("query-meal-detail", dict(base, code=code)))
        except (McdBusinessError, FixtureMissingError) as exc:
            result.notices.append(f"速查卡缺少餐品 {code} 的详情：{exc}")
    cards = []
    if result.plans:
        cards.append(("staff-card", render_staff_card(result.plans[0].item, result.age_months, result.store.name)))
    rows = age_rows(menu, details, index, allergies=allergies, keep=keep)
    cards.append(("age-card", render_age_card(rows, result.store.name, result.reservation_date)))
    all_png = True
    for stem, page in cards:
        html_path, png_path = folder / f"{stem}.html", folder / f"{stem}.png"
        html_path.write_text(page, encoding="utf-8")
        try:
            png_ok = html_to_png(html_path, png_path)
        except BabyBiteError as exc:
            print(f"PNG 渲染失败：{exc}", file=sys.stderr)
            png_ok = False
        all_png = all_png and png_ok
        print(f"手机卡片：{html_path}" + (f"、{png_path}" if png_ok else ""), file=sys.stderr)
    if not all_png:
        hint = ("未找到可用的 Chrome / Edge / Chromium，可用环境变量 BABYBITE_BROWSER 指定浏览器路径。"
                if find_browser() is None else "浏览器渲染失败，可直接用浏览器打开 HTML 后截图。")
        print("部分卡片只输出了 HTML：" + hint, file=sys.stderr)
```

在 `cmd_plan` 中，`if plans: _attach_price(...)` 之后、`_emit(...)` 之前加入：

```python
    if args.phone_card:
        _write_phone_cards(client, base, menu, index, details, result, args.phone_card, allergies, _split(args.keep))
```

- [ ] **Step 6: 运行确认通过**

Run: `python3 -m unittest discover -s tests -v`
Expected: 全部 OK。若 `test_rows_follow_bands_and_budgets` 中 18 月龄行不是汉堡开心乐园餐，说明与 Task 7 的排序不一致，报告给控制者，不要改期望值。

---

### Task 13: 小红书分享（笔记草稿 + 确认后经 xiaohongshu-mcp 发布）

**Files:**
- Modify: `babybite/mcp_client.py`（抽出通用 `McpHttpClient`）
- Create: `babybite/share.py`, `tests/test_share.py`
- Modify: `babybite/cli.py`（新增 `share` 子命令，`main` 增加 `xhs_factory` 参数）

**Interfaces:**
- Consumes: `cards.age_label`、`cards.BANNED_PHRASES`（测试用）、保存的方案 JSON（`plan_to_dict` 格式）
- Produces:
  - `mcp_client.McpHttpClient(endpoint, token=None, timeout=30.0, max_retries=3, sleep=time.sleep, opener=urllib.request.urlopen, secrets=(), write_tools=WRITE_TOOLS)`，方法 `call_tool_raw(name, args) -> dict`、`call_tool_text(name, args) -> str`
  - `McdClient(token, endpoint=MCD_ENDPOINT, **kwargs)` 继承 `McpHttpClient`，`call_tool` 行为不变
  - `OfflineClient.call_tool_text(name, args) -> str`
  - `share.XHS_MCP_URL`、`TITLE_MAX = 20`、`CONTENT_MAX = 1000`、`DEFAULT_TAGS`、`VISIBILITIES`、`DEFAULT_VISIBILITY = "仅自己可见"`
  - `share.build_note(saved: dict) -> dict{title, content, tags}`、`render_draft(note, images) -> str`、`publish(note, images, visibility=DEFAULT_VISIBILITY, client=None) -> str`
  - CLI：`share --plan P [--images ...] [--out draft.md] [--publish] [--confirm] [--visibility ...]`；`main(argv=None, client_factory=None, out=None, xhs_factory=None)`

- [ ] **Step 1: 写失败测试** `tests/test_share.py`

```python
import io
import json
import tempfile
import unittest
from pathlib import Path

from babybite.cards import BANNED_PHRASES
from babybite.cli import EXIT_ERROR, EXIT_OK, EXIT_USAGE, main
from babybite.mcp_client import McpHttpClient
from babybite.share import CONTENT_MAX, TITLE_MAX, build_note, render_draft
from tests.fake_mcp import INIT, NOTIFIED, FakeMcp, tool_ok


class FakeXhs:
    def __init__(self):
        self.calls = []

    def call_tool_text(self, name, args):
        self.calls.append((name, args))
        return "发布成功"


def saved_plan(tmp, offline=False):
    path = Path(tmp) / "plan.json"
    main(["plan", "--age-months", "18", "--offline", "--save", str(path)], out=io.StringIO())
    data = json.loads(path.read_text("utf-8"))
    data["offline"] = offline
    path.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    return path, data


def run_share(argv, xhs=None):
    out = io.StringIO()
    code = main(argv, out=out, xhs_factory=(lambda: xhs) if xhs else None)
    return code, out.getvalue()


class NoteTest(unittest.TestCase):
    def test_note_limits_and_tone(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, data = saved_plan(tmp)
        note = build_note(data)
        self.assertEqual(note["title"], "1岁6个月宝宝吃麦当劳这样点")
        self.assertLessEqual(len(note["title"]), TITLE_MAX)
        self.assertLessEqual(len(note["content"]), CONTENT_MAX)
        self.assertIn("汉堡开心乐园餐", note["content"])
        self.assertIn("牛肉饼不撒盐", note["content"])
        self.assertIn("偶尔吃", note["content"])
        self.assertNotIn("github", note["content"].lower())
        for phrase in BANNED_PHRASES:
            self.assertNotIn(phrase, note["content"])
        self.assertIn("宝宝外出吃饭", note["tags"])

    def test_draft_lists_images(self):
        note = {"title": "t", "content": "c", "tags": ["a"]}
        self.assertIn("/x/age-card.png", render_draft(note, ["/x/age-card.png"]))


class ShareCommandTest(unittest.TestCase):
    def test_draft_only_does_not_touch_xhs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = saved_plan(tmp)
            draft = Path(tmp) / "draft.md"
            code, text = run_share(["share", "--plan", str(path), "--out", str(draft)])
            self.assertEqual(code, EXIT_OK)
            self.assertIn("1岁6个月宝宝吃麦当劳这样点", text)
            self.assertTrue(draft.is_file())

    def test_publish_requires_confirm(self):
        xhs = FakeXhs()
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = saved_plan(tmp)
            image = Path(tmp) / "a.png"
            image.write_bytes(b"\x89PNG")
            code, text = run_share(["share", "--plan", str(path), "--images", str(image), "--publish"], xhs)
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(xhs.calls, [])
        self.assertIn("--confirm", text)

    def test_publish_with_confirm(self):
        xhs = FakeXhs()
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = saved_plan(tmp)
            image = Path(tmp) / "a.png"
            image.write_bytes(b"\x89PNG")
            code, _ = run_share(["share", "--plan", str(path), "--images", str(image), "--publish", "--confirm"], xhs)
            self.assertEqual(code, EXIT_OK)
            name, args = xhs.calls[0]
            self.assertEqual(name, "publish_content")
            self.assertEqual(args["images"], [str(image.resolve())])
            self.assertEqual(args["visibility"], "仅自己可见")

    def test_offline_plan_cannot_be_published(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = saved_plan(tmp, offline=True)
            image = Path(tmp) / "a.png"
            image.write_bytes(b"\x89PNG")
            code, _ = run_share(["share", "--plan", str(path), "--images", str(image), "--publish", "--confirm"], FakeXhs())
        self.assertEqual(code, EXIT_ERROR)

    def test_missing_image_is_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = saved_plan(tmp)
            code, _ = run_share(["share", "--plan", str(path), "--images", "/nope.png", "--publish", "--confirm"], FakeXhs())
        self.assertEqual(code, EXIT_USAGE)


class GenericClientTest(unittest.TestCase):
    def test_no_token_means_no_authorization_header(self):
        fake = FakeMcp([INIT, NOTIFIED, tool_ok({"ok": 1})])
        self.addCleanup(fake.close)
        text = McpHttpClient(fake.url, sleep=lambda s: None).call_tool_text("publish_content", {})
        self.assertIn('"ok": 1', text)
        self.assertNotIn("authorization", fake.requests[2]["headers"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m unittest tests.test_share -v`
Expected: `ImportError: cannot import name 'McpHttpClient'`

- [ ] **Step 3: 重构** `babybite/mcp_client.py`：把整个 `class McdClient` 替换为下面两个类（`OfflineClient`、`client_from_env`、`import http.client` 等保持不变），并在 `OfflineClient` 中追加 `call_tool_text`；已有的 `MaskingTest` 必须继续通过

```python
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
            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as exc:
                if attempt < attempts:
                    self._sleep(delay)
                    delay *= 2
                    continue
                raise TransportError(self._mask(f"网络错误：{exc}")) from None
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
```

`OfflineClient` 追加方法：

```python
    def call_tool_text(self, name: str, arguments: dict) -> str:
        return _result_text(self.call_tool_raw(name, arguments), name)
```

- [ ] **Step 4: 实现** `babybite/share.py`

```python
"""生成小红书笔记草稿；用户确认后通过本机 xiaohongshu-mcp 的 publish_content 发布。"""
from __future__ import annotations

import os
from pathlib import Path

from .cards import age_label
from .mcp_client import McpHttpClient

XHS_MCP_URL = "http://127.0.0.1:18060/mcp"
TITLE_MAX, CONTENT_MAX = 20, 1000
DEFAULT_TAGS = ("宝宝外出吃饭", "带娃日常", "宝宝辅食", "麦当劳", "遛娃")
VISIBILITIES = ("仅自己可见", "公开可见", "仅互关好友可见")
DEFAULT_VISIBILITY = "仅自己可见"


def build_note(saved: dict) -> dict:
    """按保存的方案生成个人经验口吻的笔记；不放外链（避免被判定引流）。"""
    top = saved["plans"][0]
    age = age_label(saved["ageMonths"]).replace(" ", "")
    mains = "、".join(f"{c['name']} {c['note']}" for c in top["components"] if c["role"] == "main")
    removed = "、".join(top.get("removed") or []) or "无"
    lines = [
        f"带{age}的宝宝去麦当劳，我是这样点的：",
        "",
        f"套餐：{top['name']}",
        f"线上已去：{removed}（点单时选特制就能去掉）",
        f"宝宝吃：{mains}",
        f"这一餐宝宝的钠大约不超过 {top['kidSodiumMg']:.0f}mg，约占这个年龄每日建议上限的 {top['dayLimitPct']}%"
        "（参考中国营养学会《家庭减盐行为指南》）。",
        "",
    ]
    if top.get("saltRequests"):
        lines += ["线上去不掉的盐，我会跟店员说一句：", f"“{top['staffScript']}”", ""]
    lines += ["小提示：", "1. 偶尔吃，回家搭配蔬果和白水", "2. 拿到先尝一口温度和咸淡", "3. 3 岁以下撕成小块，全程看护", "",
              "个人经验分享，不构成营养建议，餐品与价格以门店为准。"]
    return {
        "title": f"{age}宝宝吃麦当劳这样点"[:TITLE_MAX],
        "content": "\n".join(lines)[:CONTENT_MAX],
        "tags": list(DEFAULT_TAGS),
    }


def render_draft(note: dict, images: list) -> str:
    out = [f"# {note['title']}", "", note["content"], "", "话题：" + " ".join(f"#{t}" for t in note["tags"])]
    if images:
        out += ["", "图片："] + [f"- {p}" for p in images]
    return "\n".join(out) + "\n"


def default_client() -> McpHttpClient:
    return McpHttpClient(os.environ.get("XHS_MCP_URL", XHS_MCP_URL), write_tools=frozenset({"publish_content"}),
                         timeout=180.0)


def publish(note: dict, images: list, visibility: str = DEFAULT_VISIBILITY, client=None) -> str:
    if visibility not in VISIBILITIES:
        raise ValueError(f"可见范围需为：{'、'.join(VISIBILITIES)}")
    paths = [str(Path(p).resolve()) for p in images]
    missing = [p for p in paths if not Path(p).is_file()]
    if not paths or missing:
        raise ValueError("发布小红书至少需要 1 张已存在的图片" + (f"，找不到：{'、'.join(missing)}" if missing else ""))
    client = client or default_client()
    return client.call_tool_text("publish_content", {
        "title": note["title"], "content": note["content"], "images": paths,
        "tags": note["tags"], "visibility": visibility,
    })
```

- [ ] **Step 5: 修改** `babybite/cli.py`

新增 import：`from .share import DEFAULT_VISIBILITY, VISIBILITIES, build_note, default_client, publish, render_draft`

`build_parser` 中新增子命令：

```python
    share = sub.add_parser("share", help="生成小红书笔记草稿；加 --publish --confirm 才会发布")
    share.add_argument("--plan", required=True)
    share.add_argument("--images", nargs="*", default=[], help="卡片图片路径（PNG/JPG），可用 plan --phone-card 生成")
    share.add_argument("--out", help="草稿保存路径（Markdown）")
    share.add_argument("--publish", action="store_true")
    share.add_argument("--confirm", action="store_true")
    share.add_argument("--visibility", choices=VISIBILITIES, default=DEFAULT_VISIBILITY)
```

新增函数并登记到 `COMMANDS["share"]`：

```python
def cmd_share(args, factory, out) -> int:
    saved = _read_plan_file(args.plan)
    if not saved.get("plans"):
        raise BabyBiteError("方案文件里没有可分享的宝宝餐")
    note = build_note(saved)
    draft = render_draft(note, args.images)
    if args.out:
        Path(args.out).write_text(draft, encoding="utf-8")
        print(f"草稿已保存：{args.out}", file=sys.stderr)
    print(draft, file=out)
    if not args.publish:
        return EXIT_OK
    if saved.get("offline"):
        raise BabyBiteError("离线演示方案不能当作真实经验发布，请用真实 Token 生成方案后再分享")
    if not args.confirm:
        print(f"将以「{args.visibility}」发布到小红书。确认无误后加 --confirm 再执行。", file=out)
        return EXIT_OK
    print(publish(note, args.images, args.visibility, client=args.xhs_factory()), file=out)
    return EXIT_OK
```

`main` 改为：

```python
def main(argv=None, client_factory: Optional[Callable] = None, out=None,
         xhs_factory: Optional[Callable] = None) -> int:
    out = out or sys.stdout
    args = build_parser().parse_args(argv)
    args.xhs_factory = xhs_factory or default_client
    factory = client_factory or (lambda offline: client_from_env(offline=offline))
```

（其余 try/except 保持不变）

- [ ] **Step 6: 运行确认通过**

Run: `python3 -m unittest discover -s tests -v`
Expected: 全部 OK（含 Task 2 原有客户端测试，验证重构未破坏行为）

---

### Task 14: 高德地图联动（天气提醒 + 步行到店 + 导航链接）

**Files:**
- Create: `babybite/amap.py`, `tests/test_amap.py`
- Modify: `babybite/cli.py`（`plan` 增加 `--from`，门店选择支持按步行时间排序，`main` 增加 `amap_factory`）

**Interfaces:**
- Consumes: `McpHttpClient`、`OfflineClient.call_tool_text`、`menu.Store`
- Produces:
  - `amap.AMAP_MCP_URL`、`BAD_WEATHER`、`WALK_MAX_MIN = 20`、`AMAP_MAX_STORES = 3`
  - `StoreRoute(store_code, poi_name, walk_minutes, walk_meters)`
  - `amap_client_from_env(offline=False)`：离线返回 `OfflineClient()`；无 `AMAP_MAPS_API_KEY` 返回 `None`
  - `weather_notice(client, city, date) -> Optional[str]`、`geocode(client, address, city) -> Optional[str]`
  - `store_location(client, store_name, city) -> Optional[tuple[str, str]]`、`walking(client, origin, destination) -> tuple[Optional[int], Optional[int]]`
  - `navi_url(client, location) -> Optional[str]`、`route_for_store(client, store, origin, city) -> StoreRoute`
  - CLI：`plan --from 地点`；只有提供 `--from` 时才调用高德（保证黄金输出稳定）

真实数据形态（fixtures 已录制）：所有高德工具结果为 `content[0].text` 中的 JSON 字符串，`maps_schema_navi` 为纯文本 `amapuri://navi?...`。`maps_text_search` 的 POI 不含坐标，需再调 `maps_search_detail(id)` 取 `location`；门店地址直接 `maps_geo` 只能解析到道路级，误差可达 1 公里，**不要用地址解析门店坐标**。

- [ ] **Step 1: 写失败测试** `tests/test_amap.py`

```python
import os
import unittest
from unittest import mock

from babybite.amap import (amap_client_from_env, geocode, navi_url, store_location, walking,
                           weather_notice)
from babybite.mcp_client import McpHttpClient, OfflineClient
from tests.test_cli import run


class TextClient:
    def __init__(self, text):
        self.text = text

    def call_tool_text(self, name, args):
        return self.text


class AmapTest(unittest.TestCase):
    def setUp(self):
        self.client = OfflineClient()

    def test_weather(self):
        text = weather_notice(self.client, "上海市", "2026-10-12")
        self.assertEqual(text, "高德天气：2026-10-12 白天阴，26℃。")

    def test_bad_weather_suggests_drive_or_delivery(self):
        client = TextClient('{"forecasts":[{"date":"2026-10-20","dayweather":"小雨","daytemp":"18"}]}')
        self.assertIn("得来速或麦乐送", weather_notice(client, "上海市", "2026-10-20"))

    def test_store_location_uses_poi_detail(self):
        self.assertEqual(geocode(self.client, "人民广场", "上海市"), "121.477401,31.240093")
        self.assertEqual(store_location(self.client, "麦当劳上海黄浦华旭国际大厦餐厅", "上海市"),
                         ("麦当劳(华旭国际大厦店)", "121.475509,31.233694"))

    def test_walking_rounds_up_minutes(self):
        self.assertEqual(walking(self.client, "121.477401,31.240093", "121.475509,31.233694"), (13, 938))

    def test_navi_url(self):
        self.assertTrue(navi_url(self.client, "121.475509,31.233694").startswith("amapuri://navi?"))

    def test_empty_results(self):
        self.assertIsNone(geocode(TextClient('{"results":[]}'), "火星", "上海市"))
        self.assertIsNone(store_location(TextClient('{"pois":[]}'), "x", "上海市"))
        self.assertEqual(walking(TextClient('{"route":{"paths":[]}}'), "a", "b"), (None, None))

    def test_client_from_env(self):
        with mock.patch.dict(os.environ, {"AMAP_MAPS_API_KEY": ""}):
            self.assertIsNone(amap_client_from_env())
        with mock.patch.dict(os.environ, {"AMAP_MAPS_API_KEY": "k" * 32}):
            client = amap_client_from_env()
        self.assertIsInstance(client, McpHttpClient)
        self.assertEqual(client._mask("url?key=" + "k" * 32), "url?key=***")
        self.assertIsInstance(amap_client_from_env(offline=True), OfflineClient)


class AmapCliTest(unittest.TestCase):
    def test_offline_plan_with_from(self):
        code, text = run(["plan", "--age-months", "18", "--offline", "--from", "人民广场"])
        self.assertEqual(code, 0)
        self.assertIn("高德天气：2026-10-12 白天阴，26℃。", text)
        self.assertIn("高德步行：从「人民广场」到 麦当劳(华旭国际大厦店) 约 13 分钟（938 米）。", text)
        self.assertIn("高德导航：amapuri://navi?", text)

    def test_missing_key_degrades(self):
        import io
        from babybite.cli import main
        store = {"storeCode": "1450713", "storeName": "店", "businessStatus": True}
        offline = OfflineClient()

        class Client:
            def call_tool(self, name, args):
                if name == "query-nearby-stores":
                    return {"data": [store]}
                return offline.call_tool(name, args)  # 参数不完全匹配时按工具名回退到录制数据

        out = io.StringIO()
        code = main(["plan", "--age-months", "18", "--city", "上海市", "--keyword", "人民广场", "--from", "家"],
                    client_factory=lambda flag: Client(), out=out, amap_factory=lambda flag: None)
        self.assertEqual(code, 0)
        self.assertIn("未配置 AMAP_MAPS_API_KEY", out.getvalue())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m unittest tests.test_amap -v`
Expected: `ModuleNotFoundError: No module named 'babybite.amap'`

- [ ] **Step 3: 实现** `babybite/amap.py`

```python
"""高德地图 MCP 联动：天气提醒、步行到店时间、导航唤端链接（可选，需 AMAP_MAPS_API_KEY）。"""
from __future__ import annotations

import json
import math
import os
import urllib.parse
from dataclasses import dataclass
from typing import Optional

from .errors import BabyBiteError
from .mcp_client import McpHttpClient, OfflineClient

AMAP_MCP_URL = "https://mcp.amap.com/mcp"
BAD_WEATHER = ("雨", "雪", "雷", "暴", "冰雹", "沙尘")
WALK_MAX_MIN = 20
AMAP_MAX_STORES = 3


@dataclass(frozen=True)
class StoreRoute:
    store_code: str
    poi_name: str
    walk_minutes: Optional[int]
    walk_meters: Optional[int]
    location: Optional[str] = None


def amap_client_from_env(offline: bool = False):
    if offline:
        return OfflineClient()
    key = os.environ.get("AMAP_MAPS_API_KEY", "").strip()
    if not key:
        return None
    return McpHttpClient(f"{AMAP_MCP_URL}?key={urllib.parse.quote(key)}", secrets=(key,), write_tools=frozenset())


def _json(client, name: str, args: dict) -> dict:
    text = client.call_tool_text(name, args)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise BabyBiteError(f"高德 {name} 返回无法解析：{text[:100]}") from None
    return data if isinstance(data, dict) else {}


def weather_notice(client, city: str, date: Optional[str]) -> Optional[str]:
    forecasts = _json(client, "maps_weather", {"city": city}).get("forecasts") or []
    day = next((f for f in forecasts if date and f.get("date") == date), forecasts[0] if forecasts else None)
    if not day:
        return None
    weather = day.get("dayweather", "")
    text = f"高德天气：{day.get('date')} 白天{weather}，{day.get('daytemp')}℃。"
    if any(word in weather for word in BAD_WEATHER):
        text += "带娃出门不便，可以考虑得来速或麦乐送。"
    return text


def geocode(client, address: str, city: str) -> Optional[str]:
    results = _json(client, "maps_geo", {"address": address, "city": city}).get("results") or []
    return results[0].get("location") if results else None


def store_location(client, store_name: str, city: str):
    """按门店名称搜 POI 再取详情坐标；比用门店地址做地理编码准确得多。"""
    pois = _json(client, "maps_text_search", {"keywords": store_name, "city": city, "citylimit": True}).get("pois") or []
    pois = [p for p in pois if "麦当劳" in p.get("name", "")]
    if not pois:
        return None
    detail = _json(client, "maps_search_detail", {"id": pois[0]["id"]})
    location = detail.get("location")
    return (detail.get("name") or pois[0]["name"], location) if location else None


def walking(client, origin: str, destination: str):
    paths = (_json(client, "maps_direction_walking", {"origin": origin, "destination": destination})
             .get("route") or {}).get("paths") or []
    if not paths:
        return None, None
    return max(1, math.ceil(int(paths[0]["duration"]) / 60)), int(paths[0]["distance"])


def navi_url(client, location: str) -> Optional[str]:
    lon, lat = location.split(",")
    text = client.call_tool_text("maps_schema_navi", {"lon": lon, "lat": lat}).strip()
    return text if text.startswith(("amapuri://", "http")) else None


def route_for_store(client, store, origin: str, city: str) -> StoreRoute:
    found = store_location(client, store.name, city)
    if not found:
        return StoreRoute(store.code, store.name, None, None)
    poi_name, location = found
    minutes, meters = walking(client, origin, location)
    return StoreRoute(store.code, poi_name, minutes, meters, location)
```

- [ ] **Step 4: 修改** `babybite/cli.py`

新增 import：

```python
import datetime as dt

from .amap import (AMAP_MAX_STORES, WALK_MAX_MIN, amap_client_from_env, geocode, navi_url,
                   route_for_store, weather_notice)
```

`plan` 参数新增：

```python
    plan.add_argument("--from", dest="origin",
                      help="出发地点，用高德计算步行到店时间并给出天气提醒（需 AMAP_MAPS_API_KEY）")
```

把 `_resolve_store` 改名并改为返回可用门店列表：

```python
def _usable_stores(client, scene, args, when) -> list:
    if args.store:
        if scene.needs_be_code and not args.be_code:
            raise ValueError(f"{scene.label}指定门店时需要同时提供 --be-code")
        return [Store(args.store, f"门店 {args.store}", "", None, True, "-", args.be_code, bool(when), ())]
    city = args.city or (OFFLINE_CITY if args.offline else None)
    keyword = args.keyword or (OFFLINE_KEYWORD if args.offline else None)
    if not city or not keyword:
        raise ValueError("请提供 --city 和 --keyword（或用 --store 指定门店）")
    stores = parse_stores(client.call_tool("query-nearby-stores", {
        "beType": scene.be_type, "searchType": 2, "city": city, "keyword": keyword}))
    if not stores:
        raise BabyBiteError(f"在 {city}{keyword} 附近没有找到支持{scene.label}的门店")
    usable = [s for s in stores if (s.reservation if when else s.open_now)]
    if not usable:
        raise BabyBiteError("附近门店当前都不在营业时间" + CLOSED_HINT)
    return usable
```

新增函数：

```python
def _pick_store_with_amap(stores, args, when, notices):
    client = args.amap_factory(args.offline)
    if client is None:
        notices.append("未配置 AMAP_MAPS_API_KEY，已跳过高德步行与天气提醒。")
        return stores[0]
    city = args.city or OFFLINE_CITY
    try:
        weather = weather_notice(client, city, (when or dt.date.today().isoformat())[:10])
        if weather:
            notices.append(weather)
        origin = geocode(client, args.origin, city)
        if not origin:
            notices.append(f"高德没有找到出发地点「{args.origin}」，已按麦当劳门店距离选择。")
            return stores[0]
        routes = [(s, route_for_store(client, s, origin, city)) for s in stores[:AMAP_MAX_STORES]]
        store, route = sorted(routes, key=lambda x: (x[1].walk_minutes is None, x[1].walk_minutes or 0))[0]
        if route.walk_minutes is not None:
            text = f"高德步行：从「{args.origin}」到 {route.poi_name} 约 {route.walk_minutes} 分钟（{route.walk_meters} 米）。"
            if route.walk_minutes > WALK_MAX_MIN:
                text += "步行较远，带娃可以考虑得来速或麦乐送。"
            notices.append(text)
        if route.location:
            link = navi_url(client, route.location)
            if link:
                notices.append(f"高德导航：{link}")
        return store
    except BabyBiteError as exc:
        notices.append(f"高德服务暂不可用（{exc}），已按麦当劳门店距离选择。")
        return stores[0]
```

`cmd_plan` 中：
- 把 `notices, details = [], {}` 拆开，`notices = []` 移到 `client = factory(args.offline)` 之后
- 门店选择改为（若 Task 11 已加入外送分支则保留外送分支）：

```python
    if scene.needs_address:
        store = _resolve_delivery_store(client, scene, args.address_id)
    else:
        stores = _usable_stores(client, scene, args, when)
        store = _pick_store_with_amap(stores, args, when, notices) if args.origin else stores[0]
    details = {}
```

`main` 中在 `args.xhs_factory = ...` 后增加参数与赋值：签名加 `amap_factory: Optional[Callable] = None`，并 `args.amap_factory = amap_factory or amap_client_from_env`。

- [ ] **Step 5: 运行确认通过**

Run: `python3 -m unittest discover -s tests -v`
Expected: 全部 OK；黄金输出不变（未使用 `--from`）

---

### Task 15（控制者执行）：参赛必备文档、Skill 定义与合规测试

**Files:**
- Create: `SKILL.md`, `README.md`, `MCP_INTEGRATION.md`, `CONTEST_DECLARATION.md`, `mcp-config.example.json`, `LICENSE`, `.gitignore`, `examples/`, `tests/test_compliance.py`

- [ ] **Step 1: 合规测试** `tests/test_compliance.py`

```python
import hashlib
import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DECLARATION_SHA256 = "cd28101bcb29cc8fb24b372fe91ce6b42c4a1487a54e01f7ade0c8c6a84241b7"
REQUIRED = ("README.md", "CONTEST_DECLARATION.md", "MCP_INTEGRATION.md", "mcp-config.example.json", "SKILL.md", "LICENSE")
TOKEN_LIKE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9]{32}(?![A-Za-z0-9])")


def repo_files():
    listed = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                            capture_output=True, text=True, check=True).stdout.split()
    return [ROOT / p for p in listed if (ROOT / p).is_file()]


class ComplianceTest(unittest.TestCase):
    def test_required_files(self):
        for name in REQUIRED:
            with self.subTest(name=name):
                self.assertTrue((ROOT / name).is_file())

    def test_declaration_is_verbatim(self):
        digest = hashlib.sha256((ROOT / "CONTEST_DECLARATION.md").read_bytes()).hexdigest()
        self.assertEqual(digest, DECLARATION_SHA256)

    def test_mcp_config_only_env_placeholders(self):
        config = json.loads((ROOT / "mcp-config.example.json").read_text("utf-8"))
        auth = config["mcpServers"]["mcd-mcp"]["headers"]["Authorization"]
        self.assertEqual(auth, "Bearer ${MCD_MCP_TOKEN}")

    def test_no_token_like_strings(self):
        for path in repo_files():
            if path.suffix in {".png", ".jpg", ".gif"}:
                continue
            text = path.read_text("utf-8", errors="ignore")
            with self.subTest(path=str(path.relative_to(ROOT))):
                self.assertIsNone(TOKEN_LIKE.search(text))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 文档内容要求**（README 与 MCP_INTEGRATION 用真实运行输出填充）
  - `CONTEST_DECLARATION.md`：从官方仓库 `M-China/mcd-developer-innovation-challenge` 逐字拷贝
  - `mcp-config.example.json`：`{"mcpServers": {"mcd-mcp": {"type": "streamablehttp", "url": "https://mcp.mcd.cn", "headers": {"Authorization": "Bearer ${MCD_MCP_TOKEN}"}}}}`
  - `SKILL.md`：frontmatter（`name: mcd-baby-bite`，`description` 写清触发场景：带娃、宝宝、儿童、幼儿吃麦当劳 / 宝宝餐 / 去盐 / 去酱），正文写工作流（优先运行 CLI；无法运行时按 design.md 第 3、4 节规则直接调用 MCP 工具）、下单红线、诚实边界
  - `README.md`：痛点（引小红书原话"系统没有去盐选项"）、效果截图（手机卡片 PNG）/ 真实输出、三步上手（申请 Token → 配置 → 运行；无 Token 用 `--offline`）、命令说明（plan / stores / order / verify / cancel / addresses / share，`--phone-card`、`--from`）、多 MCP 联动说明（麦当劳 + 高德 + 小红书）、目标用户、实现亮点（特制 key 规则、份量算法、钠预算出处）、诚实边界、致谢与声明
  - `MCP_INTEGRATION.md`：使用的 Server 与 9 个 Tool、调用时序图（文本）、参数规则、真实请求 / 响应示例（脱敏）、业务价值、已知限制
  - `LICENSE`：MIT，版权人 `JimWen`
  - `.gitignore`：`__pycache__/`、`*.pyc`、`.DS_Store`、`plan*.json`、`*.html`（`docs/index.html` 除外，用 `!docs/index.html`）

- [ ] **Step 3: 运行全部测试**

Run: `python3 -m unittest discover -s tests -v`
Expected: 全部 OK

---

### Task 16（控制者执行）：真实验收与演示页

- [ ] 运行 `python3 scripts/smoke_real.py`，记录输出到 `examples/smoke-real.txt`（无个人信息）
- [ ] 征得用户同意后执行真实闭环：`plan --save` → `order --confirm` → `verify --plan` → `cancel`；根据 `query-order` 的真实返回校准 `cmd_verify` 的比对逻辑（如特制以独立字段返回则改为字段级比对），结果写入 `MCP_INTEGRATION.md`（订单号打码）
- [ ] 用真实 Token 运行 `scripts/record_fixtures.py` 刷新 fixtures，重新生成黄金输出并人工复核
- [ ] 用真实 Key 运行 `plan --from` 验证高德联动；运行 `plan --phone-card` 生成真实 PNG 并目视检查版式
- [ ] 征得用户同意后，用 `share --publish --confirm --visibility 仅自己可见` 真实发布一次并核对，再按用户意愿决定是否公开
- [ ] 生成 `docs/index.html`（GitHub Pages 演示页：项目介绍 + 离线真实数据生成的定制卡 + 使用方法）
- [ ] 全量测试、合规测试通过；`git status` 中无 Token、无个人信息
