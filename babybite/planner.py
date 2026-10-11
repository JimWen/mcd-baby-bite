"""在门店真实菜单中挑选宝宝餐并计算份量（规则见 docs/design.md 第 5 节）。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .age_rules import SodiumBudget, kid_item_verdict, possible_allergens
from .customize import CustomizedItem, customize_meal
from .menu import Store
from .nutrition import NutritionIndex
from .scenes import Scene

PORTIONS = (1.0, 0.75, 0.5, 1 / 3, 0.25)
PORTION_LABELS = {1.0: "整份", 0.75: "3/4 份", 0.5: "1/2 份", 1 / 3: "1/3 份", 0.25: "1/4 份"}
SIDE_WORDS = ("玉米杯", "苹果片", "纯牛奶", "牛奶", "纯悦", "苹果汁")
SKIP_WORDS = ("玩具",)
KID_MEAL_WORD = "开心乐园"
SINGLE_MAIN_WORDS = ("汉堡包", "吉士汉堡", "鱼排堡", "麦香鱼", "麦乐鸡", "板烧鸡腿堡")
COMBO_WORDS = ("套餐", "件套", "亲子", "双人", "随心", "精选")
MAX_CANDIDATES = 4
MAX_PLANS = 3
ADULT_CATEGORY_WORDS = ("精选单人餐", "人气热卖")
FRIES_NOTE = "建议大人吃，宝宝最多尝 2-3 根"
UNKNOWN_NOTE = "无官方营养数据，未计入钠合计，建议先给 1/2 份"


def floor_portion(ratio: float) -> Optional[float]:
    """向下取到最近的份量档位；不足 1/4 返回 None。"""
    for portion in PORTIONS:
        if ratio >= portion - 1e-9:
            return portion
    return None


def role_of(name: str) -> str:
    if any(w in name for w in SKIP_WORDS):
        return "skip"
    if "薯条" in name:
        return "fries"
    if any(w in name for w in SIDE_WORDS):
        return "side"
    return "main"


def _portion_note(name: str, portion: float) -> str:
    label = PORTION_LABELS[portion]
    match = re.search(r"(\d+)\s*块", name)
    if match and portion < 1.0:
        pieces = max(1, round(int(match.group(1)) * portion))
        return f"{label}（约 {pieces} 块）"
    return label


@dataclass(frozen=True)
class Component:
    name: str
    role: str  # main / side / fries / skip
    sodium_mg: Optional[float]
    portion: float
    note: str

    @property
    def kid_sodium_mg(self) -> Optional[float]:
        return None if self.sodium_mg is None else self.sodium_mg * self.portion


@dataclass(frozen=True)
class KidPlan:
    item: CustomizedItem
    menu_price_yuan: Optional[float]
    components: tuple  # 与 item.lines 一一对应
    kid_sodium_mg: float
    budget: SodiumBudget
    unknown_nutrition: tuple
    score: float

    @property
    def meal_pct(self) -> int:
        return round(self.kid_sodium_mg / self.budget.meal_sodium_mg * 100)

    @property
    def day_pct(self) -> int:
        return round(self.kid_sodium_mg / self.budget.daily_sodium_mg * 100)


def plan_for_item(item: CustomizedItem, index: NutritionIndex, budget: SodiumBudget,
                  menu_price_yuan: Optional[float] = None) -> Optional[KidPlan]:
    """配菜饮品整份计入，剩余预算平均分给主食；任一主食不足 1/4 份时返回 None。"""
    rows = []
    for line in item.lines:
        role = role_of(line.name)
        fact = index.lookup(line.name) if role != "skip" else None
        rows.append((line, role, fact.sodium_mg if fact else None))
    unknown = tuple(line.name for line, role, sodium in rows if role != "skip" and sodium is None)
    side_sodium = sum(s for _, role, s in rows if role == "side" and s is not None)
    known_mains = [s for _, role, s in rows if role == "main" and s is not None]
    per_main = (budget.meal_sodium_mg - side_sodium) / len(known_mains) if known_mains else 0.0
    components = []
    for line, role, sodium in rows:
        if role == "side":
            components.append(Component(line.name, role, sodium, 1.0, "整份"))
        elif role == "fries":
            components.append(Component(line.name, role, sodium, 0.0, FRIES_NOTE))
        elif role == "skip":
            components.append(Component(line.name, role, None, 0.0, "不计入"))
        elif sodium is None:
            components.append(Component(line.name, role, None, 0.5, UNKNOWN_NOTE))
        else:
            portion = floor_portion(per_main / sodium) if sodium > 0 else 1.0
            if portion is None:
                return None
            components.append(Component(line.name, role, sodium, portion, _portion_note(line.name, portion)))
    kid_sodium = sum(c.kid_sodium_mg for c in components if c.kid_sodium_mg is not None)
    allergens = {a for line, role, _ in rows if role != "skip" for a in possible_allergens(line.name)}
    score = (1 - kid_sodium / budget.meal_sodium_mg) + (2.0 if KID_MEAL_WORD in item.name else 0.0) \
        - len(unknown) - 0.1 * len(allergens)
    return KidPlan(item, menu_price_yuan, tuple(components), kid_sodium, budget, unknown, score)


def rank_candidates(menu: list, age_months: int, allergies: tuple = ()) -> list:
    """开心乐园餐优先，其次单点主食；最多 MAX_CANDIDATES 个，控制接口调用次数。"""
    kid_meals = [m for m in menu if KID_MEAL_WORD in m.category and not any(w in m.name for w in ("亲子", "双人"))]
    singles = [m for m in menu if any(w in m.name for w in SINGLE_MAIN_WORDS)
               and not any(w in m.name for w in COMBO_WORDS)]
    out, seen = [], set()
    for item in kid_meals + singles:
        if item.code in seen or not kid_item_verdict(item.name, age_months, allergies).allowed:
            continue
        seen.add(item.code)
        out.append(item)
    return out[:MAX_CANDIDATES]


def build_plans(candidates: list, details: dict, index: NutritionIndex, budget: SodiumBudget,
                age_months: int, allergies: tuple = (), keep: tuple = (), kids: int = 1):
    plans, excluded = [], []
    for menu_item in candidates:
        detail = details.get(menu_item.code)
        if detail is None:
            excluded.append((menu_item.name, "未取到套餐详情"))
            continue
        item = customize_meal(detail, age_months, allergies, keep, quantity=kids)
        bad = [line.name for line in item.lines
               if role_of(line.name) != "skip" and not kid_item_verdict(line.name, age_months, allergies).allowed]
        if bad:
            excluded.append((menu_item.name, f"含不适合宝宝的子项：{'、'.join(bad)}"))
            continue
        plan = plan_for_item(item, index, budget, menu_item.price_yuan)
        if plan is None:
            excluded.append((menu_item.name, "即使只吃 1/4 份也会超出本餐钠预算"))
            continue
        plans.append(plan)
    plans.sort(key=lambda p: -p.score)
    return plans[:MAX_PLANS], excluded


def adult_suggestions(menu: list, limit: int = 3) -> list:
    picks = []
    for word in ADULT_CATEGORY_WORDS:
        for item in menu:
            if word in item.category and item not in picks and KID_MEAL_WORD not in item.name:
                picks.append(item)
    return picks[:limit]


@dataclass
class PlanResult:
    age_months: int
    kids: int
    adults: int
    scene: Scene
    store: Store
    reservation_date: Optional[str]
    budget: SodiumBudget
    plans: list
    excluded: list
    adult_suggestions: list
    price_cents: Optional[int] = None
    take_ways: list = field(default_factory=list)
    offline: bool = False
    notices: list = field(default_factory=list)
    address_id: Optional[str] = None
