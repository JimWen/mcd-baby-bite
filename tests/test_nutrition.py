import unittest

from babybite.errors import BabyBiteError
from babybite.mcp_client import OfflineClient
from babybite.nutrition import NutritionIndex, normalize_name, parse_nutrition_table
from tests.helpers import load_index


class ParseTest(unittest.TestCase):
    def test_real_table_has_160_rows(self):
        data = OfflineClient().call_tool("list-nutrition-foods", {})["data"]
        facts = parse_nutrition_table(data)
        self.assertEqual(len(facts), 160)
        burger = next(f for f in facts if f.name == "汉堡包")
        self.assertEqual((burger.energy_kcal, burger.sodium_mg, burger.calcium_mg), (248.0, 492.0, 61.0))

    def test_null_values_and_comma_in_name(self):
        table = ("[2]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:\n"
                 "  测试,新品,null,1,2,3,4,5,null,7\n"
                 "  普通,null,10,20,1,1,1,null,0")
        facts = parse_nutrition_table(table)
        self.assertEqual(facts[0].name, "测试,新品")
        self.assertIsNone(facts[0].sodium_mg)
        self.assertIsNone(facts[1].sodium_mg)
        self.assertEqual(facts[1].energy_kcal, 20.0)

    def test_bad_header_raises(self):
        with self.assertRaises(BabyBiteError):
            parse_nutrition_table("no header\n a,b")
        with self.assertRaises(BabyBiteError):
            parse_nutrition_table("[1]{productName,energyKcal}:\n a,1")

    def test_empty_table(self):
        self.assertEqual(parse_nutrition_table(""), [])


class LookupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = load_index()

    def test_combo_item_names_resolve(self):
        cases = {"麦乐鸡-4块": 337, "苹果片一袋(60g)": 0, "纯牛奶": 73, "100% 苹果汁(盒装)": 0,
                 "鱼排堡": 442, "小杯玉米杯": 1, "迷你薯条": 61, "汉堡包": 492, "吉士汉堡包": 673}
        for name, sodium in cases.items():
            with self.subTest(name=name):
                self.assertEqual(self.index.lookup(name).sodium_mg, sodium)

    def test_unknown_returns_none(self):
        self.assertIsNone(self.index.lookup("海绵宝宝×航海王系列玩具"))
        self.assertIsNone(self.index.lookup(""))

    def test_normalize(self):
        self.assertEqual(normalize_name("纯牛奶（盒装）"), "纯牛奶")
        self.assertEqual(normalize_name("麦咖啡™ 美式"), "麦咖啡美式")
        self.assertEqual(len(NutritionIndex([])), 0)


if __name__ == "__main__":
    unittest.main()
