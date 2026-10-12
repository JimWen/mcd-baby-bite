import json
import unittest

from babybite.activities import Campaign, clean_text, kid_campaigns, toy_of
from babybite.cards import render_json, render_markdown
from babybite.customize import customize_meal
from babybite.mcp_client import OfflineClient
from tests.helpers import load_detail
from tests.test_cards import make_result


class ToyTest(unittest.TestCase):
    def test_toy_from_happy_meal(self):
        self.assertEqual(toy_of(customize_meal(load_detail("9900016057"), 18)), "海绵宝宝×航海王系列玩具")

    def test_no_toy_for_single_item(self):
        self.assertIsNone(toy_of(customize_meal(load_detail("1406"), 30)))


class CampaignTest(unittest.TestCase):
    def test_real_calendar(self):
        campaigns = kid_campaigns(OfflineClient().call_tool("campaign-calendar", {}))
        self.assertTrue(1 <= len(campaigns) <= 3)
        self.assertIn("过家家派对上线，快来一起解锁梦想职业", [c.title for c in campaigns])
        for campaign in campaigns:
            self.assertLessEqual(len(campaign.summary), 40)
            self.assertEqual(campaign.date, "2026-10-12")

    def test_clean_text(self):
        self.assertEqual(clean_text("  超值𝟗.𝟗元早餐两件套陪你开工啦😋 "), "超值9.9元早餐两件套陪你开工啦")

    def test_filter_dedup_and_summary(self):
        payload = {"data": {"dailyList": [
            {"date": "2026-10-12", "events": [
                {"articleDto": {"title": "9.9元早餐", "content": "早八的快乐"}},
                {"articleDto": {"title": "亲子读书会🎉", "content": "\n开心乐园餐+随机玩具一份\n第二行"}},
                {"activityTitle": "无文章的活动"},
            ]},
            {"date": "2026-10-13", "events": [{"articleDto": {"title": "亲子读书会", "content": "重复"}}]},
        ]}}
        self.assertEqual(kid_campaigns(payload), [Campaign("2026-10-12", "亲子读书会", "开心乐园餐+随机玩具一份")])

    def test_summary_truncated_and_limit(self):
        events = [{"articleDto": {"title": f"亲子活动{i}", "content": "宝" * 60}} for i in range(5)]
        campaigns = kid_campaigns({"data": {"dailyList": [{"date": "d", "events": events}]}})
        self.assertEqual(len(campaigns), 3)
        self.assertEqual(len(campaigns[0].summary), 40)

    def test_bad_payload(self):
        self.assertEqual(kid_campaigns({"data": "纯文本"}), [])
        self.assertEqual(kid_campaigns({}), [])


class RenderTest(unittest.TestCase):
    def test_toy_and_campaign_section(self):
        result = make_result()
        result.campaigns = [Campaign("2026-10-12", "亲子读书会", "开心乐园餐+随机玩具一份")]
        text = render_markdown(result)
        self.assertIn("## 玩具与亲子活动", text)
        self.assertIn("- 随餐玩具：海绵宝宝×航海王系列玩具（开心乐园餐附赠，以门店实际发放为准）", text)
        self.assertIn("- 亲子活动：亲子读书会——开心乐园餐+随机玩具一份", text)
        data = json.loads(render_json(result))
        self.assertEqual(data["toy"], "海绵宝宝×航海王系列玩具")
        self.assertEqual(data["campaigns"],
                         [{"date": "2026-10-12", "title": "亲子读书会", "summary": "开心乐园餐+随机玩具一份"}])

    def test_no_section_without_toy_or_campaign(self):
        result = make_result()
        result.plans = []
        self.assertNotIn("## 玩具与亲子活动", render_markdown(result))


if __name__ == "__main__":
    unittest.main()
