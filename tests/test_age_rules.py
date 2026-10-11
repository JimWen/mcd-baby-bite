import unittest

from babybite.age_rules import (INFANT_ADVICE, band_for, kid_item_verdict, parse_allergies,
                                possible_allergens, sodium_budget)


class BudgetTest(unittest.TestCase):
    def test_bands_and_budgets(self):
        cases = {12: (590, 197), 23: (590, 197), 24: (786, 262), 47: (786, 262),
                 48: (1179, 393), 83: (1179, 393), 84: (1572, 524), 132: (1965, 655), 216: (1965, 655)}
        for months, (daily, meal) in cases.items():
            with self.subTest(months=months):
                budget = sodium_budget(months)
                self.assertEqual((budget.daily_sodium_mg, budget.meal_sodium_mg), (daily, meal))

    def test_infant_gets_no_budget(self):
        self.assertIsNone(sodium_budget(11))
        self.assertIsNone(sodium_budget(0))
        self.assertIn("不建议外食", INFANT_ADVICE)

    def test_invalid_age(self):
        for bad in (-1, 217, True, 1.5):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    band_for(bad)

    def test_meal_share(self):
        self.assertEqual(sodium_budget(24, 0.5).meal_sodium_mg, 393)
        with self.assertRaises(ValueError):
            sodium_budget(24, 0.1)
        with self.assertRaises(ValueError):
            sodium_budget(24, 0.6)

    def test_sources_are_cited(self):
        self.assertIn("T/CNSS 022-2023", band_for(30).source)
        self.assertIn("2022", band_for(18).source)


class VerdictTest(unittest.TestCase):
    def test_excluded_for_everyone(self):
        for name in ("可乐中杯", "麦咖啡™冰美式中杯", "麦辣鸡腿汉堡", "【美汁源】“多汁柠柠”", "热浓浓黑巧中杯"):
            with self.subTest(name=name):
                self.assertFalse(kid_item_verdict(name, 60).allowed)

    def test_juice_and_dessert_only_after_36_months(self):
        self.assertFalse(kid_item_verdict("100%苹果汁", 30).allowed)
        self.assertTrue(kid_item_verdict("100%苹果汁", 40).allowed)
        self.assertFalse(kid_item_verdict("圆筒冰淇淋", 35).allowed)

    def test_preferred(self):
        for name in ("小杯玉米杯", "苹果片一袋(60g)", "纯牛奶", "纯悦"):
            with self.subTest(name=name):
                verdict = kid_item_verdict(name, 18)
                self.assertTrue(verdict.allowed and verdict.preferred)

    def test_allergies(self):
        self.assertEqual(parse_allergies("鱼、蛋 奶,麸质"), ("鱼类", "蛋类", "乳制品", "小麦麸质"))
        self.assertEqual(parse_allergies(None), ())
        with self.assertRaises(ValueError):
            parse_allergies("榴莲")
        verdict = kid_item_verdict("鱼排堡开心乐园餐", 30, ("鱼类",))
        self.assertFalse(verdict.allowed)
        self.assertIn("鱼类", verdict.reason)

    def test_possible_allergens(self):
        self.assertEqual(possible_allergens("麦乐鸡-4块"), ("小麦麸质",))
        self.assertEqual(possible_allergens("纯牛奶"), ("乳制品",))
        self.assertEqual(set(possible_allergens("鱼排堡")), {"鱼类", "小麦麸质"})


if __name__ == "__main__":
    unittest.main()
