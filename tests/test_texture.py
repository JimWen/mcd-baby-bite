import unittest

from babybite.age_rules import sodium_budget
from babybite.cards import TIPS, render_markdown
from babybite.customize import customize_meal
from babybite.planner import build_plans, plan_for_item, rank_candidates
from tests.helpers import load_detail, load_index, load_menu
from tests.test_cards import make_result

CORN_NOTE = "整份，压碎后再给（整粒玉米有噎食风险）"
APPLE_NOTE = "整份，切成细丝或刮泥再给（生苹果较硬）"


class TextureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = load_index()

    def notes(self, code, age):
        plan = plan_for_item(customize_meal(load_detail(code), age), self.index, sodium_budget(age), age_months=age)
        return {c.name: c.note for c in plan.components}

    def test_toddler_corn_and_apple_need_preparation(self):
        notes = self.notes("9900016056", 18)
        self.assertEqual(notes["小杯玉米杯"], CORN_NOTE)
        self.assertEqual(notes["苹果片一袋(60g)"], APPLE_NOTE)
        self.assertEqual(notes["纯牛奶"], "整份")

    def test_boundary_47_and_48_months(self):
        self.assertEqual(self.notes("9900016056", 47)["小杯玉米杯"], CORN_NOTE)
        self.assertEqual(self.notes("9900016056", 48)["小杯玉米杯"], "整份")

    def test_without_age_keeps_plain_note(self):
        plan = plan_for_item(customize_meal(load_detail("9900016056"), 18), self.index, sodium_budget(18))
        self.assertEqual({c.name: c.note for c in plan.components}["小杯玉米杯"], "整份")

    def test_build_plans_passes_age(self):
        menu = load_menu()
        candidates = rank_candidates(menu, 18)
        details = {m.code: load_detail(m.code) for m in candidates}
        plans, _ = build_plans(candidates, details, self.index, sodium_budget(18), 18)
        corn = [c.note for p in plans for c in p.components if c.name == "小杯玉米杯"]
        self.assertTrue(corn and all(note == CORN_NOTE for note in corn))

    def test_markdown_row_and_tip(self):
        text = render_markdown(make_result())
        self.assertIn(f"| 小杯玉米杯 | - | 1mg | {CORN_NOTE} | 1mg |", text)
        self.assertTrue(any("美国 CDC" in tip and "整粒玉米" in tip for tip in TIPS))


if __name__ == "__main__":
    unittest.main()
