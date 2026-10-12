"""把 PlanResult 渲染为终端 Markdown、JSON、HTML 卡片，以及店员话术卡和外送备注。"""
from __future__ import annotations

import html
import json
from typing import Optional

from .activities import toy_of
from .age_rules import GRAMS_SALT_TO_MG_SODIUM
from .customize import CustomizedItem, to_order_item
from .planner import KidPlan, PlanResult

REMARK_MAX = 50
BANNED_PHRASES = ("肯德基", "汉堡王", "KFC", "垃圾食品", "不健康", "最健康", "营养均衡", "绝对安全")
TIPS = (
    "偶尔吃，吃得明白：外食不宜频繁，回家后搭配蔬果和白水。",
    "拿到餐先尝一口温度和咸淡，再分给宝宝。",
    "3 岁以下把汉堡、鸡块撕成小块，全程看护进食。",
)
DISCLAIMER = (
    "营养数据来自麦当劳 MCP 官方实时接口，为默认配方整份数值；线上去料后实际钠更低，但官方未提供分项数据，"
    "本工具只按“不高于”计算。过敏原为按名称的提示，请以门店信息为准。本项目为参赛作品，非麦当劳官方产品，"
    "不构成医疗或营养建议；餐品、价格与供应以麦当劳官方渠道为准。"
)
OFFLINE_NOTICE = "离线演示：数据为 2026-10-12 用真实 Token 录制的上海黄浦华旭国际大厦餐厅午餐时段结果。"
NO_PLAN_TEXT = "这家店当前菜单里没有能放进本餐钠预算的组合，可以换个门店或时间再试。"
PLAY_HEADING = "饭后遛娃（高德，门店周边 2 公里）"
PLAY_REMINDER = "出发前请留意开放时间与天气"


def age_label(age_months: int) -> str:
    if age_months < 12:
        return f"{age_months} 个月"
    years, months = divmod(age_months, 12)
    return f"{years} 岁" + (f" {months} 个月" if months else "")


def staff_script(item: CustomizedItem, age_months: int) -> str:
    text = f"您好，这份{item.name}是给 {age_label(age_months)}宝宝吃的。"
    if not item.removed_all and not item.salt_requests:
        return text + "按正常出餐即可，谢谢您！"
    if item.removed_all:
        text += f"线上已经去掉：{'、'.join(item.removed_all)}。"
    if item.salt_requests:
        text += f"如果方便的话，麻烦{'、'.join(item.salt_requests)}。做不到也没关系，"
    return text + "谢谢您！"


def delivery_remark(item: CustomizedItem) -> str:
    """外送订单备注（≤50 字）；没有需要店员帮忙的诉求时返回空串。"""
    if not item.salt_requests:
        return ""
    return ("宝宝餐：" + "，".join(item.salt_requests) + "，谢谢")[:REMARK_MAX]


def _mg(value: Optional[float]) -> str:
    return "无官方数据" if value is None else f"{value:.0f}mg"


def _handling(line) -> str:
    parts = []
    if line.removed:
        parts.append("线上已去：" + "、".join(line.removed))
    if line.swapped_from:
        parts.append(f"已换成{line.name}（原：{line.swapped_from}）")
    return "；".join(parts) or "-"


def _kid_mg(line, comp) -> str:
    if comp.kid_sodium_mg is None or comp.portion == 0:
        return "-"
    return f"{'≤' if line.removed else ''}{comp.kid_sodium_mg:.0f}mg"


def _total_prefix(plan: KidPlan) -> str:
    """有去料或减盐诉求时实际钠低于官方数值，写"≤"；否则按官方数值写"约"。"""
    return "≤" if plan.item.removed_all or plan.item.salt_requests else "约 "


def _rows(plan: KidPlan):
    """(子项名, 处理, 官方钠, 份量, 宝宝摄入钠)，跳过玩具等不计入项。"""
    for line, comp in zip(plan.item.lines, plan.components):
        if comp.role != "skip":
            yield line.name, _handling(line), _mg(comp.sodium_mg), comp.note, _kid_mg(line, comp)


def _price_text(plan: KidPlan, price_cents: Optional[int]) -> str:
    parts = []
    if plan.menu_price_yuan is not None:
        parts.append(f"菜单价 ¥{plan.menu_price_yuan:g}")
    if price_cents is not None:
        parts.append(f"实时核价 ¥{price_cents / 100:.2f}")
    return " / ".join(parts)


def _summary(plan: KidPlan) -> str:
    return (f"本餐宝宝钠合计 {_total_prefix(plan)}{plan.kid_sodium_mg:.0f}mg，约占本餐预算 {plan.meal_pct}%、"
            f"全天上限 {plan.day_pct}%。")


def _budget_text(result: PlanResult) -> str:
    b = result.budget
    return (f"本餐 {b.meal_sodium_mg}mg（全天上限 {b.daily_sodium_mg}mg = 食盐 {b.band.daily_salt_g:g}g × "
            f"{GRAMS_SALT_TO_MG_SODIUM}，按 {round(b.meal_share * 100)}% 分到这一餐；依据：{b.band.source}）")


