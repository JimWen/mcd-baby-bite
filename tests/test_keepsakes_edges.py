"""批次 I 的边界与回归测试；不改动验收方测试。"""
from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from dataclasses import FrozenInstanceError
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

from babybite.cards import plan_to_dict
from babybite.cli import main
from babybite.errors import BabyBiteError
from babybite.menu import MealDetail, MenuItem, parse_meal_detail, parse_menu
from tests.helpers import load_menu
from tests.test_cards import make_result
from tests.test_phone_cards import make_fake_browser


class MenuImagesTest(unittest.TestCase):
    def test_positional_constructors_keep_defaults(self):
        self.assertIsNone(MenuItem('1', '汉堡', 10, '主食').image)
        self.assertEqual(MealDetail('1', '汉堡', (), ()).image, '')

    def test_menu_images_include_uncategorized_and_missing_values(self):
        menu = parse_menu({'data': {
            'categories': [{'name': '主食', 'meals': [{'code': '1'}, {'code': '1'}]}],
            'meals': {'1': {'name': '汉堡', 'image': 'https://example.org/burger.png'},
                      '2': {'name': '玉米', 'image': 'https://example.org/corn.png'},
                      '3': {'name': '牛奶'}},
        }})
        self.assertEqual([m.image for m in menu],
                         ['https://example.org/burger.png', 'https://example.org/corn.png', None])

    def test_detail_images_and_empty_payload(self):
        self.assertEqual(parse_meal_detail({'data': {'image': 'https://example.org/meal.png'}}).image,
                         'https://example.org/meal.png')
        for data in ({}, {'data': None}, {'data': {'image': None}}):
            self.assertEqual(parse_meal_detail(data).image, '')


class PlanImageMapTest(unittest.TestCase):
    def test_default_image_maps_are_independent(self):
        first, second = make_result(), make_result()
        first.images['1'] = 'https://example.org/1.png'
        self.assertEqual(second.images, {})

    def test_cli_populates_all_menu_images(self):
        with mock.patch('babybite.cli._emit') as emit:
            self.assertEqual(main(['plan', '--age-months', '18', '--offline'], out=io.StringIO()), 0)
        self.assertEqual(emit.call_args.args[0].images, {m.code: m.image for m in load_menu() if m.image})
        self.assertTrue(emit.call_args.args[0].images)


class PlanImageSerializationTest(unittest.TestCase):
    def test_every_plan_and_component_uses_its_own_code(self):
        result = make_result()
        result.images = {m.code: m.image for m in load_menu() if m.image}
        for original, saved in zip(result.plans, plan_to_dict(result)['plans']):
            self.assertEqual(saved['image'], result.images.get(original.item.product_code))
            for line, component in zip(original.item.lines, saved['components']):
                self.assertEqual(component['code'], line.code)
                self.assertEqual(component['image'], result.images.get(line.code))

    def test_absent_images_are_serialized_as_null(self):
        result = make_result()
        for saved in plan_to_dict(result)['plans']:
            self.assertIsNone(saved['image'])
            self.assertTrue(all(c['image'] is None for c in saved['components']))


