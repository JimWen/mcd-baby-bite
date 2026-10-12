"""批次 H 的边界与集成回归；验收方测试保持不变。"""
from __future__ import annotations

import io
import json
import unittest
from dataclasses import FrozenInstanceError
from unittest import mock

from babybite.activities import Campaign, clean_text, kid_campaigns
from babybite.amap import PlaySpot, Throttled, nearby_play
from babybite.cards import plan_to_dict, render_html, render_markdown
from babybite.cli import main
from babybite.errors import BabyBiteError
from babybite.mcp_client import McpHttpClient, OfflineClient
from tests.test_cards import make_result
from tests.test_play import ScriptedAmap


class ActivitiesEdgeTest(unittest.TestCase):
    def test_campaign_titles_keep_chinese_punctuation_and_clean_digits(self):
        payload = {"data": {"dailyList": [{"date": "d", "events": [
            {"articleDto": {"title": "亲子活动，𝟗.𝟗元！🎉", "content": "摘要"}},
            {"articleDto": {"title": "亲子活动，9.9元！", "content": "重复"}},
        ]}]}}
        self.assertEqual(kid_campaigns(payload), [Campaign("d", "亲子活动，9.9元！", "摘要")])
        self.assertEqual(clean_text("Ａ，𝟗"), "A,9")

    def test_body_keywords_and_first_clean_nonempty_line(self):
        payload = {"data": {"dailyList": [{"date": "d", "events": [
            {"articleDto": {"title": "周末见", "content": "\n🎉\n儿童体验营\n第二行"}},
        ]}]}}
        self.assertEqual(kid_campaigns(payload), [Campaign("d", "周末见", "儿童体验营")])
        self.assertEqual(kid_campaigns(payload, limit=0), [])
        self.assertEqual(kid_campaigns(payload, limit=-1), [])

    def test_unicode_normalized_before_supplementary_characters_removed(self):
        self.assertEqual(clean_text("  𝟗.𝟗 ©\U00020000🎉  "), "9.9")

    def test_empty_or_malformed_calendar_entries(self):
        for data in (None, [], {"dailyList": None}, {"dailyList": [None, {"events": None}]}):
            with self.subTest(data=data):
                self.assertEqual(kid_campaigns({"data": data}), [])

    def test_models_are_frozen_and_plan_lists_are_independent(self):
        for value in (Campaign("d", "亲子", "摘要"), PlaySpot("公园", "公园", 1, 10, "地址")):
            with self.assertRaises(FrozenInstanceError):
                value.name = "改名"
        first, second = make_result(), make_result()
        first.campaigns.append(Campaign("d", "亲子", "摘要"))
        first.play_spots.append(PlaySpot("公园", "公园", 1, 10, "地址"))
        self.assertEqual(second.campaigns, [])
        self.assertEqual(second.play_spots, [])