def _alt_text(plan: KidPlan) -> str:
    mains = "、".join(f"{c.name} {c.note}" for c in plan.components if c.role == "main")
    return f"{plan.item.name}：{mains}；宝宝钠 {_total_prefix(plan)}{plan.kid_sodium_mg:.0f}mg（本餐预算 {plan.meal_pct}%）"


def _activity_lines(result: PlanResult) -> list:
    toy = toy_of(result.plans[0].item) if result.plans else None
    lines = [f"随餐玩具：{toy}（开心乐园餐附赠，以门店实际发放为准）"] if toy else []
    return lines + [f"亲子活动：{campaign.title}——{campaign.summary}" for campaign in result.campaigns]


def _play_lines(result: PlanResult) -> list:
    if not result.play_spots:
        return []
    return [f"{spot.name}（{spot.kind}）：步行约 {spot.walk_minutes} 分钟（{spot.walk_meters} 米）"
            for spot in result.play_spots] + [PLAY_REMINDER]


def render_markdown(result: PlanResult) -> str:
    out = ["# 小小麦门 · 带娃吃麦定制单", ""]
    if result.offline:
        out += [f"> {OFFLINE_NOTICE}", ""]
    out += [f"> {notice}" for notice in result.notices] + ([""] if result.notices else [])
    store = result.store
    where = [part for part in (store.address,
                               f"距离 {store.distance_m}m" if store.distance_m is not None else "",
                               f"营业 {store.hours}" if store.hours.strip("- ") else "") if part]
    when = f"预约 {result.reservation_date}" if result.reservation_date else "现在"
    out += [
        f"- 门店：{store.name}" + (f"（{'，'.join(where)}）" if where else ""),
        f"- 方式：{result.scene.label}；时间：{when}",
        f"- 宝宝：{age_label(result.age_months)} × {result.kids}；大人 × {result.adults}",
        f"- 钠预算：{_budget_text(result)}",
        "",
    ]
    if not result.plans:
        out += ["## 暂无合适的宝宝餐", "", NO_PLAN_TEXT, ""]
    else:
        top = result.plans[0]
        out += [f"## 主推：{top.item.name} × {top.item.quantity}", ""]
        price = _price_text(top, result.price_cents)
        if price:
            out += [price, ""]
        out += ["| 组成 | 处理 | 官方钠 | 宝宝份量 | 宝宝摄入钠 |", "|---|---|---|---|---|"]
        out += [f"| {' | '.join(row)} |" for row in _rows(top)]
        out += ["", _summary(top), "", "### 店员话术卡", "", "> " + staff_script(top.item, result.age_months), ""]
        if result.scene.key == "delivery" and delivery_remark(top.item):
            out += [f"外送订单备注（下单时自动填写）：{delivery_remark(top.item)}", ""]
        if len(result.plans) > 1:
            out += ["## 备选", ""] + [f"- {_alt_text(p)}" for p in result.plans[1:]] + [""]
    if result.excluded:
        out += ["## 未推荐", ""] + [f"- {name}：{reason}" for name, reason in result.excluded] + [""]
    for heading, lines in (("玩具与亲子活动", _activity_lines(result)), (PLAY_HEADING, _play_lines(result))):
        if lines:
            out += [f"## {heading}", ""] + [f"- {line}" for line in lines] + [""]
    if result.adult_suggestions:
        out += ["## 大人餐参考", ""]
        out += [f"- {m.name}" + (f" ¥{m.price_yuan:g}" if m.price_yuan is not None else "")
                for m in result.adult_suggestions]
        out.append("")
    out += ["## 温馨提示", ""] + [f"- {tip}" for tip in TIPS] + [""]
    out += ["## 说明", "", DISCLAIMER, ""]
    return "\n".join(out)


def plan_to_dict(result: PlanResult) -> dict:
    def plan_dict(plan: KidPlan) -> dict:
        return {
            "name": plan.item.name,
            "productCode": plan.item.product_code,
            "quantity": plan.item.quantity,
            "menuPriceYuan": plan.menu_price_yuan,
            "kidSodiumMg": round(plan.kid_sodium_mg, 1),
            "mealBudgetPct": plan.meal_pct,
            "dayLimitPct": plan.day_pct,
            "removed": list(plan.item.removed_all),
            "saltRequests": list(plan.item.salt_requests),
            "components": [{"name": c.name, "role": c.role, "sodiumMg": c.sodium_mg,
                            "portion": round(c.portion, 3), "note": c.note} for c in plan.components],
            "unknownNutrition": list(plan.unknown_nutrition),
            "staffScript": staff_script(plan.item, result.age_months),
            "orderItem": to_order_item(plan.item),
        }

    store = result.store
    remark = delivery_remark(result.plans[0].item) if result.plans and result.scene.key == "delivery" else ""
    return {
        "version": 1,
        "ageMonths": result.age_months,
        "kids": result.kids,
        "adults": result.adults,
        "scene": result.scene.key,
        "store": {"code": store.code, "name": store.name, "address": store.address, "beCode": store.be_code},
        "addressId": result.address_id,
        "reservationDate": result.reservation_date,
        "budget": {"dailySodiumMg": result.budget.daily_sodium_mg, "mealSodiumMg": result.budget.meal_sodium_mg,
                   "dailySaltG": result.budget.band.daily_salt_g, "source": result.budget.band.source},
        "plans": [plan_dict(p) for p in result.plans],
        "excluded": [{"name": n, "reason": r} for n, r in result.excluded],
        "toy": toy_of(result.plans[0].item) if result.plans else None,
        "campaigns": [{"date": c.date, "title": c.title, "summary": c.summary} for c in result.campaigns],
        "playSpots": [{"name": s.name, "kind": s.kind, "walkMinutes": s.walk_minutes,
                       "walkMeters": s.walk_meters, "address": s.address} for s in result.play_spots],
        "priceCents": result.price_cents,
        "remark": remark,
        "offline": result.offline,
        "notices": list(result.notices),
    }