class PdfSnapshotTest(unittest.TestCase):
    def test_pdf_flags_and_hanging_browser_is_reaped(self):
        from babybite.snapshot import html_to_pdf
        script = '''#!/usr/bin/env python3
import pathlib, sys, time
assert '--no-pdf-header-footer' in sys.argv
assert sys.argv[-1].startswith('file://')
for arg in sys.argv:
    if arg.startswith('--print-to-pdf='):
        pathlib.Path(arg.split('=', 1)[1]).write_bytes(b'%PDF-1.4 fake')
time.sleep(30)
'''
        with tempfile.TemporaryDirectory() as tmp:
            page, pdf = Path(tmp) / 'a.html', Path(tmp) / 'a.pdf'
            page.write_text('<p>本地</p>', 'utf-8')
            processes = []
            popen = subprocess.Popen

            def start(*args, **kwargs):
                proc = popen(*args, **kwargs)
                processes.append(proc)
                return proc

            with mock.patch('babybite.snapshot.subprocess.Popen', side_effect=start):
                started = time.monotonic()
                self.assertTrue(html_to_pdf(page, pdf, browser=make_fake_browser(tmp, script)))
            self.assertLess(time.monotonic() - started, 10)
            self.assertIsNotNone(processes[0].returncode)
            self.assertTrue(pdf.read_bytes().startswith(b'%PDF'))

    def test_pdf_missing_browser_is_optional(self):
        from babybite.snapshot import html_to_pdf
        with mock.patch('babybite.snapshot.find_browser', return_value=None):
            self.assertFalse(html_to_pdf('unused.html', 'unused.pdf'))

    def test_pdf_failure_cannot_reuse_stale_or_empty_file(self):
        from babybite.snapshot import html_to_pdf
        for contents in (b'old PDF', b''):
            with self.subTest(contents=contents), tempfile.TemporaryDirectory() as tmp:
                page, pdf = Path(tmp) / 'a.html', Path(tmp) / 'a.pdf'
                page.write_text('x', 'utf-8')
                pdf.write_bytes(contents)
                browser = make_fake_browser(tmp, '#!/usr/bin/env python3\nraise SystemExit(3)\n')
                with self.assertRaises(BabyBiteError):
                    html_to_pdf(page, pdf, browser=browser)

    def test_timeout_kills_stubborn_browser_for_both_formats(self):
        from babybite.snapshot import html_to_pdf, html_to_png
        for render, suffix in ((html_to_pdf, '.pdf'), (html_to_png, '.png')):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as tmp:
                proc = mock.Mock()
                proc.poll.return_value = None
                proc.wait.side_effect = [subprocess.TimeoutExpired('fake', 5), 0]
                with mock.patch('babybite.snapshot.subprocess.Popen', return_value=proc):
                    with self.assertRaises(BabyBiteError):
                        render(Path(tmp) / 'a.html', Path(tmp) / ('a' + suffix), browser='fake', timeout=0)
                proc.terminate.assert_called_once()
                proc.kill.assert_called_once()
                self.assertEqual(proc.wait.call_count, 2)

    def test_pdf_start_failure_has_chinese_error(self):
        from babybite.snapshot import html_to_pdf
        with mock.patch('babybite.snapshot.subprocess.Popen', side_effect=OSError('无法执行')):
            with self.assertRaisesRegex(BabyBiteError, '浏览器渲染'):
                html_to_pdf('unused.html', '/tmp/batch-I-unused.pdf', browser='fake')


class ImageSources(HTMLParser):
    def __init__(self, page):
        super().__init__()
        self.sources = []
        self.events = []
        self.feed(page)

    def handle_starttag(self, tag, attrs):
        self.events.extend(key for key, _ in attrs if key.startswith('on'))
        if tag == 'img':
            self.sources.append(dict(attrs).get('src'))


