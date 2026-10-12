import io
import json
import unittest

from babybite.amap import PlaySpot, Throttled, nearby_play
from babybite.cli import main
from babybite.errors import BabyBiteError
from babybite.mcp_client import OfflineClient
from tests.test_cli import run

AROUND = {
    "儿童乐园": {"pois": [
        {"id": "P1", "name": "百慕大冒险", "typecode": "080501", "address": "西藏中路1号"},
        {"id": "P2", "name": "人民公园-南极石", "typecode": "110000", "address": "南京西路"},
        {"id": "P4", "name": "某某餐厅", "typecode": "050000", "address": "x"},
    ]},
    "公园": {"pois": [
        {"id": "P3", "name": "人民公园", "typecode": "110101", "address": "南京西路231号"},
        {"id": "P1", "name": "百慕大冒险", "typecode": "080501", "address": "西藏中路1号"},
    ]},
}
DETAIL = {
    "P1": {"id": "P1", "name": "百慕大冒险", "location": "121.1,31.1"},
    "P3": {"id": "P3", "name": "人民公园", "location": "121.2,31.2"},
    "S1": {"id": "S1", "name": "麦当劳(测试店)", "location": "121.0,31.0"},
}
WALK = {
    "121.1,31.1": {"route": {"paths": [{"distance": 1000, "duration": 900}]}},
    "121.2,31.2": {"route": {"paths": [{"distance": 400, "duration": 241}]}},
}


class ScriptedAmap:
    def __init__(self):
        self.calls = []

    def call_tool_text(self, name, args):
        self.calls.append((name, args))
        if name == "maps_around_search":
            return json.dumps(AROUND[args["keywords"]], ensure_ascii=False)
        if name == "maps_search_detail":
            return json.dumps(DETAIL[args["id"]], ensure_ascii=False)
        if name == "maps_direction_walking":
            return json.dumps(WALK[args["destination"]])
        if name == "maps_text_search":
            return json.dumps({"pois": [{"id": "S1", "name": "麦当劳(测试店)"}]}, ensure_ascii=False)
        if name == "maps_weather":
            return json.dumps({"forecasts": []})
        raise AssertionError(f"unexpected tool {name}")


class NearbyPlayTest(unittest.TestCase):
    def test_sorted_by_walk_and_filtered(self):
        client = ScriptedAmap()
        spots = nearby_play(client, "121.0,31.0")
        self.assertEqual(spots, [PlaySpot("人民公园", "公园", 5, 400, "南京西路231号"),
                                 PlaySpot("百慕大冒险", "游乐场", 15, 1000, "西藏中路1号")])
        around = [a for n, a in client.calls if n == "maps_around_search"]
        self.assertEqual([a["keywords"] for a in around], ["儿童乐园", "公园"])
        self.assertEqual((around[0]["radius"], around[0]["location"]), ("2000", "121.0,31.0"))
        self.assertEqual([a["id"] for n, a in client.calls if n == "maps_search_detail"], ["P1", "P3"])

    def test_interleaves_keywords_dedupes_brands_and_keeps_a_park(self):
        around = {
            "儿童乐园": {"pois": [
                {"id": "A1", "name": "百慕大冒险(人广来福士店)", "typecode": "080501", "address": "a1"},
                {"id": "A2", "name": "百慕大冒险", "typecode": "080501", "address": "a2"},
                {"id": "A3", "name": "妙趣幻想", "typecode": "080501", "address": "a3"},
                {"id": "A4", "name": "东方童话", "typecode": "080501", "address": "a4"},
            ]},
            "公园": {"pois": [{"id": "B1", "name": "人民公园", "typecode": "110101", "address": "b1"}]},
        }
        locations = {"A1": "1,1", "A3": "3,3", "A4": "5,5", "B1": "4,4"}
        seconds = {"1,1": 386, "3,3": 525, "5,5": 100, "4,4": 900}
        calls = []

        class Client:
            def call_tool_text(self, name, args):
                calls.append((name, args))
                if name == "maps_around_search":
                    return json.dumps(around[args["keywords"]], ensure_ascii=False)
                if name == "maps_search_detail":
                    return json.dumps({"location": locations[args["id"]]})
                value = seconds[args["destination"]]
                return json.dumps({"route": {"paths": [{"distance": value, "duration": value}]}})

        spots = nearby_play(Client(), "0,0")
        self.assertEqual([a["id"] for n, a in calls if n == "maps_search_detail"], ["A1", "B1", "A3", "A4"])
        self.assertEqual([(s.name, s.kind, s.walk_minutes) for s in spots],
                         [("东方童话", "游乐场", 2), ("百慕大冒险(人广来福士店)", "游乐场", 7), ("人民公园", "公园", 15)])

    def test_empty(self):
        class Empty:
            def call_tool_text(self, name, args):
                return json.dumps({"pois": []})

        self.assertEqual(nearby_play(Empty(), "0,0"), [])


