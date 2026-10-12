"""真实只读冒烟：门店 → 菜单 → 营养 → 详情 → 特制算价。不下单。

用法：MCD_MCP_TOKEN=... python3 scripts/smoke_real.py [--city 上海市 --keyword 人民广场 --age-months 18]
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from babybite.age_rules import sodium_budget  # noqa: E402
from babybite.customize import to_order_item  # noqa: E402
from babybite.mcp_client import client_from_env  # noqa: E402
from babybite.menu import parse_meal_detail, parse_menu, parse_stores  # noqa: E402
from babybite.nutrition import NutritionIndex, parse_nutrition_table  # noqa: E402
from babybite.planner import build_plans, rank_candidates  # noqa: E402
from babybite.scenes import get_scene, store_args  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", default="上海市")
    parser.add_argument("--keyword", default="人民广场")
    parser.add_argument("--age-months", type=int, default=18)
    args = parser.parse_args()
    when = (dt.date.today() + dt.timedelta(days=1)).strftime("%Y-%m-%d") + " 11:30"
    client = client_from_env(offline=False)
    stores = parse_stores(client.call_tool("query-nearby-stores", {
        "beType": 1, "searchType": 2, "city": args.city, "keyword": args.keyword}))
    store = next(s for s in stores if s.reservation)
    print(f"[1/5] 门店 {store.code} {store.name}")
    base = store_args(get_scene("pickup"), store.code, None, when)
    menu = parse_menu(client.call_tool("query-meals", base))
    print(f"[2/5] 菜单 {len(menu)} 个餐品（预约 {when}）")
    index = NutritionIndex(parse_nutrition_table(client.call_tool("list-nutrition-foods", {})["data"]))
    print(f"[3/5] 营养数据 {len(index)} 条")
    candidates = rank_candidates(menu, args.age_months)
    details = {m.code: parse_meal_detail(client.call_tool("query-meal-detail", dict(base, code=m.code)))
               for m in candidates}
    plans, excluded = build_plans(candidates, details, index, sodium_budget(args.age_months), args.age_months)
    print(f"[4/5] 方案 {len(plans)} 个，未推荐 {len(excluded)} 个")
    if not plans:
        print("失败：没有生成方案", file=sys.stderr)
        return 1
    data = client.call_tool("calculate-price", dict(base, items=[to_order_item(plans[0].item)]))["data"]
    print(f"[5/5] {plans[0].item.name} 宝宝特制算价成功：¥{data['price'] / 100:.2f}，"
          f"线上去料：{'、'.join(plans[0].item.removed_all) or '无'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