class NearbyEdgeTest(unittest.TestCase):
    def test_first_four_candidates_are_routed_before_sort_and_limit(self):
        calls = []

        class Client:
            def call_tool_text(self, name, args):
                calls.append((name, args))
                if name == "maps_around_search":
                    return json.dumps({"pois": [
                        {"id": str(i), "name": "公园" + str(i), "typecode": "110101", "address": "地址"}
                        for i in range(1, 7)
                    ]})
                if name == "maps_search_detail":
                    return json.dumps({"location": args["id"] + ",0"})
                return json.dumps({"route": {"paths": [{
                    "duration": 600 - int(args["destination"].split(",")[0]) * 60, "distance": "100",
                }]}})

        self.assertEqual([s.name for s in nearby_play(Client(), "0,0")], ["公园4", "公园3", "公园2"])
        self.assertEqual([a["id"] for n, a in calls if n == "maps_search_detail"], ["1", "2", "3", "4"])
        self.assertEqual(len(nearby_play(Client(), "0,0", limit=1)), 1)
        self.assertEqual(nearby_play(Client(), "0,0", limit=0), [])

    def test_missing_coordinates_or_walking_path_are_skipped(self):
        class Client(ScriptedAmap):
            def call_tool_text(self, name, args):
                if name == "maps_search_detail" and args["id"] == "P1":
                    return "{}"
                if name == "maps_direction_walking":
                    return '{"route":{"paths":[]}}'
                return super().call_tool_text(name, args)

        self.assertEqual(nearby_play(Client(), "0,0"), [])

    def test_throttle_uses_elapsed_time_and_does_not_sleep_after_last_failure(self):
        now = [0.0]
        starts, sleeps = [], []

        def sleep(seconds):
            sleeps.append(seconds)
            now[0] += seconds

        class Client:
            def call_tool_text(self, name, args):
                starts.append(now[0])
                if name == "busy":
                    raise BabyBiteError("CUQPS_HAS_EXCEEDED_THE_LIMIT")
                return "{}"

        client = Throttled(Client(), sleep=sleep, clock=lambda: now[0])
        client.call_tool_text("ok", {})
        now[0] += 0.1
        client.call_tool_text("ok", {})
        self.assertAlmostEqual(starts[1] - starts[0], 0.35)
        now[0] += 1
        with self.assertRaises(BabyBiteError):
            client.call_tool_text("busy", {})
        self.assertEqual(len(starts), 5)
        self.assertEqual(sleeps[1:], [1.0, 1.0])
        self.assertFalse(hasattr(client, "call_tool"))


class RenderEdgeTest(unittest.TestCase):
    def result(self):
        result = make_result()
        result.campaigns = [Campaign("d", "亲子<script>", "摘要&内容")]
        result.play_spots = [PlaySpot("公园<script>", "公园", 5, 400, "地址&路")]
        return result

    def test_markdown_section_order_and_play_reminder(self):
        text = render_markdown(self.result())
        headings = ["## 未推荐", "## 玩具与亲子活动", "## 饭后遛娃（高德，门店周边 2 公里）", "## 大人餐参考"]
        positions = [text.index(heading) for heading in headings]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("- 出发前请留意开放时间与天气\n\n## 大人餐参考", text)

    def test_play_json_and_html_escape_external_text(self):
        result = self.result()
        self.assertEqual(plan_to_dict(result)["playSpots"], [{
            "name": "公园<script>", "kind": "公园", "walkMinutes": 5, "walkMeters": 400, "address": "地址&路",
        }])
        page = render_html(result)
        for part in ("玩具与亲子活动", "随餐玩具：海绵宝宝×航海王系列玩具", "亲子&lt;script&gt;",
                     "摘要&amp;内容", "饭后遛娃（高德，门店周边 2 公里）", "公园&lt;script&gt;",
                     "步行约 5 分钟（400 米）", "出发前请留意开放时间与天气"):
            self.assertIn(part, page)
        self.assertNotIn("<script>", page)

    def test_empty_extensions_and_campaign_without_meal(self):
        result = make_result()
        result.plans = []
        data = plan_to_dict(result)
        self.assertIsNone(data["toy"])
        self.assertEqual((data["campaigns"], data["playSpots"]), ([], []))
        for text in (render_markdown(result), render_html(result)):
            self.assertNotIn("玩具与亲子活动", text)
            self.assertNotIn("饭后遛娃", text)
        result.campaigns = [Campaign("d", "亲子活动", "摘要")]
        self.assertIn("亲子活动：亲子活动——摘要", render_markdown(result))
        self.assertIn("亲子活动：亲子活动——摘要", render_html(result))