class ThrottleTest(unittest.TestCase):
    def test_retries_on_qps_limit_and_keeps_interval(self):
        sleeps = []

        class Flaky:
            calls = 0

            def call_tool_text(self, name, args):
                Flaky.calls += 1
                if Flaky.calls == 1:
                    raise BabyBiteError("maps_weather 调用失败：API 调用失败：CUQPS_HAS_EXCEEDED_THE_LIMIT")
                return "{}"

        throttled = Throttled(Flaky(), interval=0.35, sleep=sleeps.append, clock=lambda: 100.0)
        self.assertEqual(throttled.call_tool_text("maps_weather", {}), "{}")
        self.assertEqual(throttled.call_tool_text("maps_weather", {}), "{}")
        self.assertIn(1.0, sleeps)
        self.assertIn(0.35, sleeps)

    def test_other_errors_propagate_without_retry(self):
        class Broken:
            calls = 0

            def call_tool_text(self, name, args):
                Broken.calls += 1
                raise BabyBiteError("maps_weather 调用失败：INVALID_USER_KEY")

        with self.assertRaises(BabyBiteError):
            Throttled(Broken(), sleep=lambda s: None, clock=lambda: 0.0).call_tool_text("maps_weather", {})
        self.assertEqual(Broken.calls, 1)

    def test_gives_up_after_retries(self):
        class AlwaysBusy:
            calls = 0

            def call_tool_text(self, name, args):
                AlwaysBusy.calls += 1
                raise BabyBiteError("CUQPS_HAS_EXCEEDED_THE_LIMIT")

        with self.assertRaises(BabyBiteError):
            Throttled(AlwaysBusy(), sleep=lambda s: None, clock=lambda: 0.0).call_tool_text("x", {})
        self.assertEqual(AlwaysBusy.calls, 3)


class PlayCliTest(unittest.TestCase):
    def online_client(self):
        offline = OfflineClient()
        store = {"storeCode": "1450713", "storeName": "麦当劳(测试店)", "businessStatus": True, "reservation": True}

        class Client:
            def call_tool(self, name, args):
                if name == "query-nearby-stores":
                    return {"data": [store]}
                return offline.call_tool(name, args)

        return Client()

    def plan(self, amap):
        out = io.StringIO()
        code = main(["plan", "--age-months", "18", "--city", "上海市", "--keyword", "人民广场", "--play"],
                    client_factory=lambda flag: self.online_client(), out=out, amap_factory=lambda flag: amap)
        return code, out.getvalue()

    def test_play_section(self):
        code, text = self.plan(ScriptedAmap())
        self.assertEqual(code, 0)
        self.assertIn("## 饭后遛娃（高德，门店周边 2 公里）", text)
        self.assertIn("- 人民公园（公园）：步行约 5 分钟（400 米）", text)
        self.assertIn("- 百慕大冒险（游乐场）：步行约 15 分钟（1000 米）", text)

    def test_play_without_key(self):
        code, text = self.plan(None)
        self.assertEqual(code, 0)
        self.assertIn("未配置 AMAP_MAPS_API_KEY，已跳过饭后遛娃推荐。", text)

    def test_play_offline_notice(self):
        code, text = run(["plan", "--age-months", "18", "--offline", "--play"])
        self.assertEqual(code, 0)
        self.assertIn("离线演示不包含饭后遛娃推荐", text)


if __name__ == "__main__":
    unittest.main()
