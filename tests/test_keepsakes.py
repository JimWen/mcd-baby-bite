import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from babybite.checkin import render_checkin, validate_photo
from babybite.cli import main
from babybite.learn_cards import (VOCAB, render_print_sheet, render_word_card, word_for,
                                  words_from_plan)
from babybite.snapshot import html_to_pdf

FAKE_BROWSER = """#!/usr/bin/env python3
import sys
for arg in sys.argv[1:]:
    if arg.startswith("--screenshot="):
        open(arg.split("=", 1)[1], "wb").write(b"\\x89PNG fake")
    if arg.startswith("--print-to-pdf="):
        open(arg.split("=", 1)[1], "wb").write(b"%PDF-1.4 fake")
"""


def fake_browser(folder):
    path = Path(folder) / "fake-chrome"
    path.write_text(FAKE_BROWSER, "utf-8")
    path.chmod(0o755)
    return str(path)


def saved_plan(folder):
    path = Path(folder) / "plan.json"
    with redirect_stderr(io.StringIO()):
        main(["plan", "--age-months", "18", "--offline", "--save", str(path)], out=io.StringIO())
    return path, json.loads(path.read_text("utf-8"))


def run(argv):
    out = io.StringIO()
    with redirect_stderr(io.StringIO()):
        code = main(argv, out=out)
    return code, out.getvalue()


class VocabTest(unittest.TestCase):
    def test_word_for(self):
        cases = {"鱼排堡": "fish", "麦乐鸡-4块": "chicken nuggets", "原味板烧鸡腿麦满分": "muffin",
                 "板烧鸡腿堡": "chicken", "汉堡包": "hamburger", "迷你薯条": "French fries",
                 "小杯玉米杯": "corn", "100%苹果汁": "juice", "苹果片一袋(60g)": "apple",
                 "纯牛奶": "milk", "纯悦": "water"}
        for name, english in cases.items():
            with self.subTest(name=name):
                self.assertEqual(word_for(name).en, english)
        self.assertIsNone(word_for("海绵宝宝×航海王系列玩具"))

    def test_vocab_assets_exist(self):
        assets = Path(__file__).resolve().parent.parent / "babybite" / "assets"
        for word in VOCAB:
            self.assertTrue((assets / "food" / f"{word.asset}.png").is_file(), word.asset)
        self.assertTrue((assets / "mascot.png").is_file())


class PlanImagesTest(unittest.TestCase):
    def test_saved_plan_carries_codes_and_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, data = saved_plan(tmp)
        top = data["plans"][0]
        self.assertTrue(top["image"].startswith("https://"))
        components = {c["name"]: c for c in top["components"]}
        self.assertEqual(components["小杯玉米杯"]["code"], "4437")
        self.assertTrue(components["小杯玉米杯"]["image"].startswith("https://"))
        self.assertIsNone(components["汉堡包"]["image"])

    def test_words_from_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, data = saved_plan(tmp)
        words = words_from_plan(data)
        self.assertEqual([w.zh for w, _ in words], ["汉堡", "薯条", "玉米", "牛奶"])
        images = dict((w.zh, image) for w, image in words)
        self.assertTrue(images["玉米"].startswith("https://"))
        self.assertTrue(images["汉堡"].startswith("file://") and images["汉堡"].endswith("hamburger.png"))


class RenderTest(unittest.TestCase):
    def test_word_card(self):
        word = word_for("汉堡包")
        page = render_word_card(word, "file:///x/hamburger.png", "file:///x/mascot.png")
        for part in ("汉堡", "hàn bǎo", "hamburger", "我吃汉堡。", "I eat a hamburger.", "mascot.png"):
            self.assertIn(part, page)

    def test_print_sheet_pages(self):
        cards = [(word_for(n), "file:///x/a.png") for n in ("汉堡包", "迷你薯条", "玉米杯", "纯牛奶", "苹果片")]
        page = render_print_sheet(cards, "file:///x/mascot.png")
        self.assertIn("size: A4", page)
        self.assertEqual(page.count('class="page"'), 2)

    def test_checkin_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, data = saved_plan(tmp)
        page = render_checkin(data, name="小米<b>", date="2026-10-12", text="第一次自己吃汉堡",
                              photo_uri=None, mascot_uri="file:///x/mascot.png")
        for part in ("小米&lt;b&gt;的麦麦打卡", "2026-10-12 · 1 岁 6 个月", "汉堡开心乐园餐",
                     "今天吃了：汉堡包 1/4 份", "去料减盐 宝宝版", "第一次自己吃汉堡", "偶尔吃，吃得明白！",
                     "非麦当劳官方"):
            self.assertIn(part, page)
        self.assertNotIn("小米<b>", page)

    def test_validate_photo(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "a.JPG"
            good.write_bytes(b"x")
            self.assertTrue(validate_photo(str(good)).startswith("file://"))
            heic = Path(tmp) / "a.heic"
            heic.write_bytes(b"x")
            with self.assertRaises(ValueError):
                validate_photo(str(heic))
            with self.assertRaises(ValueError):
                validate_photo(str(Path(tmp) / "missing.jpg"))


class CommandTest(unittest.TestCase):
    def test_html_to_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = Path(tmp) / "a.html"
            html.write_text("<p>x</p>", "utf-8")
            self.assertTrue(html_to_pdf(html, Path(tmp) / "a.pdf", browser=fake_browser(tmp)))
            self.assertTrue((Path(tmp) / "a.pdf").read_bytes().startswith(b"%PDF"))

    def test_learn_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = saved_plan(tmp)
            out_dir = Path(tmp) / "learn"
            with mock.patch.dict(os.environ, {"BABYBITE_BROWSER": fake_browser(tmp)}):
                code, _ = run(["learn", "--plan", str(path), "--out", str(out_dir)])
            self.assertEqual(code, 0)
            self.assertEqual(sorted(p.name for p in out_dir.iterdir()),
                             ["card-01-hamburger.png", "card-02-french-fries.png", "card-03-corn.png",
                              "card-04-milk.png", "learn-cards.html", "learn-cards.pdf"])

    def test_learn_with_photo_adds_baby_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = saved_plan(tmp)
            photo = Path(tmp) / "baby.png"
            photo.write_bytes(b"\x89PNG")
            out_dir = Path(tmp) / "learn"
            with mock.patch.dict(os.environ, {"BABYBITE_BROWSER": "/nonexistent"}):
                code, _ = run(["learn", "--plan", str(path), "--photo", str(photo), "--out", str(out_dir)])
            self.assertEqual(code, 0)
            sheet = (out_dir / "learn-cards.html").read_text("utf-8")
            self.assertIn("This is me!", sheet)
            self.assertIn(photo.resolve().as_uri(), sheet)

    def test_checkin_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = saved_plan(tmp)
            out = Path(tmp) / "checkin.png"
            with mock.patch.dict(os.environ, {"BABYBITE_BROWSER": fake_browser(tmp)}):
                code, _ = run(["checkin", "--plan", str(path), "--name", "小米", "--out", str(out)])
            self.assertEqual(code, 0)
            self.assertTrue(out.is_file())
            self.assertIn("小米的麦麦打卡", (Path(tmp) / "checkin.html").read_text("utf-8"))

    def test_checkin_rejects_heic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = saved_plan(tmp)
            photo = Path(tmp) / "baby.heic"
            photo.write_bytes(b"x")
            code, _ = run(["checkin", "--plan", str(path), "--photo", str(photo), "--out", str(Path(tmp) / "c.png")])
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