class LearnCardsEdgeTest(unittest.TestCase):
    def test_vocabulary_is_frozen_and_order_matches_spec(self):
        from babybite.learn_cards import VOCAB
        self.assertEqual([w.en for w in VOCAB], ['fish', 'chicken nuggets', 'muffin', 'chicken',
                         'hamburger', 'French fries', 'corn', 'juice', 'apple', 'milk', 'water'])
        self.assertEqual(VOCAB[0].keys, ('鱼',))
        with self.assertRaises(FrozenInstanceError):
            VOCAB[0].zh = '修改'

    def test_top_plan_component_order_deduplication_and_skips(self):
        from babybite.learn_cards import words_from_plan
        data = {'plans': [{'components': [
            {'name': '纯牛奶', 'image': 'https://example.org/milk.png'},
            {'name': '汉堡包', 'image': None},
            {'name': '吉士汉堡'}, {'name': '玉米玩具', 'role': 'skip'},
            {'name': '苹果片', 'note': '不计入'}, {'name': '未知餐品'},
            {'name': '迷你薯条', 'role': 'fries', 'portion': 0},
        ]}, {'components': [{'name': '鱼排堡'}]}]}
        cards = words_from_plan(data)
        self.assertEqual([w.en for w, _ in cards], ['milk', 'hamburger', 'French fries'])
        self.assertEqual(cards[0][1], 'https://example.org/milk.png')
        self.assertTrue(cards[1][1].endswith('/food/hamburger.png'))
        self.assertEqual(words_from_plan({}), [])

    def test_only_https_component_images_override_local_illustrations(self):
        from babybite.learn_cards import words_from_plan
        for unsafe in ('http://example.org/x.png', '//example.org/x.png', 'javascript:alert(1)',
                       'data:image/png;base64,eA==', 'file:///private/a.png', 'https:///x.png', None):
            with self.subTest(image=unsafe):
                cards = words_from_plan({'plans': [{'components': [{'name': '汉堡', 'image': unsafe}]}]})
                self.assertTrue(cards[0][1].startswith('file://'))
                self.assertTrue(cards[0][1].endswith('/food/hamburger.png'))

    def test_card_escapes_all_word_text_and_image_attributes(self):
        from babybite.learn_cards import Word, render_word_card
        bad = '<b>"&文本</b>'
        word = Word(('关键词',), bad, bad, bad, bad, bad, 'hamburger')
        uri = 'https://example.org/a.png?x=" onerror="alert(1)&y=2'
        page = render_word_card(word, uri, 'file:///tmp/mascot.png')
        self.assertNotIn(bad, page)
        self.assertIn('&lt;b&gt;&quot;&amp;文本&lt;/b&gt;', page)
        images = ImageSources(page)
        self.assertEqual(images.events, [])
        self.assertIn(uri, images.sources)
        self.assertIn('1080px', page)
        self.assertIn('1440px', page)

    def test_card_rejects_non_https_external_and_remote_file_images(self):
        from babybite.learn_cards import render_word_card, word_for
        for uri in ('http://example.org/a.png', '//example.org/a.png', 'javascript:alert(1)',
                    'file://remote/a.png', 'https:///a.png'):
            with self.subTest(uri=uri):
                page = render_word_card(word_for('汉堡'), uri, uri)
                self.assertNotIn(uri, ImageSources(page).sources)

    def test_print_pagination_and_cut_lines(self):
        from babybite.learn_cards import render_print_sheet, word_for
        for count, pages in ((0, 0), (1, 1), (4, 1), (5, 2), (8, 2), (9, 3)):
            with self.subTest(count=count):
                page = render_print_sheet([(word_for('汉堡'), 'file:///tmp/a.png')] * count,
                                          'file:///tmp/mascot.png')
                self.assertEqual(page.count('class="page"'), pages)
                self.assertEqual(page.count('class="word-card"'), count)
                self.assertIn('@page { size: A4; margin: 10mm }', page)
                self.assertIn('dashed', page)


