"""用真实 Token 重新录制离线演示数据（只调用只读接口），写入 fixtures/real/。

用法：MCD_MCP_TOKEN=... python3 scripts/record_fixtures.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from babybite.age_rules import sodium_budget  # noqa: E402
from babybite.cli import OFFLINE_CITY, OFFLINE_KEYWORD, OFFLINE_WHEN  # noqa: E402
from babybite.customize import to_order_item  # noqa: E402
from babybite.mcp_client import client_from_env, unwrap_tool_result  # noqa: E402
from babybite.menu import parse_meal_detail, parse_menu, parse_stores  # noqa: E402
from babybite.nutrition import NutritionIndex, parse_nutrition_table  # noqa: E402
from babybite.planner import build_plans, rank_candidates  # noqa: E402
from babybite.scenes import get_scene, store_args  # noqa: E402

OUT = ROOT / "fixtures" / "real"
DEMO_AGES = (18, 30)
EXTRA_DETAIL_CODES = ("1120", "4437", "1401", "1600", "1406", "9900016055")


def sanitize(result: dict) -> dict:
    content = result.get("structuredContent")
    if isinstance(content, dict) and "traceId" in content:
        content["traceId"] = "recorded"
    for block in result.get("content") or []:
        if block.get("type") == "text":
            block["text"] = re.sub(r'"traceId":"[0-9a-f]+"', '"traceId":"recorded"', block["text"])
    return result


def save(client, tool: str, args: dict, filename: str) -> dict:
    result = sanitize(client.call_tool_raw(tool, args))
    record = {"tool": tool, "args": args, "recordedAt": OFFLINE_WHEN[:10], "result": result}
    (OUT / filename).write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"saved {filename}")
    return unwrap_tool_result(result)


def main() -> int:
    client = client_from_env(offline=False)
    scene = get_scene("pickup")
    stores_args = {"beType": 1, "searchType": 2, "city": OFFLINE_CITY, "keyword": OFFLINE_KEYWORD}
    store = parse_stores(save(client, "query-nearby-stores", stores_args,
                              "query-nearby-stores__pickup_renminguangchang.json"))[0]
    base = store_args(scene, store.code, None, OFFLINE_WHEN)
    menu = parse_menu(save(client, "query-meals", base, f"query-meals__{store.code}_lunch.json"))
    index = NutritionIndex(parse_nutrition_table(
        save(client, "list-nutrition-foods", {}, "list-nutrition-foods.json")["data"]))
    codes = {m.code for age in DEMO_AGES for m in rank_candidates(menu, age)}
    codes |= {m.code for m in rank_candidates(menu, 30, ("鱼类",))} | set(EXTRA_DETAIL_CODES)
    details = {code: parse_meal_detail(save(client, "query-meal-detail", dict(base, code=code),
                                            f"query-meal-detail__{code}.json")) for code in sorted(codes)}
    priced = set()
    for age in DEMO_AGES:
        plans, _ = build_plans(rank_candidates(menu, age), details, index, sodium_budget(age), age)
        for plan in plans:
            item = to_order_item(plan.item)
            key = json.dumps(item, sort_keys=True)
            if key in priced:
                continue
            priced.add(key)
            save(client, "calculate-price", dict(base, items=[item]),
                 f"calculate-price__{plan.item.product_code}_{age}m.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
