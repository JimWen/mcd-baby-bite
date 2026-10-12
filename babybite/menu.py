"""门店、菜单、套餐详情的结构化解析（字段见 docs/design.md 3.2）。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Store:
    code: str
    name: str
    address: str
    distance_m: Optional[int]
    open_now: bool
    hours: str
    be_code: Optional[str]
    reservation: bool
    reservation_options: tuple  # ((date, today, text), ...)


@dataclass(frozen=True)
class MenuItem:
    code: str
    name: str
    price_yuan: Optional[float]
    category: str
    image: Optional[str] = None


@dataclass(frozen=True)
class ModValue:
    code: str
    name: str
    selected_key: str
    unselected_key: Optional[str]
    selected_quantity: int


@dataclass(frozen=True)
class ModGroup:
    values: tuple

    @property
    def toggleable(self) -> bool:
        """开关型特制组（每项都有 unselectedKey），例如酱料；冰量这类单选组为 False。"""
        return bool(self.values) and all(v.unselected_key for v in self.values)


@dataclass(frozen=True)
class Choice:
    code: str
    name: str
    is_default: bool
    mod_groups: tuple


@dataclass(frozen=True)
class Round:
    id: str
    name: str
    quantity: int
    choices: tuple


@dataclass(frozen=True)
class MealDetail:
    code: str
    name: str
    rounds: tuple
    mod_groups: tuple
    image: str = ""


def _clean(text) -> str:
    return str(text or "").replace("\n", "").strip()


def _price(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_stores(payload: dict) -> list:
    stores = []
    for raw in payload.get("data") or []:
        options = tuple(
            (o.get("date", ""), bool(o.get("today")), o.get("reservationOptionText", ""))
            for o in raw.get("reservationTimeOptions") or []
        )
        distance = raw.get("distance")
        stores.append(Store(
            code=str(raw.get("storeCode", "")),
            name=_clean(raw.get("storeName")),
            address=_clean(raw.get("address")),
            distance_m=int(distance) if isinstance(distance, (int, float)) else None,
            open_now=bool(raw.get("businessStatus")),
            hours=f"{raw.get('businessStartTime', '')}-{raw.get('businessEndTime', '')}",
            be_code=raw.get("beCode") or None,
            reservation=bool(raw.get("reservation")),
            reservation_options=options,
        ))
    return stores


def parse_menu(payload: dict) -> list:
    """按分类顺序展开菜单，同一餐品出现在多个分类时只保留第一次。"""
    data = payload.get("data") or {}
    meals = data.get("meals") or {}
    items, seen = [], set()
    for category in data.get("categories") or []:
        cat_name = _clean(category.get("name"))
        for entry in category.get("meals") or []:
            code = str(entry.get("code", ""))
            if code in seen or code not in meals:
                continue
            seen.add(code)
            meal = meals[code]
            items.append(MenuItem(code, _clean(meal.get("name")), _price(meal.get("currentPrice")),
                                  cat_name, meal.get("image")))
    for code, meal in meals.items():  # 未归入任何分类的餐品
        if code not in seen:
            seen.add(code)
            items.append(MenuItem(code, _clean(meal.get("name")), _price(meal.get("currentPrice")),
                                  "", meal.get("image")))
    return items


def _mod_groups(modification) -> tuple:
    groups = []
    for item in (modification or {}).get("items") or []:
        values = tuple(
            ModValue(
                code=str(v.get("code", "")),
                name=_clean(v.get("name")),
                selected_key=str(v.get("selectedKey", "")),
                unselected_key=v.get("unselectedKey") or None,
                selected_quantity=int(v.get("selectedQuantity") or 0),
            )
            for v in item.get("values") or []
        )
        groups.append(ModGroup(values))
    return tuple(groups)


def parse_meal_detail(payload: dict) -> MealDetail:
    data = payload.get("data") or {}
    rounds = tuple(
        Round(
            id=str(r.get("id", "")),
            name=_clean(r.get("name")),
            quantity=int(r.get("quantity") or 1),
            choices=tuple(
                Choice(str(c.get("code", "")), _clean(c.get("name")), c.get("isDefault") == 1,
                       _mod_groups(c.get("modification")))
                for c in r.get("choices") or []
            ),
        )
        for r in data.get("rounds") or []
    )
    return MealDetail(str(data.get("code", "")), _clean(data.get("name")), rounds,
                      _mod_groups(data.get("modification")), data.get("image") or "")
