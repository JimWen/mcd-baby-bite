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
