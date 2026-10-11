"""年龄档位、钠预算与"宝宝能不能吃"的规则。常量出处见 docs/design.md 第 4 节。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

GRAMS_SALT_TO_MG_SODIUM = 393  # 1g 食盐约含 393mg 钠
SOURCE_SALT = "中国营养学会《家庭减盐行为指南》T/CNSS 022-2023"
SOURCE_INFANT = "《中国居民膳食指南（2022）》7～24 月龄婴幼儿平衡膳食宝塔"
MAX_AGE_MONTHS = 216
MIN_MEAL_SHARE, MAX_MEAL_SHARE = 0.2, 0.5


@dataclass(frozen=True)
class AgeBand:
    min_months: int
    max_months: Optional[int]  # 不含
    label: str
    daily_salt_g: Optional[float]
    source: str


BANDS = (
    AgeBand(0, 12, "12 月龄以下", None, SOURCE_INFANT),
    AgeBand(12, 24, "1-2 岁", 1.5, SOURCE_INFANT),
    AgeBand(24, 48, "2-3 岁", 2.0, SOURCE_SALT),
    AgeBand(48, 84, "4-6 岁", 3.0, SOURCE_SALT),
    AgeBand(84, 132, "7-10 岁", 4.0, SOURCE_SALT),
    AgeBand(132, None, "11 岁及以上", 5.0, SOURCE_SALT),
)

INFANT_ADVICE = (
    "12 月龄以下的宝宝不建议外食：辅食应单独制作、保持原味、不额外加盐"
    f"（依据：{SOURCE_INFANT}）。带宝宝出门可以自带辅食，大人照常点餐即可。"
)


@dataclass(frozen=True)
class SodiumBudget:
    band: AgeBand
    daily_sodium_mg: int
    meal_sodium_mg: int
    meal_share: float


def band_for(age_months: int) -> AgeBand:
    if isinstance(age_months, bool) or not isinstance(age_months, int) \
            or not 0 <= age_months <= MAX_AGE_MONTHS:
        raise ValueError(f"月龄需为 0 到 {MAX_AGE_MONTHS} 之间的整数")
    for band in BANDS:
        if age_months >= band.min_months and (band.max_months is None or age_months < band.max_months):
            return band
    raise ValueError("月龄超出范围")  # pragma: no cover


def sodium_budget(age_months: int, meal_share: float = 1 / 3) -> Optional[SodiumBudget]:
    """返回钠预算；12 月龄以下返回 None（不推荐外食）。"""
    if not MIN_MEAL_SHARE <= meal_share <= MAX_MEAL_SHARE:
        raise ValueError(f"单餐占比需在 {MIN_MEAL_SHARE} 到 {MAX_MEAL_SHARE} 之间")
    band = band_for(age_months)
    if band.daily_salt_g is None:
        return None
    daily = round(band.daily_salt_g * GRAMS_SALT_TO_MG_SODIUM)
    return SodiumBudget(band, daily, round(daily * meal_share), meal_share)


EXCLUDE_ALL = ("咖啡", "拿铁", "奶铁", "美式", "摩卡", "卡布奇诺", "浓缩", "黑巧", "可乐", "雪碧",
               "芬达", "汽水", "气泡", "怡泉", "红茶", "柠", "橙", "辣")
EXCLUDE_UNDER_36 = ("冰淇淋", "新地", "麦旋风", "圆筒", "派", "奶昔", "果汁", "粥")
PREFERRED = ("玉米杯", "苹果片", "纯牛奶", "纯悦")
ALLERGEN_KEYWORDS = {
    "鱼类": ("鱼", "鳕"),
    "乳制品": ("吉士", "芝士", "奶酪", "牛奶", "奶"),
    "蛋类": ("蛋",),
    "小麦麸质": ("堡", "面包", "派", "麦满分", "卷", "麦乐鸡", "鸡块"),
}
ALLERGY_ALIASES = {
    "鱼": "鱼类", "鱼类": "鱼类", "海鲜": "鱼类",
    "奶": "乳制品", "牛奶": "乳制品", "乳": "乳制品", "乳制品": "乳制品",
    "蛋": "蛋类", "鸡蛋": "蛋类", "蛋类": "蛋类",
    "麸质": "小麦麸质", "小麦": "小麦麸质", "小麦麸质": "小麦麸质",
}


def parse_allergies(text: Optional[str]) -> tuple:
    if not text:
        return ()
    out = []
    for token in re.split(r"[,，、;；\s]+", text.strip()):
        if not token:
            continue
        category = ALLERGY_ALIASES.get(token)
        if category is None:
            raise ValueError(f"不认识的过敏原：{token}，可选：鱼、奶、蛋、麸质")
        if category not in out:
            out.append(category)
    return tuple(out)


def possible_allergens(name: str) -> tuple:
    """按名称关键词判断"可能含"的过敏原类别（官方未提供过敏原数据）。"""
    return tuple(cat for cat, words in ALLERGEN_KEYWORDS.items() if any(w in name for w in words))


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    reason: Optional[str]
    preferred: bool
    allergens: tuple


def kid_item_verdict(name: str, age_months: int, allergies: tuple = ()) -> Verdict:
    allergens = possible_allergens(name)
    preferred = any(word in name for word in PREFERRED)
    for word in EXCLUDE_ALL:
        if word in name:
            return Verdict(False, f"含“{word}”，不适合宝宝", False, allergens)
    if age_months < 36:
        for word in EXCLUDE_UNDER_36:
            if word in name:
                return Verdict(False, f"3 岁以下不建议：{word}", False, allergens)
    hit = [a for a in allergens if a in allergies]
    if hit:
        return Verdict(False, f"可能含{'、'.join(hit)}", preferred, allergens)
    return Verdict(True, None, preferred, allergens)
