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
