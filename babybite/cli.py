"""命令行入口：python3 -m babybite <command>。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, Optional

from .age_rules import INFANT_ADVICE, band_for, parse_allergies, sodium_budget
from .cards import render_html, render_json, render_markdown
from .customize import to_order_item
from .errors import AuthError, BabyBiteError, FixtureMissingError, McdBusinessError
from .mcp_client import client_from_env
from .menu import Store, parse_meal_detail, parse_menu, parse_stores
from .nutrition import NutritionIndex, parse_nutrition_table
from .planner import PlanResult, adult_suggestions, build_plans, rank_candidates
from .scenes import get_scene, store_args

OFFLINE_WHEN = "2026-10-12 11:30"
OFFLINE_CITY, OFFLINE_KEYWORD = "上海市", "人民广场"
EXIT_OK, EXIT_USAGE, EXIT_AUTH, EXIT_BUSINESS, EXIT_ERROR = 0, 2, 3, 4, 5
CLOSED_HINT = "（门店可能不在营业时间，可用 --when \"yyyy-MM-dd HH:mm\" 预约）"
VERIFY_PRINT_LIMIT = 4000


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="babybite", description="小小麦门 · 带娃吃麦定制官（mcd-baby-bite）")
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="生成宝宝定制单")
    plan.add_argument("--age-months", type=int, required=True, help="宝宝月龄，如 18")
    plan.add_argument("--kids", type=int, default=1)
    plan.add_argument("--adults", type=int, default=1)
    plan.add_argument("--scene", choices=["pickup", "drive", "delivery"], default="pickup", help="到店自提 / 得来速 / 麦乐送")
    plan.add_argument("--address-id", help="外送地址 ID（见 addresses 命令）")
    plan.add_argument("--city")
    plan.add_argument("--keyword", help="位置关键词，如 人民广场")
    plan.add_argument("--store", help="门店编码（跳过门店搜索）")
    plan.add_argument("--be-code", help="得来速门店的 beCode")
    plan.add_argument("--when", help="预约时间 yyyy-MM-dd HH:mm")
    plan.add_argument("--allergy", help="过敏原，逗号分隔：鱼、奶、蛋、麸质")
    plan.add_argument("--keep", help="不想去掉的配料，逗号分隔，如 生菜,吉士")
    plan.add_argument("--meal-share", type=float, default=1 / 3, help="本餐占全天钠的比例，0.2-0.5")
    plan.add_argument("--json", action="store_true")
    plan.add_argument("--card", help="输出 HTML 卡片路径")
    plan.add_argument("--save", help="保存方案 JSON，供 order 使用")
    plan.add_argument("--offline", action="store_true", help="用录制的真实数据离线演示，无需 Token")

    stores = sub.add_parser("stores", help="查询附近门店")
    stores.add_argument("--city", required=True)
    stores.add_argument("--keyword", required=True)
    stores.add_argument("--scene", choices=["pickup", "drive"], default="pickup")
    stores.add_argument("--offline", action="store_true")

    sub.add_parser("addresses", help="列出外送地址（脱敏显示）")

    order = sub.add_parser("order", help="按保存的方案算价；加 --confirm 才会下单")
    order.add_argument("--plan", required=True)
    order.add_argument("--confirm", action="store_true")
    order.add_argument("--take-way", help="取餐方式 code，默认取算价返回的第一个")

    verify = sub.add_parser("verify", help="查询订单并核验特制")
    verify.add_argument("--order-id", required=True)
    verify.add_argument("--plan", help="对照的方案 JSON")

    cancel = sub.add_parser("cancel", help="取消订单")
    cancel.add_argument("--order-id", required=True)
    cancel.add_argument("--reason", default="1", help="1=改主意了 2=重复下单 3=点错了 -1=其它")
    return parser


def _split(text: Optional[str]) -> tuple:
    return tuple(t.strip() for t in (text or "").replace("，", ",").split(",") if t.strip())


def _resolve_store(client, scene, args, when) -> Store:
    if args.store:
        if scene.needs_be_code and not args.be_code:
            raise ValueError(f"{scene.label}指定门店时需要同时提供 --be-code")
        return Store(args.store, f"门店 {args.store}", "", None, True, "-", args.be_code, bool(when), ())
    city = args.city or (OFFLINE_CITY if args.offline else None)
    keyword = args.keyword or (OFFLINE_KEYWORD if args.offline else None)
    if not city or not keyword:
        raise ValueError("请提供 --city 和 --keyword（或用 --store 指定门店）")
    stores = parse_stores(client.call_tool("query-nearby-stores", {
        "beType": scene.be_type, "searchType": 2, "city": city, "keyword": keyword}))
    if not stores:
        raise BabyBiteError(f"在 {city}{keyword} 附近没有找到支持{scene.label}的门店")
    usable = [s for s in stores if (s.reservation if when else s.open_now)]
    if not usable:
        raise BabyBiteError("附近门店当前都不在营业时间" + CLOSED_HINT)
    return usable[0]


def _mask(text: str, keep: int = 2) -> str:
    text = str(text or "")
    return text[:keep] + "***" if len(text) > keep else "***"


def _resolve_delivery_store(client, scene, address_id: Optional[str]) -> Store:
    if not address_id:
        raise ValueError("麦乐送需要 --address-id，可先运行 addresses 命令查看")
    stores = parse_stores(client.call_tool("delivery-query-stores", {"beType": scene.be_type, "addressId": address_id}))
    usable = [s for s in stores if s.open_now and s.be_code]
    if not usable:
        raise BabyBiteError("该地址附近暂无可配送的营业门店" + CLOSED_HINT)
    return usable[0]


def cmd_addresses(args, factory, out) -> int:
    payload = factory(False).call_tool("delivery-query-addresses", {})
    rows = payload.get("data") or []
    if isinstance(rows, dict):
        rows = rows.get("addresses") or rows.get("list") or []
    if not rows:
        print("还没有配送地址，请先在麦当劳 App 中添加。", file=out)
    for row in rows:
        address_id = row.get("addressId") or row.get("id")
        full = row.get("fullAddress") or row.get("address") or ""  # 实测字段：addressId/contactName/fullAddress/phone
        print(f"{address_id}  {_mask(full, keep=6)}", file=out)
    return EXIT_OK


def _attach_price(client, base: dict, result: PlanResult) -> None:
    try:
        payload = client.call_tool("calculate-price", dict(base, items=[to_order_item(result.plans[0].item)]))
    except (FixtureMissingError, McdBusinessError) as exc:
        result.notices.append(f"实时核价未完成（{exc}），以菜单价为准。")
        return
    data = payload.get("data") or {}
    price = data.get("price")
    result.price_cents = int(price) if isinstance(price, (int, float)) else None
    result.take_ways = list(data.get("takeWayList") or [])


def _emit(result: PlanResult, args, out) -> None:
    print(render_json(result) if args.json else render_markdown(result), file=out)
    if args.card:
        Path(args.card).write_text(render_html(result), encoding="utf-8")
        print(f"HTML 卡片已保存：{args.card}", file=sys.stderr)
    if args.save:
        if not result.plans:
            raise BabyBiteError("没有可保存的方案")
        Path(args.save).write_text(render_json(result), encoding="utf-8")
        print(f"方案已保存：{args.save}（下单：python3 -m babybite order --plan {args.save} --confirm）", file=sys.stderr)


def cmd_plan(args, factory, out) -> int:
    band_for(args.age_months)
    allergies = parse_allergies(args.allergy)
    if args.kids < 1 or args.adults < 0:
        raise ValueError("--kids 至少为 1，--adults 不能为负数")
    budget = sodium_budget(args.age_months, args.meal_share)
    if budget is None:
        print(INFANT_ADVICE, file=out)
        return EXIT_OK
    scene = get_scene(args.scene)
    if args.store and scene.needs_be_code and not args.be_code:
        raise ValueError(f"{scene.label}指定门店时需要同时提供 --be-code")
    if scene.needs_address and not args.address_id:
        raise ValueError("麦乐送需要 --address-id，可先运行 addresses 命令查看")
    client = factory(args.offline)
    when = args.when or (OFFLINE_WHEN if args.offline else None)
    store = (_resolve_delivery_store(client, scene, args.address_id) if scene.needs_address
             else _resolve_store(client, scene, args, when))
    base = store_args(scene, store.code, store.be_code, when)
    menu = parse_menu(client.call_tool("query-meals", base))
    index = NutritionIndex(parse_nutrition_table(client.call_tool("list-nutrition-foods", {}).get("data") or ""))
    candidates = rank_candidates(menu, args.age_months, allergies)
    notices, details = [], {}
    for item in candidates:
        try:
            details[item.code] = parse_meal_detail(client.call_tool("query-meal-detail", dict(base, code=item.code)))
        except (McdBusinessError, FixtureMissingError) as exc:
            notices.append(f"{item.name} 详情获取失败：{exc}")
    plans, excluded = build_plans(candidates, details, index, budget, args.age_months, allergies,
                                  _split(args.keep), args.kids)
    result = PlanResult(args.age_months, args.kids, args.adults, scene, store, when, budget, plans, excluded,
                        adult_suggestions(menu), offline=args.offline, notices=notices,
                        address_id=args.address_id if scene.needs_address else None)
    if plans:
        _attach_price(client, base, result)
    _emit(result, args, out)
    return EXIT_OK


def cmd_stores(args, factory, out) -> int:
    scene = get_scene(args.scene)
    client = factory(args.offline)
    stores = parse_stores(client.call_tool("query-nearby-stores", {
        "beType": scene.be_type, "searchType": 2, "city": args.city, "keyword": args.keyword}))
    if not stores:
        print("附近没有找到门店", file=out)
    for s in stores:
        status = "营业中" if s.open_now else "未营业"
        extra = ("，可预约" if s.reservation else "") + (f"，beCode={s.be_code}" if s.be_code else "")
        distance = f"{s.distance_m}m" if s.distance_m is not None else "-"
        print(f"{s.code}  {s.name}  {distance}  {s.hours} {status}{extra}\n    {s.address}", file=out)
    return EXIT_OK


def _read_plan_file(path: str) -> dict:
    try:
        data = json.loads(Path(path).read_text("utf-8"))
    except OSError as exc:
        raise ValueError(f"无法读取方案文件 {path}：{exc.strerror or exc}") from None
    except json.JSONDecodeError:
        raise ValueError(f"方案文件 {path} 不是有效的 JSON，请用 plan --save 重新生成") from None
    if not isinstance(data, dict):
        raise ValueError(f"方案文件 {path} 格式不正确，请用 plan --save 重新生成")
    return data


def _load_plan(path: str) -> dict:
    saved = _read_plan_file(path)
    if not saved.get("plans"):
        raise BabyBiteError("方案文件里没有可下单的宝宝餐")
    if saved.get("offline"):
        raise BabyBiteError("这是离线演示方案，不能用于真实下单，请去掉 --offline 重新生成")
    store, top = saved.get("store"), saved["plans"][0]
    if not saved.get("scene") or not isinstance(store, dict) or not store.get("code") \
            or not isinstance(top, dict) or not top.get("orderItem"):
        raise ValueError("方案文件缺少 scene / store.code / plans[0].orderItem，请用 plan --save 重新生成")
    return saved


def cmd_order(args, factory, out) -> int:
    saved = _load_plan(args.plan)
    scene = get_scene(saved["scene"])
    store, top = saved["store"], saved["plans"][0]
    base = store_args(scene, store["code"], store.get("beCode"), saved.get("reservationDate"))
    items = [top["orderItem"]]
    client = factory(False)
    data = client.call_tool("calculate-price", dict(base, items=items)).get("data") or {}
    price = data.get("price")
    print(f"门店：{store['name']}；餐品：{top['name']} × {top['quantity']}", file=out)
    print(f"实时核价：¥{price / 100:.2f}" if isinstance(price, (int, float)) else "实时核价：未返回金额", file=out)
    print("线上去料：" + ("、".join(top.get("removed") or []) or "无"), file=out)
    if not args.confirm:
        print("未加 --confirm，仅算价不下单。", file=out)
        return EXIT_OK
    order_args = dict(base, items=items)
    if scene.needs_take_way:
        codes = [t.get("code") for t in data.get("takeWayList") or [] if t.get("code")]
        if args.take_way and args.take_way not in codes:
            raise ValueError(f"--take-way 需为：{'、'.join(codes)}")
        take_way = args.take_way or (codes[0] if codes else None)
        if not take_way:
            raise BabyBiteError("算价结果没有返回取餐方式，已中止下单")
        order_args["takeWayCode"] = take_way
    if scene.needs_address:
        if not saved.get("addressId"):
            raise BabyBiteError("方案缺少 addressId，无法外送下单")
        order_args["addressId"] = saved["addressId"]
        if saved.get("remark"):
            order_args["remark"] = saved["remark"]
    created = client.call_tool("create-order", order_args)
    print("已创建订单，请在支付链接或麦当劳 App 中完成支付：", file=out)
    print(json.dumps(created.get("data"), ensure_ascii=False, indent=2), file=out)
    return EXIT_OK


def cmd_verify(args, factory, out) -> int:
    saved = _read_plan_file(args.plan) if args.plan else None
    payload = factory(False).call_tool("query-order", {"orderId": args.order_id})
    text = json.dumps(payload.get("data"), ensure_ascii=False)
    print(text if len(text) <= VERIFY_PRINT_LIMIT else text[:VERIFY_PRINT_LIMIT] + "…", file=out)
    if saved is not None:
        removed = (saved.get("plans") or [{}])[0].get("removed") or []
        found = [name for name in removed if name in text]
        missing = [name for name in removed if name not in text]
        print(f"订单详情中出现的特制项：{'、'.join(found) or '无'}", file=out)
        if missing:
            print(f"订单详情中未出现：{'、'.join(missing)}（接口可能不回显特制，请以小票为准）", file=out)
    return EXIT_OK


def cmd_cancel(args, factory, out) -> int:
    factory(False).call_tool("cancel-order", {"orderId": args.order_id, "cancelReasonCode": str(args.reason)})
    print(f"订单 {args.order_id} 已提交取消。", file=out)
    return EXIT_OK


COMMANDS = {"plan": cmd_plan, "stores": cmd_stores, "order": cmd_order, "verify": cmd_verify, "cancel": cmd_cancel,
            "addresses": cmd_addresses}


def main(argv=None, client_factory: Optional[Callable] = None, out=None) -> int:
    out = out or sys.stdout
    args = build_parser().parse_args(argv)
    factory = client_factory or (lambda offline: client_from_env(offline=offline))
    try:
        return COMMANDS[args.command](args, factory, out)
    except AuthError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return EXIT_AUTH
    except McdBusinessError as exc:
        hint = CLOSED_HINT if str(exc.code) == "600057" else ""
        print(f"错误：{exc}{hint}", file=sys.stderr)
        return EXIT_BUSINESS
    except ValueError as exc:
        print(f"参数错误：{exc}", file=sys.stderr)
        return EXIT_USAGE
    except BabyBiteError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return EXIT_ERROR
    except OSError as exc:
        print(f"错误：文件读写失败：{exc}", file=sys.stderr)
        return EXIT_ERROR