class CliEdgeTest(unittest.TestCase):
    def plan(self, amap=None, extra=(), client=None, offline=False):
        out = io.StringIO()
        factory = mock.Mock(return_value=amap)
        argv = ["plan", "--age-months", "18", "--city", "上海市", "--keyword", "人民广场"]
        if offline:
            argv.append("--offline")
        code = main(argv + list(extra), client_factory=lambda flag: client or OfflineClient(),
                    amap_factory=factory, out=out)
        self.assertEqual(code, 0)
        return out.getvalue(), factory

    def test_calendar_requested_once_and_failure_is_silent(self):
        replay = OfflineClient()
        client = mock.Mock()

        def call(name, args):
            if name == "campaign-calendar":
                raise BabyBiteError("活动日历不可用")
            return replay.call_tool(name, args)

        client.call_tool.side_effect = call
        text, factory = self.plan(client=client, extra=("--json",))
        self.assertEqual(json.loads(text)["campaigns"], [])
        self.assertNotIn("活动日历不可用", text)
        self.assertEqual(client.call_tool.call_args_list.count(mock.call("campaign-calendar", {})), 1)
        factory.assert_not_called()
        text, _ = self.plan(extra=("--json",), offline=True)
        self.assertEqual(len(json.loads(text)["campaigns"]), 3)

    def test_calendar_still_requested_without_candidates(self):
        replay = OfflineClient()
        client = mock.Mock()
        client.call_tool.side_effect = lambda name, args: {"data": []} if name == "query-meals" else replay.call_tool(name, args)
        text, _ = self.plan(client=client, extra=("--json",))
        data = json.loads(text)
        self.assertEqual(data["plans"], [])
        self.assertEqual(len(data["campaigns"]), 3)

    def test_play_failures_keep_meal_and_notice(self):
        for amap in (mock.Mock(call_tool_text=mock.Mock(side_effect=BabyBiteError("服务忙"))),
                     mock.Mock(call_tool_text=mock.Mock(return_value='{"pois":[]}'))):
            with self.subTest(amap=amap):
                text, _ = self.plan(amap=amap, extra=("--play", "--json"))
                data = json.loads(text)
                self.assertTrue(data["plans"])
                self.assertEqual(data["playSpots"], [])
                self.assertTrue(any("已跳过饭后遛娃推荐" in n for n in data["notices"]))

    def test_offline_play_never_creates_amap_client(self):
        text, factory = self.plan(extra=("--play",), offline=True)
        self.assertIn("离线演示不包含饭后遛娃推荐（需要高德 Key 的在线模式）", text)
        factory.assert_not_called()

    def test_from_and_play_share_one_throttled_http_client(self):
        replay = OfflineClient()
        scripted = ScriptedAmap()
        client = McpHttpClient("https://unused.invalid")

        def call(name, args):
            if name in ("maps_geo", "maps_schema_navi"):
                return replay.call_tool_text(name, args)
            if name == "maps_direction_walking" and args["destination"] == "121.0,31.0":
                return '{"route":{"paths":[{"duration":60,"distance":50}]}}'
            return scripted.call_tool_text(name, args)

        client.call_tool_text = mock.Mock(side_effect=call)
        wrappers = []

        def wrap(raw):
            wrapped = Throttled(raw, sleep=lambda seconds: None, clock=lambda: 0.0)
            wrappers.append(wrapped)
            return wrapped

        with mock.patch("babybite.cli.Throttled", side_effect=wrap) as throttle:
            text, factory = self.plan(amap=client, extra=("--from", "家", "--play", "--json"))
        throttle.assert_called_once_with(client)
        factory.assert_called_once_with(False)
        self.assertEqual(len(wrappers), 1)
        data = json.loads(text)
        self.assertEqual(len(data["playSpots"]), 2)
        self.assertTrue(any("高德步行" in n for n in data["notices"]))

    def test_injected_and_offline_clients_are_not_wrapped(self):
        with mock.patch("babybite.cli.Throttled") as throttle:
            self.plan(amap=ScriptedAmap(), extra=("--play",))
            self.plan(amap=OfflineClient(), extra=("--from", "家", "--play"), offline=True)
        throttle.assert_not_called()


if __name__ == "__main__":
    unittest.main()
