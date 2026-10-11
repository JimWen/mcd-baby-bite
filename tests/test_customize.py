import json
import unittest
from pathlib import Path

from babybite.customize import customize_meal, modification_payload, pick_choice, should_remove, to_order_item
from tests.helpers import load_detail

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "real"


def recorded_items(name):
    return json.loads((FIXTURES / name).read_text("utf-8"))["args"]["items"]


class CustomizeTest(unittest.TestCase):
    def test_toddler_burger_happy_meal_matches_real_priced_payload(self):
        item = customize_meal(load_detail("9900016057"), 18)
        self.assertEqual([to_order_item(item)], recorded_items("calculate-price__9900016057_toddler.json"))
        self.assertEqual(item.removed_all, ("酸黄瓜", "洋葱粒", "番茄酱", "芥末酱"))
        self.assertEqual(item.salt_requests, ("牛肉饼不撒盐", "薯条不加盐"))

    def test_nuggets_happy_meal_matches_real_priced_payload(self):
        item = customize_meal(load_detail("9900016056"), 18)
        self.assertEqual([to_order_item(item)], recorded_items("calculate-price__9900016056_toddler.json"))
        self.assertEqual(item.salt_requests, ())

    def test_whole_toggle_group_is_sent(self):
        item = customize_meal(load_detail("9900016058"), 30)
        fish = item.lines[0]
        self.assertEqual(list(fish.modification), [
            {"code": "100214", "key": "0-0", "quantity": 0},
            {"code": "102225", "key": "0-1", "quantity": 1},
        ])
        self.assertEqual(fish.removed, ("番茄酱",))

    def test_cheese_kept_from_48_months_and_keep_option(self):
        detail = load_detail("1120")
        young, older = customize_meal(detail, 30), customize_meal(detail, 48)
        self.assertIn("吉士", young.removed_all)
        self.assertNotIn("吉士", older.removed_all)
        self.assertIn({"code": "100141", "key": "0-1", "quantity": 1}, list(older.lines[0].modification))
        kept = customize_meal(detail, 30, keep=("洋葱",))
        self.assertNotIn("洋葱粒", kept.removed_all)

    def test_single_item_payload_uses_top_level_modification(self):
        payload = to_order_item(customize_meal(load_detail("1406"), 30))
        self.assertNotIn("roundList", payload)
        self.assertEqual(payload["modification"]["values"][0], {"code": "102201", "key": "0-0", "quantity": 0})
        self.assertEqual(payload["modification"]["values"][1], {"code": "120512", "key": "0-1", "quantity": 1})

    def test_group_without_removals_is_omitted_and_ice_group_untouched(self):
        detail = load_detail("9900016055")
        values, removed = modification_payload(detail.rounds[6].choices[0].mod_groups, 30)
        self.assertEqual((values, removed), ([], []))

    def test_snack_round_swaps_fries_to_corn(self):
        detail = load_detail("9900016055")
        choice = pick_choice(detail.rounds[4], 30)
        self.assertEqual(choice.name, "小杯玉米杯")
        line = customize_meal(detail, 30).lines[4]
        self.assertEqual(line.swapped_from, "中薯条")

    def test_dairy_allergy_swaps_milk_to_water(self):
        line = customize_meal(load_detail("9900016058"), 30, allergies=("乳制品",)).lines[3]
        self.assertEqual((line.name, line.swapped_from), ("纯悦", "纯牛奶"))

    def test_should_remove(self):
        self.assertTrue(should_remove("麦香鱼酱", 30))
        self.assertFalse(should_remove("切块生菜", 30))
        self.assertFalse(should_remove("番茄片", 30))
        self.assertFalse(should_remove("吉士", 60))

    def test_quantity_for_two_kids(self):
        self.assertEqual(to_order_item(customize_meal(load_detail("9900016056"), 30, quantity=2))["quantity"], 2)


if __name__ == "__main__":
    unittest.main()