class CheckinEdgeTest(unittest.TestCase):
    def render(self, saved=None, **kwargs):
        from babybite.checkin import render_checkin
        values = dict(name='宝宝', date='2026-10-12', text='', photo_uri=None,
                      mascot_uri='file:///tmp/mascot.png')
        values.update(kwargs)
        return render_checkin(saved or plan_to_dict(make_result()), **values)

    def test_photo_extensions_and_directory_rejection(self):
        from babybite.checkin import validate_photo
        with tempfile.TemporaryDirectory() as tmp:
            for ext in ('.jpg', '.JPEG', '.PNG', '.WebP', '.GIF'):
                path = Path(tmp) / ('宝宝 照片' + ext)
                path.write_bytes(b'image')
                self.assertEqual(validate_photo(path), path.resolve().as_uri())
            folder = Path(tmp) / 'folder.png'
            folder.mkdir()
            with self.assertRaises(ValueError):
                validate_photo(folder)
            for ext in ('.HEIC', '.heif', '.svg', '.txt'):
                path = Path(tmp) / ('photo' + ext)
                path.write_bytes(b'image')
                with self.assertRaisesRegex(ValueError, '转换'):
                    validate_photo(path)

    def test_actual_food_portions_exclude_fries_and_toys(self):
        saved = plan_to_dict(make_result())
        page = self.render(saved)
        self.assertIn('今天吃了：汉堡包 1/4 份、小杯玉米杯、纯牛奶', page)
        self.assertNotIn('迷你薯条', page)
        self.assertNotIn('海绵宝宝', page)
        self.assertIn('去料减盐 宝宝版', page)
        self.assertIn('1080px', page)
        self.assertIn('1440px', page)
        self.assertIn('file:///tmp/mascot.png', page)

    def test_badge_depends_on_removals_or_salt_requests(self):
        saved = plan_to_dict(make_result())
        saved['plans'][0]['removed'] = []
        saved['plans'][0]['saltRequests'] = []
        self.assertNotIn('去料减盐 宝宝版', self.render(saved))
        saved['plans'][0]['saltRequests'] = ['薯条不加盐']
        self.assertIn('去料减盐 宝宝版', self.render(saved))

    def test_photo_meal_image_and_all_text_are_escaped(self):
        saved = plan_to_dict(make_result())
        bad = '<script>"&内容</script>'
        saved['plans'][0]['name'] = bad
        saved['plans'][0]['components'][0]['name'] = bad
        uri = 'https://example.org/meal.png?x=" onerror="alert(1)&y=2'
        saved['plans'][0]['image'] = uri
        page = self.render(saved, name=bad, date=bad, text=bad, photo_uri='file:///tmp/baby.png')
        self.assertNotIn('<script>', page)
        self.assertIn('&lt;script&gt;&quot;&amp;内容&lt;/script&gt;', page)
        images = ImageSources(page)
        self.assertEqual(images.events, [])
        self.assertIn(uri, images.sources)
        self.assertIn('file:///tmp/baby.png', images.sources)

    def test_unsafe_meal_image_uses_illustration(self):
        saved = plan_to_dict(make_result())
        for uri in ('http://example.org/a.png', 'file:///private/a.png', 'javascript:alert(1)'):
            with self.subTest(uri=uri):
                saved['plans'][0]['image'] = uri
                images = ImageSources(self.render(saved))
                self.assertNotIn(uri, images.sources)
                self.assertTrue(any(src.endswith('/food/hamburger.png') for src in images.sources))


class KeepsakeCommandEdgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.plan = self.folder / 'plan.json'
        self.saved = plan_to_dict(make_result())
        self.plan.write_text(json.dumps(self.saved), 'utf-8')

    def command(self, command, extra=(), browser=None):
        from babybite import cli
        out, err = io.StringIO(), io.StringIO()
        factory = mock.Mock(side_effect=AssertionError('纪念卡片不能调用 API'))
        with mock.patch.object(cli, 'find_browser', return_value=browser), redirect_stderr(err):
            code = main([command, '--plan', str(self.plan)] + list(extra), client_factory=factory, out=out)
        factory.assert_not_called()
        return code, out.getvalue() + err.getvalue()

    def test_no_browser_creates_only_html_and_explains_fallback(self):
        for command in ('learn', 'checkin'):
            with self.subTest(command=command):
                target = self.folder / command / ('cards' if command == 'learn' else 'photo.png')
                with mock.patch('babybite.cli.html_to_png') as png:
                    code, text = self.command(command, ['--out', str(target)])
                self.assertEqual(code, 0)
                html = target / 'learn-cards.html' if command == 'learn' else target.with_suffix('.html')
                self.assertTrue(html.is_file())
                self.assertIn('HTML', text)
                self.assertIn('BABYBITE_BROWSER', text)
                png.assert_not_called()

    def test_default_output_paths(self):
        previous = Path.cwd()
        try:
            os.chdir(self.folder)
            self.assertEqual(self.command('learn')[0], 0)
            self.assertEqual(self.command('checkin')[0], 0)
        finally:
            os.chdir(previous)
        self.assertTrue((self.folder / 'learn-cards' / 'learn-cards.html').is_file())
        self.assertTrue((self.folder / 'checkin.html').is_file())

    def test_custom_photo_and_mascot_are_local_in_both_commands(self):
        photo, mascot = self.folder / '宝宝.PNG', self.folder / '自有图片.png'
        photo.write_bytes(b'image')
        mascot.write_bytes(b'image')
        for command in ('learn', 'checkin'):
            target = self.folder / ('learn' if command == 'learn' else 'c.png')
            code, _ = self.command(command, ['--photo', str(photo), '--mascot', str(mascot), '--out', str(target)])
            self.assertEqual(code, 0)
            path = target / 'learn-cards.html' if command == 'learn' else target.with_suffix('.html')
            images = ImageSources(path.read_text('utf-8'))
            self.assertIn(photo.resolve().as_uri(), images.sources)
            self.assertIn(mascot.resolve().as_uri(), images.sources)

    def test_bad_photo_and_mascot_are_usage_errors_before_output(self):
        heic = self.folder / 'a.heic'
        heic.write_bytes(b'x')
        for command in ('learn', 'checkin'):
            for flag in ('--photo', '--mascot'):
                for path in (self.folder / 'missing.png', heic, self.folder):
                    with self.subTest(command=command, flag=flag, path=path):
                        target = self.folder / 'bad-output'
                        code, message = self.command(command, [flag, str(path), '--out', str(target)])
                        self.assertEqual(code, 2)
                        self.assertIn('参数错误', message)
                        self.assertFalse(target.exists())
                        self.assertFalse(target.with_suffix('.html').exists())

    def test_checkin_date_priority_and_custom_text(self):
        target = self.folder / 'c.png'
        cases = [('2026-11-02', '2026-11-02'), (None, '2026-10-12')]
        for override, expected in cases:
            extra = ['--out', str(target), '--text', '一起长大<&>']
            if override:
                extra += ['--date', override]
            self.assertEqual(self.command('checkin', extra)[0], 0)
            page = target.with_suffix('.html').read_text('utf-8')
            self.assertIn(expected + ' · 1 岁 6 个月', page)
            self.assertIn('一起长大&lt;&amp;&gt;', page)
        self.saved['reservationDate'] = None
        self.plan.write_text(json.dumps(self.saved), 'utf-8')
        import datetime
        today = datetime.date.today().isoformat()
        self.assertEqual(self.command('checkin', ['--out', str(target)])[0], 0)
        self.assertIn(today + ' · ', target.with_suffix('.html').read_text('utf-8'))

    def test_checkin_invalid_date_is_usage_error(self):
        for date in ('2026-02-30', '今天', '20261012'):
            code, _ = self.command('checkin', ['--date', date, '--out', str(self.folder / 'c.png')])
            self.assertEqual(code, 2)

    def test_shared_plan_reader_and_invalid_files(self):
        from babybite.cli import _read_plan_file
        for command in ('learn', 'checkin'):
            target = self.folder / command
            with mock.patch('babybite.cli._read_plan_file', wraps=_read_plan_file) as reader:
                self.assertEqual(self.command(command, ['--out', str(target)])[0], 0)
            reader.assert_called_once_with(str(self.plan))
        for contents in ('not json', '[]'):
            self.plan.write_text(contents, 'utf-8')
            for command in ('learn', 'checkin'):
                self.assertEqual(self.command(command)[0], 2)
        self.plan.unlink()
        for command in ('learn', 'checkin'):
            self.assertEqual(self.command(command)[0], 2)

    def test_no_plan_is_explained_without_traceback(self):
        self.plan.write_text('{"plans": []}', 'utf-8')
        for command in ('learn', 'checkin'):
            code, text = self.command(command)
            self.assertEqual(code, 5)
            self.assertIn('没有', text)
            self.assertNotIn('Traceback', text)

    def test_baby_card_png_and_temporary_html_cleanup(self):
        from tests.test_keepsakes import fake_browser
        photo = self.folder / 'baby.png'
        photo.write_bytes(b'image')
        target = self.folder / 'learn'
        code, _ = self.command('learn', ['--photo', str(photo), '--out', str(target)],
                               browser=fake_browser(self.folder))
        self.assertEqual(code, 0)
        self.assertTrue((target / 'card-05-baby.png').is_file())
        self.assertEqual(len(list(target.iterdir())), 7)

    def test_renderer_failure_preserves_html_with_explanation(self):
        for command in ('learn', 'checkin'):
            target = self.folder / command
            with mock.patch('babybite.cli.html_to_png', side_effect=BabyBiteError('超时')), \
                    mock.patch('babybite.cli.html_to_pdf', side_effect=BabyBiteError('超时')):
                code, text = self.command(command, ['--out', str(target)], browser='fake')
            self.assertEqual(code, 0)
            page = target / 'learn-cards.html' if command == 'learn' else target.with_suffix('.html')
            self.assertTrue(page.is_file())
            self.assertIn('超时', text)
            self.assertIn('HTML', text)
