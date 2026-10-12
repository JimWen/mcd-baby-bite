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


if __name__ == "__main__":
    unittest.main()
