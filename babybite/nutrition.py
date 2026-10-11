"""解析 list-nutrition-foods 返回的营养表，并按名称匹配菜单单品。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional

from .errors import BabyBiteError

_PAREN = re.compile(r"[（(][^（()）]*[）)]")
_NOISE = re.compile(r"[\s　™®“”\"'·\-—_]")
REQUIRED_FIELDS = ("productName", "energyKcal", "protein", "fat", "carbohydrate", "sodium", "calcium")
# 套餐子项名 -> 营养表名。只收录用真实数据核对过的别名，不做模糊猜测。
ALIASES = {"鱼排堡": "儿童鱼排堡"}


@dataclass(frozen=True)
class NutritionFact:
    name: str
    energy_kcal: Optional[float]
    protein_g: Optional[float]
    fat_g: Optional[float]
    carb_g: Optional[float]
    sodium_mg: Optional[float]
    calcium_mg: Optional[float]


def normalize_name(name: str) -> str:
    text = _PAREN.sub("", name or "")
    text = text.replace("一袋", "")
    text = _NOISE.sub("", text)
    return text.lower()


def _num(value: str) -> Optional[float]:
    value = value.strip()
    if value in ("", "null", "None", "-"):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_nutrition_table(data: str) -> list:
    """解析形如 `[160]{productName,...}:` 表头 + 逗号分隔行的营养表。"""
    lines = [line for line in (data or "").splitlines() if line.strip()]
    if not lines:
        return []
    match = re.search(r"\{([^}]*)\}", lines[0])
    if not match:
        raise BabyBiteError("营养数据表头格式无法识别")
    fields = [f.strip() for f in match.group(1).split(",")]
    missing = [f for f in REQUIRED_FIELDS if f not in fields]
    if missing:
        raise BabyBiteError(f"营养数据缺少字段：{', '.join(missing)}")
    idx = {f: i for i, f in enumerate(fields)}
    name_at = idx["productName"]
    facts = []
    for line in lines[1:]:
        cols = [c.strip() for c in line.split(",")]
        extra = len(cols) - len(fields)
        if extra < 0:
            continue
        if extra > 0:  # 名称里带逗号：把多出来的列并回名称
            cols = cols[:name_at] + [",".join(cols[name_at:name_at + extra + 1])] + cols[name_at + extra + 1:]
        facts.append(NutritionFact(
            name=cols[name_at],
            energy_kcal=_num(cols[idx["energyKcal"]]),
            protein_g=_num(cols[idx["protein"]]),
            fat_g=_num(cols[idx["fat"]]),
            carb_g=_num(cols[idx["carbohydrate"]]),
            sodium_mg=_num(cols[idx["sodium"]]),
            calcium_mg=_num(cols[idx["calcium"]]),
        ))
    return facts


class NutritionIndex:
    """按规范化名称索引营养数据；重名时保留第一条。"""

    def __init__(self, facts: Iterable[NutritionFact]):
        self._by_key = {}
        for fact in facts:
            self._by_key.setdefault(normalize_name(fact.name), fact)

    def __len__(self) -> int:
        return len(self._by_key)

    def lookup(self, name: str) -> Optional[NutritionFact]:
        key = normalize_name(name)
        if not key:
            return None
        if key in self._by_key:
            return self._by_key[key]
        alias = ALIASES.get(key)
        return self._by_key.get(normalize_name(alias)) if alias else None
