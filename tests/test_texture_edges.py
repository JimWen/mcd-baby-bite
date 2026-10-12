import json
import unittest
from dataclasses import replace

from babybite.age_rules import sodium_budget
from babybite.cards import render_html, render_json
from babybite.customize import CustomizedItem, CustomizedLine, customize_meal
from babybite.phone_cards import age_rows, card_candidate_codes
from babybite.planner import plan_for_item
from tests.helpers import load_detail, load_index, load_menu
from tests.test_cards import make_result

CORN_NOTE = "整份，压碎后再给（整粒玉米有噎食风险）"
APPLE_NOTE = "整份，切成细丝或刮泥再给（生苹果较硬）"
TEXTURE_TIP = ("4 岁以下：整粒玉米压碎、生苹果切细丝或刮泥、汉堡和鸡块撕成小块，"
               "全程看护进食（参考美国 CDC 幼儿防噎指南）。")


class TextureEdgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = load_index()

    def test_preparation_only_changes_notes_at_age_boundaries(self):
        for age in (18, 47, 48, 60):
            with self.subTest(age=age):
                item = customize_meal(load_detail("9900016056"), age)
                budget = sodium_budget(age)
                original = plan_for_item(item, self.index, budget, 23.5)
                prepared = plan_for_item(item, self.index, budget, 23.5, age_months=age)
                notes = {c.name: c.note for c in prepared.components}
                self.assertEqual(notes["小杯玉米杯"], CORN_NOTE if age < 48 else "整份")
                self.assertEqual(notes["苹果片一袋(60g)"], APPLE_NOTE if age < 48 else "整份")
                restored = tuple(replace(c, note=old.note)
                                 for c, old in zip(prepared.components, original.components))
                self.assertEqual(replace(prepared, components=restored), original)

    def test_apple_juice_keeps_plain_note(self):
        for name in ("100%苹果汁", "100% 苹果汁(盒装)"):
            with self.subTest(name=name):
                line = CustomizedLine("1", "饮料", "6362", name, 1, (), (), None)
                item = CustomizedItem("X", "果汁", 1, (line,), ())
                plan = plan_for_item(item, self.index, sodium_budget(36), age_months=36)
                component, = plan.components
                self.assertEqual((component.role, component.portion, component.note),
                                 ("side", 1.0, "整份"))
                self.assertEqual(component.kid_sodium_mg, 0)

    def test_html_and_json_carry_preparation_notes(self):
        result = make_result()
        page = render_html(result)
        self.assertIn(CORN_NOTE, page)
        self.assertIn(TEXTURE_TIP, page)
        data = json.loads(render_json(result))
        notes = {c["name"]: c["note"] for p in data["plans"] for c in p["components"]}
        self.assertEqual(notes["小杯玉米杯"], CORN_NOTE)
        self.assertEqual(notes["苹果片一袋(60g)"], APPLE_NOTE)
        self.assertEqual(data["plans"][0]["kidSodiumMg"], 197.0)

    def test_phone_card_plans_use_each_rows_age(self):
        menu = load_menu()
        details = {code: load_detail(code) for code in card_candidate_codes(menu)}
        rows = age_rows(menu, details, self.index)
        self.assertEqual([row.age_months for row in rows], [18, 30, 60])
        for row in rows:
            with self.subTest(age=row.age_months):
                notes = {c.name: c.note for c in row.plan.components}
                self.assertEqual(notes["小杯玉米杯"], CORN_NOTE if row.age_months < 48 else "整份")


if __name__ == "__main__":
    unittest.main()
