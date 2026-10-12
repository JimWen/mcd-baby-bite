"""从随餐子项和官方活动日历提取玩具与亲子活动。"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

from .customize import CustomizedItem

KID_KEYWORDS = ("开心乐园", "玩具", "儿童", "亲子", "宝宝", "派对", "小朋友", "孩子", "童", "读书会", "体验营")


@dataclass(frozen=True)
class Campaign:
    date: str
    title: str
    summary: str


def clean_text(text: str) -> str:
    """先归一化花体数字，再去掉表情、补充平面字符和首尾空白。"""
    return _strip_symbols(unicodedata.normalize("NFKC", text))


def _strip_symbols(text: str) -> str:
    return "".join(char for char in text
                   if unicodedata.category(char) != "So" and ord(char) <= 0xFFFF
                   and char not in "\ufe0e\ufe0f\u200d\u20e3").strip()


def _clean_title(text: str) -> str:
    """标题保留官方中文标点，其他文字仍按 NFKC 清洗。"""
    parts = re.split(r"([，！？：；（）])", text)
    return _strip_symbols("".join(part if i % 2 else unicodedata.normalize("NFKC", part)
                                  for i, part in enumerate(parts)))


def toy_of(item: CustomizedItem) -> Optional[str]:
    return next((clean_text(line.name) for line in item.lines
                 if "玩具" in line.name or "玩具" in line.round_name), None)


def kid_campaigns(payload: dict, limit: int = 3) -> list[Campaign]:
    data = payload.get("data")
    if not isinstance(data, dict) or limit <= 0:
        return []
    days = data.get("dailyList")
    if not isinstance(days, list):
        return []
    campaigns, seen = [], set()
    for day in days:
        if not isinstance(day, dict) or not isinstance(day.get("events"), list):
            continue
        for event in day["events"]:
            article = event.get("articleDto") if isinstance(event, dict) else None
            if not isinstance(article, dict):
                continue
            title, content = article.get("title"), article.get("content")
            title = _clean_title(title) if isinstance(title, str) else ""
            content = clean_text(content) if isinstance(content, str) else ""
            if not title or title in seen or not any(word in title + content for word in KID_KEYWORDS):
                continue
            summary = next((line.strip() for line in content.splitlines() if line.strip()), "")[:40]
            campaigns.append(Campaign(str(day.get("date") or ""), title, summary))
            seen.add(title)
            if len(campaigns) >= limit:
                return campaigns
    return campaigns
