import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from babybite.age_rules import sodium_budget
from babybite.errors import BabyBiteError
from babybite.customize import customize_meal
from babybite.phone_cards import age_rows, card_candidate_codes, render_age_card, render_staff_card
from babybite.snapshot import find_browser, html_to_png
from tests.helpers import load_detail, load_index, load_menu
from tests.test_cli import run

FAKE_BROWSER = """#!/usr/bin/env python3
import sys
for arg in sys.argv[1:]:
    if arg.startswith("--screenshot="):
        open(arg.split("=", 1)[1], "wb").write(b"\\x89PNG fake")
"""
HANGING_BROWSER = FAKE_BROWSER + "import time\ntime.sleep(30)\n"
FAILING_BROWSER = "#!/usr/bin/env python3\nimport sys\nsys.exit(3)\n"


def make_fake_browser(folder, script=FAKE_BROWSER, name="fake-chrome"):
    path = Path(folder) / name
    path.write_text(script, "utf-8")
    path.chmod(0o755)
    return str(path)


class StaffCardTest(unittest.TestCase):
    def test_staff_card_content(self):
        item = customize_meal(load_detail("9900016057"), 18)
        page = render_staff_card(item, 18, "麦当劳上海黄浦华旭国际大厦餐厅")
        self.assertTrue(page.startswith("<!doctype html>"))
        for part in ("给店员看", "1 岁 6 个月", "酸黄瓜、洋葱粒、番茄酱、芥末酱", "牛肉饼不撒盐", "薯条不加盐", "做不到也没关系"):
            self.assertIn(part, page)

    def test_staff_card_escapes(self):
        item = customize_meal(load_detail("9900016056"), 18)
        page = render_staff_card(item, 18, "<b>店</b>")
        self.assertNotIn("<b>店</b>", page)
        self.assertIn("按正常出餐即可", page)
        self.assertNotIn("线上已经去掉", page)
        self.assertNotIn("做不到也没关系", page)


class AgeCardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        menu = load_menu()
        details = {code: load_detail(code) for code in card_candidate_codes(menu)}
        cls.rows = age_rows(menu, details, load_index())

    def test_rows_follow_bands_and_budgets(self):
        self.assertEqual([r.band_label for r in self.rows], ["1-2 岁", "2-3 岁", "4-6 岁"])
        self.assertEqual([r.meal_sodium_mg for r in self.rows], [197, 262, 393])
        self.assertEqual(self.rows[0].plan.item.name, "汉堡开心乐园餐")
        for row in self.rows:
            self.assertIsNotNone(row.plan)
            self.assertLessEqual(row.plan.kid_sodium_mg, row.meal_sodium_mg)

    def test_age_card_content(self):
        page = render_age_card(self.rows, "麦当劳上海黄浦华旭国际大厦餐厅", "2026-10-12 11:30")
        for part in ("宝宝点餐速查卡", "1-2 岁", "2-3 岁", "4-6 岁", "每天盐 ≤1.5g", "T/CNSS 022-2023", "偶尔吃"):
            self.assertIn(part, page)

    def test_missing_plan_row(self):
        rows = list(self.rows)
        rows[2] = rows[2].__class__(60, "4-6 岁", 3.0, 393, None)
        self.assertIn("暂无合适组合", render_age_card(rows, "店", None))


class SnapshotTest(unittest.TestCase):
    def test_env_pointing_nowhere_disables_browser(self):
        with mock.patch.dict(os.environ, {"BABYBITE_BROWSER": "/nonexistent/chrome"}):
            self.assertIsNone(find_browser())
            with tempfile.TemporaryDirectory() as tmp:
                html = Path(tmp) / "a.html"
                html.write_text("<p>x</p>", "utf-8")
                self.assertFalse(html_to_png(html, Path(tmp) / "a.png"))

    def test_fake_browser_writes_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = Path(tmp) / "a.html"
            html.write_text("<p>x</p>", "utf-8")
            self.assertTrue(html_to_png(html, Path(tmp) / "a.png", browser=make_fake_browser(tmp)))
            self.assertTrue((Path(tmp) / "a.png").read_bytes().startswith(b"\x89PNG"))

    def test_browser_that_never_exits_is_stopped_after_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = Path(tmp) / "a.html"
            html.write_text("<p>x</p>", "utf-8")
            started = time.monotonic()
            ok = html_to_png(html, Path(tmp) / "a.png", browser=make_fake_browser(tmp, HANGING_BROWSER, "hang"))
            self.assertTrue(ok)
            self.assertLess(time.monotonic() - started, 10)

    def test_browser_without_png_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = Path(tmp) / "a.html"
            html.write_text("<p>x</p>", "utf-8")
            with self.assertRaises(BabyBiteError):
                html_to_png(html, Path(tmp) / "a.png", browser=make_fake_browser(tmp, FAILING_BROWSER, "fail"))

    def test_cli_phone_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"BABYBITE_BROWSER": make_fake_browser(tmp)}):
                out_dir = Path(tmp) / "cards"
                code, _ = run(["plan", "--age-months", "18", "--offline", "--phone-card", str(out_dir)])
            self.assertEqual(code, 0)
            names = sorted(p.name for p in out_dir.iterdir())
            self.assertEqual(names, ["age-card.html", "age-card.png", "staff-card.html", "staff-card.png"])


if __name__ == "__main__":
    unittest.main()
