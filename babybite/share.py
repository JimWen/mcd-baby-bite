"""生成小红书笔记草稿；用户确认后通过本机 xiaohongshu-mcp 的 publish_content 发布。"""
from __future__ import annotations

import os
from pathlib import Path

from .cards import age_label
from .mcp_client import McpHttpClient

XHS_MCP_URL = "http://127.0.0.1:18060/mcp"
TITLE_MAX, CONTENT_MAX = 20, 1000
DEFAULT_TAGS = ("宝宝外出吃饭", "带娃日常", "宝宝辅食", "麦当劳", "遛娃")
VISIBILITIES = ("仅自己可见", "公开可见", "仅互关好友可见")
DEFAULT_VISIBILITY = "仅自己可见"


def build_note(saved: dict) -> dict:
    """按保存的方案生成个人经验口吻的笔记；不放外链（避免被判定引流）。"""
    top = saved["plans"][0]
    age = age_label(saved["ageMonths"]).replace(" ", "")
    mains = "、".join(f"{c['name']} {c['note']}" for c in top["components"] if c["role"] == "main")
    removed = "、".join(top.get("removed") or []) or "无"
    lines = [
        f"带{age}的宝宝去麦当劳，我是这样点的：",
        "",
        f"套餐：{top['name']}",
        f"线上已去：{removed}（点单时选特制就能去掉）",
        f"宝宝吃：{mains}",
        f"这一餐宝宝的钠大约不超过 {top['kidSodiumMg']:.0f}mg，约占这个年龄每日建议上限的 {top['dayLimitPct']}%"
        "（参考中国营养学会《家庭减盐行为指南》）。",
        "",
    ]
    if top.get("saltRequests"):
        lines += ["线上去不掉的盐，我会跟店员说一句：", f"“{top['staffScript']}”", ""]
    lines += ["小提示：", "1. 偶尔吃，回家搭配蔬果和白水", "2. 拿到先尝一口温度和咸淡", "3. 3 岁以下撕成小块，全程看护", "",
              "个人经验分享，不构成营养建议，餐品与价格以门店为准。"]
    return {
        "title": f"{age}宝宝吃麦当劳这样点"[:TITLE_MAX],
        "content": "\n".join(lines)[:CONTENT_MAX],
        "tags": list(DEFAULT_TAGS),
    }


def render_draft(note: dict, images: list) -> str:
    out = [f"# {note['title']}", "", note["content"], "", "话题：" + " ".join(f"#{t}" for t in note["tags"])]
    if images:
        out += ["", "图片："] + [f"- {p}" for p in images]
    return "\n".join(out) + "\n"


def default_client() -> McpHttpClient:
    return McpHttpClient(os.environ.get("XHS_MCP_URL", XHS_MCP_URL), write_tools=frozenset({"publish_content"}),
                         timeout=180.0)


def publish(note: dict, images: list, visibility: str = DEFAULT_VISIBILITY, client=None) -> str:
    if visibility not in VISIBILITIES:
        raise ValueError(f"可见范围需为：{'、'.join(VISIBILITIES)}")
    paths = [str(Path(p).resolve()) for p in images]
    missing = [p for p in paths if not Path(p).is_file()]
    if not paths or missing:
        raise ValueError("发布小红书至少需要 1 张已存在的图片" + (f"，找不到：{'、'.join(missing)}" if missing else ""))
    client = client or default_client()
    return client.call_tool_text("publish_content", {
        "title": note["title"], "content": note["content"], "images": paths,
        "tags": note["tags"], "visibility": visibility,
    })
