import http.client
import io
import json
import os
import unittest
import urllib.error
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


class MaskingTest(unittest.TestCase):
    def make(self, responses, sleep=None):
        responses = iter([INIT, NOTIFIED, *responses])
        self.http_errors = []
        self.sleeps = []

        def opener(request, timeout):
            status, content_type, body, extra = next(responses)
            response = body if isinstance(body, io.BytesIO) else io.BytesIO(body.encode("utf-8"))
            response.headers = {"Content-Type": content_type, **extra}
            self.addCleanup(response.close)
            if status >= 400:
                error = urllib.error.HTTPError(request.full_url, status, "error", response.headers, response)
                self.http_errors.append(error)
                self.addCleanup(error.close)
                raise error
            return response

        return McdClient(TOKEN, opener=opener, sleep=sleep if sleep is not None else self.sleeps.append)

    def test_unparsable_tool_text_masks_token(self):
        for is_error in (False, True):
            with self.subTest(is_error=is_error):
                result = {"content": [{"type": "text", "text": f"invalid tool result: {TOKEN}"}],
                          "isError": is_error}
                client = self.make([(200, "application/json", rpc(result), {})])
                with self.assertRaises(BabyBiteError) as ctx:
                    client.call_tool("query-meals", {})
                self.assertNotIn(TOKEN, str(ctx.exception))
                self.assertIn("***", str(ctx.exception))

    def test_business_error_message_masks_token(self):
        payload = {"success": False, "code": 600057, "message": f"rejected token: {TOKEN}"}
        results = [
            {"structuredContent": payload},
            {"content": [{"type": "text", "text": json.dumps(payload)}]},
        ]
        for result in results:
            with self.subTest(source=next(iter(result))):
                client = self.make([(200, "application/json", rpc(result), {})])
                with self.assertRaises(McdBusinessError) as ctx:
                    client.call_tool("query-meals", {})
                self.assertEqual(ctx.exception.code, 600057)
                self.assertNotIn(TOKEN, str(ctx.exception))
                self.assertIn("***", str(ctx.exception))

    def test_http_error_masks_token_before_truncation(self):
        client = self.make([(500, "text/plain", "x" * 190 + TOKEN + " tail", {})])
        with self.assertRaises(TransportError) as ctx:
            client.call_tool("query-meals", {})
        message = str(ctx.exception)
        for length in range(8, len(TOKEN) + 1):
            with self.subTest(prefix_length=length):
                self.assertNotIn(TOKEN[:length], message)
        self.assertIn("***", message)

    def test_json_rpc_error_message_masks_token(self):
        body = json.dumps({"jsonrpc": "2.0", "id": 2,
                           "error": {"code": -32603, "message": f"RPC rejected token: {TOKEN}"}})
        client = self.make([(200, "application/json", body, {})])
        with self.assertRaises(BabyBiteError) as ctx:
            client.call_tool_raw("query-meals", {})
        self.assertNotIn(TOKEN, str(ctx.exception))
        self.assertIn("***", str(ctx.exception))

    def test_unparsable_http_body_masks_token(self):
        for raw in (f"invalid JSON: {TOKEN}", json.dumps([TOKEN])):
            for content_type in ("application/json", "text/event-stream"):
                with self.subTest(raw=raw, content_type=content_type):
                    body = f"event: message\ndata: {raw}\n\n" if content_type == "text/event-stream" else raw
                    client = self.make([(200, content_type, body, {})])
                    with self.assertRaises(BabyBiteError) as ctx:
                        client.call_tool("query-meals", {})
                    self.assertNotIn(TOKEN, str(ctx.exception))
                    self.assertIn("***", str(ctx.exception))

    def test_http_errors_are_closed_before_raising(self):
        cases = [
            (401, "query-meals", 1, AuthError),
            (429, "query-meals", 3, RateLimitError),
            (429, "create-order", 1, RateLimitError),
            (500, "query-meals", 1, TransportError),
        ]
        for status, tool, attempts, error_type in cases:
            with self.subTest(status=status, tool=tool):
                client = self.make([(status, "text/plain", "server error", {})] * attempts)
                with self.assertRaises(error_type):
                    client.call_tool(tool, {})
                self.assertEqual(len(self.http_errors), attempts)
                for error in self.http_errors:
                    self.assertTrue(error.fp.closed)

    def test_429_response_is_closed_before_retry_sleep(self):
        def sleep(delay):
            self.assertTrue(self.http_errors[-1].fp.closed)
            self.sleeps.append(delay)

        busy = (429, "text/plain", "retry later", {})
        client = self.make([busy, busy, tool_ok(OK)], sleep=sleep)
        self.assertEqual(client.call_tool("query-meals", {})["data"], "x")
        self.assertEqual(self.sleeps, [1.0, 2.0])
        self.assertEqual(len(self.http_errors), 2)

    def test_unreadable_http_errors_are_closed_and_keep_status_handling(self):
        class UnreadableBody(io.BytesIO):
            def read(self):
                raise read_error

        cases = [
            (401, "query-meals", 1, AuthError),
            (429, "query-meals", 3, RateLimitError),
            (429, "create-order", 1, RateLimitError),
            (500, "query-meals", 1, TransportError),
        ]
        read_errors = [TimeoutError(f"read timed out: {TOKEN}"), http.client.IncompleteRead(TOKEN.encode(), 100)]
        for read_error in read_errors:
            for status, tool, attempts, error_type in cases:
                with self.subTest(read_error=type(read_error).__name__, status=status, tool=tool):
                    responses = [(status, "text/plain", UnreadableBody(), {}) for _ in range(attempts)]
                    client = self.make(responses)
                    with self.assertRaises((BabyBiteError, OSError, http.client.HTTPException)) as ctx:
                        client.call_tool(tool, {})
                    for error in self.http_errors:
                        self.assertTrue(error.fp.closed)
                    self.assertIsInstance(ctx.exception, error_type)
                    self.assertNotIn(TOKEN, str(ctx.exception))
                    self.assertEqual(len(self.http_errors), attempts)
                    self.assertEqual(self.sleeps, [1.0, 2.0] if attempts == 3 else [])

    def test_unreadable_429_response_is_closed_before_successful_retry(self):
        class UnreadableBody(io.BytesIO):
            def read(self):
                raise TimeoutError("error body timed out")

        def sleep(delay):
            self.assertTrue(self.http_errors[-1].fp.closed)
            self.sleeps.append(delay)

        client = self.make([(429, "text/plain", UnreadableBody(), {}), tool_ok(OK)], sleep=sleep)
        try:
            payload = client.call_tool("query-meals", {})
        except TimeoutError:
            self.fail("An unreadable HTTP 429 response must still be retried")
        self.assertEqual(payload["data"], "x")
        self.assertEqual(self.sleeps, [1.0])
        self.assertEqual(len(self.http_errors), 1)


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
