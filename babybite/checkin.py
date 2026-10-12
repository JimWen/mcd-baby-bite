"""宝宝打卡照片：在本机生成 HTML，再交给本机浏览器合成。"""
from __future__ import annotations

import html
from pathlib import Path

from .cards import age_label
from .keepsake_html import ASSETS, image_tag, safe_image_uri
from .learn_cards import word_for
from .planner import PORTION_LABELS

PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def validate_photo(path) -> str:
    photo = Path(path).expanduser()
    if not photo.is_file():
        raise ValueError(f"图片不存在或不是文件：{path}")
    if photo.suffix.lower() not in PHOTO_EXTENSIONS:
        raise ValueError("暂不支持此图片格式（含 HEIC），请先转换为 JPG / JPEG / PNG / WebP / GIF")
    return photo.resolve().as_uri()


def _eaten(top: dict) -> str:
    foods = []
    for component in top.get("components") or []:
        role, portion = component.get("role"), component.get("portion", 1)
        if role in ("skip", "fries") or component.get("note") == "不计入" or portion <= 0:
            continue
        name = component.get("name") or ""
        if role == "main" or portion != 1:
            label = next((label for value, label in PORTION_LABELS.items() if abs(value - portion) < 0.001),
                         f"{portion:g} 份")
            name += f" {label}"
        foods.append(name)
    return "、".join(foods)


_CSS = """
*{box-sizing:border-box}body{margin:0;width:1080px;height:1440px;color:#563d32;
font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:#fff2d8}
.poster{position:relative;isolation:isolate;width:1080px;height:1440px;padding:48px 58px;
display:flex;flex-direction:column;align-items:center;gap:18px;overflow:hidden;
background:radial-gradient(circle at 5px 5px,#dfb97655 2px,transparent 3px) 0 0/38px 38px}
.decor{position:absolute;z-index:-1;width:210px;height:210px;object-fit:contain;opacity:.13}
.decor-0{top:185px;left:-65px;transform:rotate(-22deg)}
.decor-1{top:540px;right:-55px;transform:rotate(22deg)}
.decor-2{bottom:110px;left:-55px;transform:rotate(18deg)}
header{text-align:center}h1{font-size:62px;line-height:1.2;margin:0 0 12px;overflow-wrap:anywhere}
.date{font-size:30px;color:#937352}.polaroid{position:relative;width:680px;flex:1;min-height:240px;
max-height:550px;background:white;padding:18px 18px 54px;transform:rotate(-2deg);
box-shadow:0 12px 30px #88603825}.photo{width:100%;height:100%;object-fit:cover;background:#fff8e9}
.photo.mascot-photo{object-fit:contain}.caption{position:absolute;bottom:14px;left:0;width:100%;
text-align:center;font-size:24px;letter-spacing:4px;color:#997956}
.meal{width:100%;display:flex;align-items:center;justify-content:center;gap:24px}
.meal-image{width:138px;height:110px;object-fit:contain}.meal h2{font-size:36px;margin:0;overflow-wrap:anywhere}
.eaten{width:100%;padding:18px 24px;border-radius:22px;background:#ffffffb8;font-size:29px;line-height:1.5}
.badge{background:#efba57;border-radius:30px;padding:10px 28px;font-size:25px;font-weight:700}
.message{font-size:30px;line-height:1.45;margin:0;text-align:center;overflow-wrap:anywhere}
.closing{display:flex;align-items:center;gap:12px}.mascot{width:138px;height:138px;object-fit:contain}
.bubble{background:white;padding:20px 26px;border-radius:28px;font-size:30px;font-weight:700}
footer{font-size:20px;color:#967c60}
"""


def render_checkin(saved, name, date, text, photo_uri, mascot_uri) -> str:
    e = html.escape
    top = (saved.get("plans") or [{}])[0]
    meal_name = top.get("name") or "宝宝餐"
    meal_image = safe_image_uri(top.get("image"), allow_file=False)
    word = word_for(meal_name)
    if not meal_image:
        meal_image = (ASSETS / "food" / f"{word.asset if word else 'hamburger'}.png").as_uri()
    photo = safe_image_uri(photo_uri) or safe_image_uri(mascot_uri)
    photo_class = "photo" if safe_image_uri(photo_uri) else "photo mascot-photo"
    decorations = "".join(image_tag((ASSETS / "food" / f"{asset}.png").as_uri(), "", f"decor decor-{i}")
                          for i, asset in enumerate(("corn", "apple", "hamburger")))
    badge = '<div class="badge">去料减盐 宝宝版</div>' if top.get("removed") or top.get("saltRequests") else ""
    message = f'<p class="message">{e(text)}</p>' if text else ""
    title = f"{name}的麦麦打卡"
    return ('<!doctype html>\n<html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e(title)}</title><style>{_CSS}</style></head><body><main class="poster">'
            f'{decorations}<header><h1>{e(title)}</h1>'
            f'<div class="date">{e(date)} · {e(age_label(saved.get("ageMonths", 0)))}</div></header>'
            f'<div class="polaroid">{image_tag(photo, "宝宝的打卡纪念", photo_class)}'
            '<div class="caption">今天也有小小的快乐</div></div>'
            f'<div class="meal">{image_tag(meal_image, meal_name, "meal-image")}<h2>{e(meal_name)}</h2></div>'
            f'<div class="eaten">今天吃了：{e(_eaten(top))}</div>{badge}{message}'
            f'<div class="closing">{image_tag(mascot_uri, "小麦芽", "mascot")}'
            '<div class="bubble">偶尔吃，吃得明白！</div></div>'
            '<footer>mcd-baby-bite · 非麦当劳官方</footer></main></body></html>')