def render_json(result: PlanResult) -> str:
    return json.dumps(plan_to_dict(result), ensure_ascii=False, indent=2)


_CSS = """
body{margin:0;background:#fff8e7;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;color:#2b2b2b}
.wrap{max-width:720px;margin:0 auto;padding:24px}
.hero{background:#da291c;color:#fff;border-radius:20px;padding:20px 24px}
.hero h1{margin:0 0 8px;font-size:24px}.hero p{margin:3px 0}
.card{background:#fff;border-radius:16px;padding:18px 20px;margin-top:16px;box-shadow:0 2px 10px rgba(0,0,0,.06)}
.card h2{margin:0 0 10px;font-size:18px}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{padding:8px 6px;border-bottom:1px solid #f1e6c8;text-align:left;vertical-align:top}
.bar{height:12px;background:#f6e7b5;border-radius:6px;overflow:hidden;margin:10px 0}.bar i{display:block;height:100%;background:#ffbc0d}
.script{background:#ffbc0d;border-radius:16px;padding:20px;font-size:20px;line-height:1.6;font-weight:600}
.muted{color:#7a6f5a;font-size:13px;line-height:1.6}ul{padding-left:20px;margin:0}
"""


def render_html(result: PlanResult) -> str:
    e = html.escape
    store = result.store
    parts = [
        "<!doctype html>",
        '<html lang="zh-CN"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        "<title>小小麦门 · 带娃吃麦定制单</title>",
        f"<style>{_CSS}</style></head><body><div class=\"wrap\">",
        '<div class="hero"><h1>小小麦门 · 带娃吃麦定制单</h1>',
        f"<p>{e(store.name)}</p>",
        f"<p>宝宝 {e(age_label(result.age_months))} × {result.kids} · {e(result.scene.label)}</p>",
        f"<p>本餐钠预算 {result.budget.meal_sodium_mg}mg</p></div>",
    ]
    if result.offline:
        parts.append(f'<p class="muted">{e(OFFLINE_NOTICE)}</p>')
    if not result.plans:
        parts.append(f'<div class="card"><h2>暂无合适的宝宝餐</h2><p>{e(NO_PLAN_TEXT)}</p></div>')
    else:
        top = result.plans[0]
        rows = "".join("<tr>" + "".join(f"<td>{e(cell)}</td>" for cell in row) + "</tr>" for row in _rows(top))
        width = max(0, min(top.meal_pct, 100))
        price = _price_text(top, result.price_cents)
        parts += [
            f'<div class="card"><h2>主推：{e(top.item.name)} × {top.item.quantity}</h2>',
            f'<p class="muted">{e(price)}</p>' if price else "",
            "<table><tr><th>组成</th><th>处理</th><th>官方钠</th><th>宝宝份量</th><th>宝宝摄入钠</th></tr>",
            rows, "</table>",
            f'<div class="bar"><i style="width:{width}%"></i></div><p>{e(_summary(top))}</p></div>',
            f'<div class="card"><h2>店员话术卡</h2><div class="script">{e(staff_script(top.item, result.age_months))}</div></div>',
        ]
        if len(result.plans) > 1:
            items = "".join(f"<li>{e(_alt_text(p))}</li>" for p in result.plans[1:])
            parts.append(f'<div class="card"><h2>备选</h2><ul>{items}</ul></div>')
    for heading, lines in (("玩具与亲子活动", _activity_lines(result)), (PLAY_HEADING, _play_lines(result))):
        if lines:
            items = "".join(f"<li>{e(line)}</li>" for line in lines)
            parts.append(f'<div class="card"><h2>{e(heading)}</h2><ul>{items}</ul></div>')
    tips = "".join(f"<li>{e(t)}</li>" for t in TIPS)
    parts += [
        f'<div class="card"><h2>温馨提示</h2><ul>{tips}</ul></div>',
        f'<p class="muted">{e(_budget_text(result))}</p>',
        f'<p class="muted">{e(DISCLAIMER)}</p>',
        "</div></body></html>",
    ]
    return "\n".join(p for p in parts if p)
