"""测试共用：从真实录制的 fixtures 构造对象。"""
from babybite.mcp_client import OfflineClient

LUNCH = "2026-10-12 11:30"
STORE_ARGS = {"storeCode": "1450713", "orderType": 1, "beType": 1, "reservationDate": LUNCH}


def load_index():
    from babybite.nutrition import NutritionIndex, parse_nutrition_table
    payload = OfflineClient().call_tool("list-nutrition-foods", {})
    return NutritionIndex(parse_nutrition_table(payload["data"]))


def load_detail(code):
    from babybite.menu import parse_meal_detail
    return parse_meal_detail(OfflineClient().call_tool("query-meal-detail", dict(STORE_ARGS, code=code)))


def load_menu():
    from babybite.menu import parse_menu
    return parse_menu(OfflineClient().call_tool("query-meals", STORE_ARGS))
