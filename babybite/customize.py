"""宝宝特制：rounds 换搭配 + modification 去料，生成下单入参（规则见 docs/design.md 3.3、4.2、4.3）。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .age_rules import kid_item_verdict
from .menu import Choice, MealDetail, Round

REMOVE_KEYWORDS = ("酱", "吉士", "芝士", "奶酪", "酸黄瓜", "洋葱", "芥末", "沙拉", "黑椒", "胡椒", "辣", "培根")
CHEESE_WORDS = ("吉士", "芝士", "奶酪")
KEEP_CHEESE_FROM_MONTHS = 48
DRINK_ORDER = ("纯牛奶", "牛奶", "纯悦", "苹果汁")
SNACK_ORDER = ("玉米杯", "苹果片")
PATTY_WORDS = ("汉堡包", "吉士汉堡", "牛堡", "巨无霸", "牛肉")
FRIES_WORD = "薯条"


@dataclass(frozen=True)
class CustomizedLine:
    round_id: Optional[str]
    round_name: str
    code: str
    name: str
    quantity: int
    modification: tuple  # 下单用的特制 values（dict）
    removed: tuple  # 线上已去掉的配料名
    swapped_from: Optional[str]  # 被替换掉的默认选项名


@dataclass(frozen=True)
class CustomizedItem:
    product_code: str
    name: str
    quantity: int
    lines: tuple
    salt_requests: tuple  # 线上做不到、需要请店员帮忙的诉求

    @property
    def removed_all(self) -> tuple:
        seen = []
        for line in self.lines:
            for name in line.removed:
                if name not in seen:
                    seen.append(name)
        return tuple(seen)


def should_remove(ingredient: str, age_months: int, keep: tuple = ()) -> bool:
    if any(k and k in ingredient for k in keep):
        return False
    if age_months >= KEEP_CHEESE_FROM_MONTHS and any(w in ingredient for w in CHEESE_WORDS):
        return False
    return any(k in ingredient for k in REMOVE_KEYWORDS)


def modification_payload(groups: tuple, age_months: int, keep: tuple = ()):
    """按官方 key 规则生成特制 values：开关型组内只要有一项要去掉，整组全部传入。"""
    values, removed = [], []
    for group in groups:
        if not group.toggleable:
            continue
        decisions = [(v, should_remove(v.name, age_months, keep)) for v in group.values]
        if not any(flag for _, flag in decisions):
            continue
        for value, flag in decisions:
            if flag:
                values.append({"code": value.code, "key": value.unselected_key, "quantity": 0})
                removed.append(value.name)
            else:
                values.append({"code": value.code, "key": value.selected_key, "quantity": value.selected_quantity})
    return values, removed


def _rank(name: str, order: tuple) -> Optional[int]:
    for i, keyword in enumerate(order):
        if keyword in name:
            return i
    return None


def pick_choice(round_: Round, age_months: int, allergies: tuple = ()) -> Choice:
    """饮料轮优先牛奶/水，小食轮优先玉米杯/苹果片；其余取默认项。"""
    allowed = [c for c in round_.choices if kid_item_verdict(c.name, age_months, allergies).allowed]
    pool = allowed or list(round_.choices)
    for order in (DRINK_ORDER, SNACK_ORDER):
        ranked = [(rank, i, c) for i, c in enumerate(pool) for rank in [_rank(c.name, order)] if rank is not None]
        if ranked:
            return min(ranked, key=lambda x: (x[0], x[1]))[2]
    defaults = [c for c in pool if c.is_default]
    return (defaults or pool)[0]


def customize_meal(detail: MealDetail, age_months: int, allergies: tuple = (), keep: tuple = (),
                   quantity: int = 1) -> CustomizedItem:
    lines = []
    if detail.rounds:
        for round_ in detail.rounds:
            choice = pick_choice(round_, age_months, allergies)
            values, removed = modification_payload(choice.mod_groups, age_months, keep)
            default = next((c for c in round_.choices if c.is_default), None)
            swapped = default.name if default is not None and default.code != choice.code else None
            lines.append(CustomizedLine(round_.id, round_.name, choice.code, choice.name, round_.quantity,
                                        tuple(values), tuple(removed), swapped))
    else:
        values, removed = modification_payload(detail.mod_groups, age_months, keep)
        lines.append(CustomizedLine(None, detail.name, detail.code, detail.name, 1,
                                    tuple(values), tuple(removed), None))
    names = " ".join(line.name for line in lines)
    salt = []
    if any(word in names for word in PATTY_WORDS):
        salt.append("牛肉饼不撒盐")
    if FRIES_WORD in names:
        salt.append("薯条不加盐")
    return CustomizedItem(detail.code, detail.name, max(1, quantity), tuple(lines), tuple(salt))


def _combo(line: CustomizedLine) -> dict:
    entry = {"code": line.code, "quantity": line.quantity}
    if line.modification:
        entry["modification"] = {"values": [dict(v) for v in line.modification]}
    return entry


def to_order_item(item: CustomizedItem) -> dict:
    """生成 calculate-price / create-order 的 items[] 元素（结构见 docs/design.md 3.3）。"""
    out = {"productCode": item.product_code, "quantity": item.quantity}
    round_lines = [line for line in item.lines if line.round_id is not None]
    if round_lines:
        out["roundList"] = [{"round": line.round_id, "comboItemList": [_combo(line)]} for line in round_lines]
    elif item.lines and item.lines[0].modification:
        out["modification"] = {"values": [dict(v) for v in item.lines[0].modification]}
    return out
