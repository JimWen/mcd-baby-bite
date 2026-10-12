"""手机竖版卡片（1080×1440）：给店员看的话术卡、按年龄推荐搭配的速查卡。适合存相册或发小红书。"""
from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Optional

from .age_rules import sodium_budget
from .cards import age_label
from .planner import KidPlan, build_plans, rank_candidates

AGE_CARD_AGES = (18, 30, 60)  # 分别代表 1-2 岁、2-3 岁、4-6 岁

_BASE_CSS = """
*{box-sizing:border-box}html,body{margin:0;width:1080px;height:1440px;overflow:hidden}
body{background:#fff8e7;font-family:-apple-system,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;color:#2b2b2b}
.page{width:1080px;height:1440px;padding:64px 72px;display:flex;flex-direction:column}
.tag{align-self:flex-start;background:#da291c;color:#fff;border-radius:999px;padding:10px 28px;font-size:30px;font-weight:700}
h1{font-size:64px;margin:28px 0 12px;line-height:1.25}
.sub{font-size:30px;color:#7a6f5a;margin:0 0 16px}
.foot{margin-top:auto;font-size:24px;color:#7a6f5a;line-height:1.5}
"""
_STAFF_CSS = """
.box{background:#fff;border-radius:32px;padding:36px 40px;margin-top:28px;box-shadow:0 4px 16px rgba(0,0,0,.06)}
.ask{background:#ffbc0d}
.label{font-size:30px;color:#7a6f5a;margin-bottom:12px}.ask .label{color:#5a4300}
.big{font-size:52px;font-weight:800;line-height:1.4;margin:0;padding:0;list-style:none}
.soft{font-size:34px;margin-top:16px;font-weight:600}
"""
_AGE_CSS = """
.row{display:flex;background:#fff;border-radius:28px;margin-top:22px;overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,.06)}
.age{width:230px;background:#da291c;color:#fff;padding:28px 24px;display:flex;flex-direction:column;justify-content:center}
.age b{font-size:44px}.age span{font-size:24px;margin-top:8px}
.info{padding:24px 30px;flex:1}.dish{font-size:38px;font-weight:800;margin-bottom:8px}
.line{font-size:27px;line-height:1.5;color:#4a4a4a}
"""
AGE_CARD_FOOT = ("盐上限依据：中国营养学会《家庭减盐行为指南》T/CNSS 022-2023、《中国居民膳食指南（2022）》。"
                 "营养数据来自麦当劳 MCP 官方接口，去料后实际更低。偶尔吃，吃得明白；不构成营养建议。")


@dataclass(frozen=True)
class AgeRow:
    age_months: int
    band_label: str
    daily_salt_g: float
    meal_sodium_mg: int
    plan: Optional[KidPlan]


def card_candidate_codes(menu: list, ages: tuple = AGE_CARD_AGES, allergies: tuple = ()) -> list:
    codes = []
    for age in ages:
        for item in rank_candidates(menu, age, allergies):
            if item.code not in codes:
                codes.append(item.code)
    return codes


def age_rows(menu: list, details: dict, index, ages: tuple = AGE_CARD_AGES, allergies: tuple = (),
             keep: tuple = ()) -> list:
    rows = []
    for age in ages:
        budget = sodium_budget(age)
        plans, _ = build_plans(rank_candidates(menu, age, allergies), details, index, budget, age, allergies, keep)
        rows.append(AgeRow(age, budget.band.label, budget.band.daily_salt_g, budget.meal_sodium_mg,
                           plans[0] if plans else None))
    return rows


def _page(title: str, css: str, body: str) -> str:
    return ("<!doctype html>\n<html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
            f"<meta name=\"viewport\" content=\"width=1080\"><title>{html.escape(title)}</title>"
            f"<style>{_BASE_CSS}{css}</style></head><body><div class=\"page\">{body}</div></body></html>")


def render_staff_card(item, age_months: int, store_name: str) -> str:
    e = html.escape
    removed_box = (f'<div class="box"><div class="label">线上已经去掉</div>'
                   f'<div class="big">{e("、".join(item.removed_all))}</div></div>') if item.removed_all else ""
    if item.salt_requests:
        asks = "".join(f"<li>{e(s)}</li>" for s in item.salt_requests)
        ask_box = (f'<div class="box ask"><div class="label">如果方便，麻烦您</div><ul class="big">{asks}</ul>'
                   '<div class="soft">做不到也没关系，谢谢您！</div></div>')
    else:
        ask_box = '<div class="box ask"><div class="big">按正常出餐即可，谢谢您！</div></div>'
    body = (
        '<span class="tag">给店员看 · 宝宝餐</span>'
        f"<h1>您好，这份是给<br>{e(age_label(age_months))}宝宝吃的</h1>"
        f'<p class="sub">{e(item.name)} × {item.quantity}</p>'
        + removed_box + ask_box
        + f'<div class="foot">{e(store_name)} · 由 mcd-baby-bite 生成，非麦当劳官方</div>'
    )
    return _page("店员话术卡", _STAFF_CSS, body)


def render_age_card(rows: list, store_name: str, when: Optional[str]) -> str:
    e = html.escape
    blocks = []
    for row in rows:
        if row.plan is None:
            info = '<div class="dish">这家店暂无合适组合</div>'
        else:
            mains = "、".join(f"{c.name} {c.note}" for c in row.plan.components if c.role == "main")
            removed = "、".join(row.plan.item.removed_all) or "无需去料"
            info = (f'<div class="dish">{e(row.plan.item.name)}</div>'
                    f'<div class="line">宝宝吃：{e(mains)}</div>'
                    f'<div class="line">线上去：{e(removed)}</div>'
                    f'<div class="line">本餐宝宝钠 ≤{row.plan.kid_sodium_mg:.0f}mg / 预算 {row.meal_sodium_mg}mg</div>')
        blocks.append(f'<div class="row"><div class="age"><b>{e(row.band_label)}</b>'
                      f'<span>每天盐 ≤{row.daily_salt_g:g}g</span></div><div class="info">{info}</div></div>')
    when_text = f" · {when}" if when else ""
    body = (
        '<span class="tag">宝宝点餐速查卡</span>'
        "<h1>带娃吃麦当劳<br>按年龄这样点</h1>"
        f'<p class="sub">{e(store_name)}{e(when_text)} · 门店实时菜单</p>'
        + "".join(blocks)
        + f'<div class="foot">{e(AGE_CARD_FOOT)}</div>'
    )
    return _page("宝宝点餐速查卡", _AGE_CSS, body)
