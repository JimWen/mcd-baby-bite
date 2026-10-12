import unittest

from babybite.age_rules import sodium_budget
from babybite.customize import CustomizedItem, CustomizedLine, customize_meal
from babybite.menu import MenuItem
from babybite.planner import (adult_suggestions, build_plans, floor_portion, plan_for_item,
                              rank_candidates, role_of)
from tests.helpers import load_detail, load_index, load_menu


def details_for(candidates):
    return {m.code: load_detail(m.code) for m in candidates}


class PortionTest(unittest.TestCase):
    def test_floor_portion(self):
        self.assertEqual([floor_portion(x) for x in (1.2, 0.8, 0.6, 0.4, 0.3, 0.25)],
                         [1.0, 0.75, 0.5, 1 / 3, 0.25, 0.25])
        self.assertIsNone(floor_portion(0.2))

    def test_roles(self):
        self.assertEqual([role_of(n) for n in ("汉堡包", "迷你薯条", "纯牛奶", "海绵宝宝×航海王系列玩具")],
                         ["main", "fries", "side", "skip"])


class PlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = load_index()
        cls.menu = load_menu()

    def test_burger_meal_at_18_months(self):
        budget = sodium_budget(18)
        plan = plan_for_item(customize_meal(load_detail("9900016057"), 18), self.index, budget, 23.5)
        comps = {c.name: c for c in plan.components}
        self.assertEqual(comps["汉堡包"].portion, 0.25)
        self.assertEqual(comps["迷你薯条"].portion, 0.0)
        self.assertEqual(comps["纯牛奶"].portion, 1.0)
        self.assertAlmostEqual(plan.kid_sodium_mg, 197.0)
        self.assertEqual((plan.meal_pct, plan.day_pct), (100, 33))
        self.assertEqual(plan.unknown_nutrition, ())

    def test_nuggets_meal_at_30_months_shows_pieces(self):
        plan = plan_for_item(customize_meal(load_detail("9900016056"), 30), self.index, sodium_budget(30))
        nuggets = plan.components[0]
        self.assertEqual((nuggets.portion, nuggets.note), (0.5, "1/2 份（约 2 块）"))
        self.assertAlmostEqual(plan.kid_sodium_mg, 242.5)

    def test_candidates_and_ranking_at_18_months(self):
        candidates = rank_candidates(self.menu, 18)
        self.assertEqual([m.code for m in candidates], ["9900016057", "9900016058", "9900016056", "1406"])
        plans, excluded = build_plans(candidates, details_for(candidates), self.index, sodium_budget(18), 18)
        self.assertEqual([p.item.name for p in plans], ["汉堡开心乐园餐", "鱼排堡开心乐园餐", "麦乐鸡开心乐园餐"])
        self.assertEqual(excluded, [("板烧鸡腿堡", "即使只吃 1/4 份也会超出本餐钠预算")])

    def test_fish_allergy_removes_fish_candidates(self):
        candidates = rank_candidates(self.menu, 30, ("鱼类",))
        self.assertEqual([m.code for m in candidates], ["9900016057", "9900016056", "1406", "1120"])

    def test_unknown_nutrition_is_marked_and_ranked_lower(self):
        line = CustomizedLine("1", "主食", "X1", "神秘新品堡", 1, (), (), None)
        milk = CustomizedLine("2", "饮料", "3755", "纯牛奶", 1, (), (), None)
        item = CustomizedItem("X", "神秘开心乐园餐", 1, (line, milk), ())
        plan = plan_for_item(item, self.index, sodium_budget(30))
        self.assertEqual(plan.unknown_nutrition, ("神秘新品堡",))
        self.assertIn("无官方营养数据", plan.components[0].note)
        self.assertAlmostEqual(plan.kid_sodium_mg, 73.0)
        known = plan_for_item(customize_meal(load_detail("9900016056"), 30), self.index, sodium_budget(30))
        self.assertLess(plan.score, known.score)

    def test_missing_detail_is_reported(self):
        candidates = rank_candidates(self.menu, 30)[:1]
        plans, excluded = build_plans(candidates, {}, self.index, sodium_budget(30), 30)
        self.assertEqual(plans, [])
        self.assertEqual(excluded, [("汉堡开心乐园餐", "未取到套餐详情")])

    def test_breakfast_muffin_is_a_candidate(self):
        menu = [MenuItem("B1", "烟肉蛋麦满分", 12.0, "麦满分"), MenuItem("B2", "麦满分单人餐", 19.9, "人气热卖"),
                MenuItem("B3", "皮蛋鸡肉粥", 9.0, "粥王系列")]
        self.assertEqual([m.code for m in rank_candidates(menu, 18)], ["B1"])
        line = CustomizedLine(None, "烟肉蛋麦满分", "B1", "烟肉蛋麦满分", 1, (), (), None)
        plan = plan_for_item(CustomizedItem("B1", "烟肉蛋麦满分", 1, (line,), ()), self.index, sodium_budget(18))
        self.assertEqual(plan.components[0].note, "1/3 份")
        self.assertAlmostEqual(plan.kid_sodium_mg, 161.0)

    def test_adult_suggestions(self):
        self.assertEqual([m.name for m in adult_suggestions(self.menu)],
                         ["人气超值四件套随心选", "鱼牛汉堡四件套随心选", "“我就喜欢”鸡薯双全盒"])


if __name__ == "__main__":
    unittest.main()
