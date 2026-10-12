"""本地纪念卡片共用的素材路径和图片 HTML。"""
from __future__ import annotations

import html
from pathlib import Path
from urllib.parse import urlsplit

ASSETS = Path(__file__).resolve().parent / "assets"


def safe_image_uri(uri, allow_file: bool = True) -> str:
    """仅允许 HTTPS 外部图片和本机绝对 file URI；不下载或上传图片。"""
    if not isinstance(uri, str) or any(ord(c) < 32 for c in uri):
        return ""
    try:
        parsed = urlsplit(uri)
        if parsed.scheme == "https" and parsed.hostname:
            return uri
        if allow_file and parsed.scheme == "file" and not parsed.netloc and parsed.path.startswith("/"):
            return uri
    except ValueError:
        pass
    return ""


def image_tag(uri, alt: str, class_name: str) -> str:
    uri = safe_image_uri(uri)
    if not uri:
        return ""
    return f'<img class="{html.escape(class_name)}" src="{html.escape(uri)}" alt="{html.escape(alt)}">'
