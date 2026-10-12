import io
import json
import tempfile
import unittest
from pathlib import Path

from babybite.cards import BANNED_PHRASES
from babybite.cli import EXIT_ERROR, EXIT_OK, EXIT_USAGE, main
from babybite.mcp_client import McpHttpClient
from babybite.share import CONTENT_MAX, TITLE_MAX, build_note, render_draft
from tests.fake_mcp import INIT, NOTIFIED, FakeMcp, tool_ok


class FakeXhs:
    def __init__(self):
        self.calls = []

    def call_tool_text(self, name, args):
        self.calls.append((name, args))
        return "发布成功"


def saved_plan(tmp, offline=False):
    path = Path(tmp) / "plan.json"
    main(["plan", "--age-months", "18", "--offline", "--save", str(path)], out=io.StringIO())
    data = json.loads(path.read_text("utf-8"))
    data["offline"] = offline
    path.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    return path, data


def run_share(argv, xhs=None):
    out = io.StringIO()
    code = main(argv, out=out, xhs_factory=(lambda: xhs) if xhs else None)
    return code, out.getvalue()


class NoteTest(unittest.TestCase):
    def test_note_limits_and_tone(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, data = saved_plan(tmp)
        note = build_note(data)
        self.assertEqual(note["title"], "1岁6个月宝宝吃麦当劳这样点")
        self.assertLessEqual(len(note["title"]), TITLE_MAX)
        self.assertLessEqual(len(note["content"]), CONTENT_MAX)
        self.assertIn("汉堡开心乐园餐", note["content"])
        self.assertIn("牛肉饼不撒盐", note["content"])
        self.assertIn("偶尔吃", note["content"])
        self.assertNotIn("github", note["content"].lower())
        for phrase in BANNED_PHRASES:
            self.assertNotIn(phrase, note["content"])
        self.assertIn("宝宝外出吃饭", note["tags"])
        self.assertIn("参考《中国居民膳食指南（2022）》", note["content"])  # 1-2 岁的依据

    def test_draft_lists_images(self):
        note = {"title": "t", "content": "c", "tags": ["a"]}
        self.assertIn("/x/age-card.png", render_draft(note, ["/x/age-card.png"]))


class ShareCommandTest(unittest.TestCase):
    def test_draft_only_does_not_touch_xhs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = saved_plan(tmp)
            draft = Path(tmp) / "draft.md"
            code, text = run_share(["share", "--plan", str(path), "--out", str(draft)])
            self.assertEqual(code, EXIT_OK)
            self.assertIn("1岁6个月宝宝吃麦当劳这样点", text)
            self.assertTrue(draft.is_file())

    def test_publish_requires_confirm(self):
        xhs = FakeXhs()
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = saved_plan(tmp)
            image = Path(tmp) / "a.png"
            image.write_bytes(b"\x89PNG")
            code, text = run_share(["share", "--plan", str(path), "--images", str(image), "--publish"], xhs)
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(xhs.calls, [])
        self.assertIn("--confirm", text)

    def test_publish_with_confirm(self):
        xhs = FakeXhs()
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = saved_plan(tmp)
            image = Path(tmp) / "a.png"
            image.write_bytes(b"\x89PNG")
            code, _ = run_share(["share", "--plan", str(path), "--images", str(image), "--publish", "--confirm"], xhs)
            self.assertEqual(code, EXIT_OK)
            name, args = xhs.calls[0]
            self.assertEqual(name, "publish_content")
            self.assertEqual(args["images"], [str(image.resolve())])
            self.assertEqual(args["visibility"], "仅自己可见")

    def test_offline_plan_cannot_be_published(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = saved_plan(tmp, offline=True)
            image = Path(tmp) / "a.png"
            image.write_bytes(b"\x89PNG")
            code, _ = run_share(["share", "--plan", str(path), "--images", str(image), "--publish", "--confirm"], FakeXhs())
        self.assertEqual(code, EXIT_ERROR)

    def test_missing_image_is_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = saved_plan(tmp)
            code, _ = run_share(["share", "--plan", str(path), "--images", "/nope.png", "--publish", "--confirm"], FakeXhs())
        self.assertEqual(code, EXIT_USAGE)


class GenericClientTest(unittest.TestCase):
    def test_no_token_means_no_authorization_header(self):
        fake = FakeMcp([INIT, NOTIFIED, tool_ok({"ok": 1})])
        self.addCleanup(fake.close)
        text = McpHttpClient(fake.url, sleep=lambda s: None).call_tool_text("publish_content", {})
        self.assertIn('"ok": 1', text)
        self.assertNotIn("authorization", fake.requests[2]["headers"])


if __name__ == "__main__":
    unittest.main()
