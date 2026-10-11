import unittest

from babybite.mcp_client import OfflineClient
from babybite.menu import parse_meal_detail, parse_menu, parse_stores
from tests.helpers import load_detail, load_menu


class StoreTest(unittest.TestCase):
    def test_real_stores(self):
        args = {"beType": 1, "searchType": 2, "city": "上海市", "keyword": "人民广场"}
        stores = parse_stores(OfflineClient().call_tool("query-nearby-stores", args))
        first = stores[0]
        self.assertEqual((first.code, first.name), ("1450713", "麦当劳上海黄浦华旭国际大厦餐厅"))
        self.assertEqual((first.distance_m, first.open_now, first.hours), (144, True, "00:00-23:59"))
        self.assertTrue(first.reservation)
        self.assertIsNone(first.be_code)
        self.assertEqual(len(first.reservation_options), 2)
        self.assertEqual(first.reservation_options[0][:2], ("2026-10-12", True))
        self.assertFalse(stores[1].open_now)

    def test_empty_payload(self):
        self.assertEqual(parse_stores({"data": None}), [])
        self.assertEqual(parse_menu({}), [])


class MenuTest(unittest.TestCase):
    def test_real_menu(self):
        menu = load_menu()
        self.assertEqual(len(menu), 86)
        happy = next(m for m in menu if m.code == "9900016057")
        self.assertEqual((happy.name, happy.price_yuan, happy.category), ("汉堡开心乐园餐", 23.5, "开心乐园"))
        self.assertTrue(all("\n" not in m.category for m in menu))


class DetailTest(unittest.TestCase):
    def test_happy_meal_rounds(self):
        detail = load_detail("9900016057")
        self.assertEqual(detail.name, "汉堡开心乐园餐")
        self.assertEqual([r.id for r in detail.rounds], ["1", "2", "3", "4", "5"])
        burger = detail.rounds[0].choices[0]
        self.assertEqual(burger.code, "1000")
        self.assertTrue(burger.mod_groups[0].toggleable)
        self.assertEqual([v.name for v in burger.mod_groups[0].values], ["酸黄瓜", "洋葱粒", "番茄酱", "芥末酱"])
        self.assertEqual(burger.mod_groups[0].values[0].unselected_key, "0-0")
        self.assertEqual([c.is_default for c in detail.rounds[2].choices], [True, True])

    def test_single_item_modification(self):
        detail = load_detail("1120")
        self.assertEqual(detail.rounds, ())
        self.assertEqual([v.name for v in detail.mod_groups[0].values], ["吉士", "酸黄瓜", "洋葱粒", "番茄酱", "芥末酱"])

    def test_ice_group_is_not_toggleable(self):
        detail = load_detail("9900016055")
        cola = detail.rounds[6].choices[0]
        self.assertEqual(cola.name, "可乐中杯")
        self.assertFalse(cola.mod_groups[0].toggleable)

    def test_missing_data(self):
        detail = parse_meal_detail({"data": None})
        self.assertEqual((detail.code, detail.rounds, detail.mod_groups), ("", (), ()))


if __name__ == "__main__":
    unittest.main()
