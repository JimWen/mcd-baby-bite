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
