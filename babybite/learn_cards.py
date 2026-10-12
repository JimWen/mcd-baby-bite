"""从主推宝宝餐生成中英文教育卡片和 A4 打印页。"""
from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Optional

from .keepsake_html import ASSETS, image_tag, safe_image_uri


@dataclass(frozen=True)
class Word:
    keys: tuple
    zh: str
    pinyin: str
    en: str
    sentence_zh: str
    sentence_en: str
    asset: str


VOCAB = (
    Word(("鱼",), "鱼", "yú", "fish", "小鱼在水里游。", "Fish swim in the water.", "fish"),
    Word(("麦乐鸡", "鸡块"), "鸡块", "jī kuài", "chicken nuggets", "鸡块小小的。",
         "The nuggets are small.", "nuggets"),
    Word(("麦满分", "松饼"), "松饼", "sōng bǐng", "muffin", "早上吃松饼。",
         "I eat a muffin in the morning.", "muffin"),
    Word(("鸡腿", "板烧", "鸡"), "鸡肉", "jī ròu", "chicken", "鸡肉香香的。",
         "The chicken smells good.", "hamburger"),
    Word(("汉堡", "堡"), "汉堡", "hàn bǎo", "hamburger", "我吃汉堡。", "I eat a hamburger.", "hamburger"),
    Word(("薯条",), "薯条", "shǔ tiáo", "French fries", "我和爸爸分薯条。", "I share fries with Dad.", "fries"),
    Word(("玉米",), "玉米", "yù mǐ", "corn", "玉米黄黄的。", "The corn is yellow.", "corn"),
    Word(("苹果汁", "果汁"), "果汁", "guǒ zhī", "juice", "果汁甜甜的。", "The juice is sweet.", "apple"),
    Word(("苹果",), "苹果", "píng guǒ", "apple", "苹果甜甜的。", "The apple is sweet.", "apple"),
    Word(("牛奶",), "牛奶", "niú nǎi", "milk", "我爱喝牛奶。", "I like milk.", "milk"),
    Word(("纯悦", "水"), "水", "shuǐ", "water", "我喝水。", "I drink water.", "water"),
)
BABY_WORD = Word((), "宝宝", "bǎo bao", "baby", "这是我！", "This is me!", "")


def word_for(name: str) -> Optional[Word]:
    return next((word for word in VOCAB if any(key in name for key in word.keys)), None)


def words_from_plan(saved: dict) -> list[tuple[Word, str]]:
    top = (saved.get("plans") or [{}])[0]
    cards, seen = [], set()
    for component in top.get("components") or []:
        if component.get("role") == "skip" or component.get("note") == "不计入":
            continue
        word = word_for(component.get("name") or "")
        if word is None or word in seen:
            continue
        seen.add(word)
        uri = safe_image_uri(component.get("image"), allow_file=False)
        cards.append((word, uri or (ASSETS / "food" / f"{word.asset}.png").as_uri()))
    return cards


_CARD_CSS = """
*{box-sizing:border-box}body{margin:0;color:#53372c;background:#fff7e7;
font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
.word-card{width:100%;height:100%;padding:56px;display:flex;flex-direction:column;align-items:center;
gap:14px;text-align:center;background:#fffaf0;border:3px solid #efd6ab;border-radius:40px;overflow:hidden}
.eyebrow{font-size:26px;letter-spacing:5px;color:#9b7346}.art{width:100%;height:520px;min-height:0;
flex:1;object-fit:contain;border-radius:24px}.zh{font-size:88px;margin:0;line-height:1.15}
.pinyin{font-size:36px;color:#946c50}.en{font-size:54px;font-weight:700;line-height:1.2}
.sentences{font-size:32px;line-height:1.5;margin:12px 0}.sentences p{margin:0}
.signature{display:flex;align-items:center;justify-content:center;gap:18px;font-size:23px;color:#946c50}
.mascot{width:110px;height:110px;object-fit:contain}.footer{font-size:18px;color:#917e69}
"""


def _card_content(word: Word, image_uri: str, mascot_uri: str) -> str:
    e = html.escape
    return (f'<article class="word-card"><div class="eyebrow">小麦芽 · 一起认食物</div>'
            f'{image_tag(image_uri, word.zh, "art")}<h1 class="zh">{e(word.zh)}</h1>'
            f'<div class="pinyin">{e(word.pinyin)}</div><div class="en">{e(word.en)}</div>'
            f'<div class="sentences"><p>{e(word.sentence_zh)}</p><p>{e(word.sentence_en)}</p></div>'
            f'<div class="signature">{image_tag(mascot_uri, "小麦芽", "mascot")}和宝宝一起读一读</div>'
            '<div class="footer">mcd-baby-bite · 非麦当劳官方</div></article>')


def _document(title: str, css: str, body: str) -> str:
    return ('<!doctype html>\n<html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{html.escape(title)}</title><style>{_CARD_CSS}{css}</style></head>'
            f'<body>{body}</body></html>')


def render_word_card(word: Word, image_uri: str, mascot_uri: str) -> str:
    return _document(f"{word.zh} · 中英文教育卡片", "body{width:1080px;height:1440px;padding:36px}",
                     _card_content(word, image_uri, mascot_uri))


def render_print_sheet(cards, mascot_uri: str) -> str:
    cards = list(cards)
    pages = []
    for start in range(0, len(cards), 4):
        content = "".join(_card_content(word, uri, mascot_uri) for word, uri in cards[start:start + 4])
        pages.append(f'<div class="page">{content}</div>')
    css = """
@page { size: A4; margin: 10mm }
body{background:white;print-color-adjust:exact;-webkit-print-color-adjust:exact}
.page{width:190mm;height:276mm;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));
grid-template-rows:repeat(2,minmax(0,1fr));gap:6mm;break-after:page;page-break-after:always}
.page:last-child{break-after:auto;page-break-after:auto}
.word-card{padding:5mm;gap:2mm;border:1px dashed #b8a084;border-radius:0;break-inside:avoid}
.eyebrow{font-size:9pt;letter-spacing:1px}.art{height:42mm;border-radius:3mm}
.zh{font-size:28pt}.pinyin{font-size:12pt}.en{font-size:18pt}
.sentences{font-size:10pt;line-height:1.4;margin:1mm 0}.signature{font-size:8pt;gap:2mm}
.mascot{width:14mm;height:14mm}.footer{font-size:6pt}
"""
    return _document("宝宝中英文教育卡片 · A4 打印", css, "".join(pages))
