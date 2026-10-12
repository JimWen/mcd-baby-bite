import hashlib
import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DECLARATION_SHA256 = "cd28101bcb29cc8fb24b372fe91ce6b42c4a1487a54e01f7ade0c8c6a84241b7"
REQUIRED = ("README.md", "CONTEST_DECLARATION.md", "MCP_INTEGRATION.md", "mcp-config.example.json", "SKILL.md", "LICENSE")
# 真实泄露形态：Bearer 后的长串、URL 中 key= 后的长串（排除 ${...} 占位符）；精确比对由 pre-commit 钩子负责
SECRET_PATTERNS = (re.compile(r"Bearer\s+(?!\$\{)[A-Za-z0-9._-]{20,}"),
                   re.compile(r"[?&]key=(?!\$\{)[A-Za-z0-9]{20,}"))


def repo_files():
    listed = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                            capture_output=True, text=True, check=True).stdout.split()
    return [ROOT / p for p in listed if (ROOT / p).is_file()]


class ComplianceTest(unittest.TestCase):
    def test_required_files(self):
        for name in REQUIRED:
            with self.subTest(name=name):
                self.assertTrue((ROOT / name).is_file())

    def test_declaration_is_verbatim(self):
        digest = hashlib.sha256((ROOT / "CONTEST_DECLARATION.md").read_bytes()).hexdigest()
        self.assertEqual(digest, DECLARATION_SHA256)

    def test_mcp_config_only_env_placeholders(self):
        config = json.loads((ROOT / "mcp-config.example.json").read_text("utf-8"))
        auth = config["mcpServers"]["mcd-mcp"]["headers"]["Authorization"]
        self.assertEqual(auth, "Bearer ${MCD_MCP_TOKEN}")

    def test_no_secrets(self):
        for path in repo_files():
            if path.suffix in {".png", ".jpg", ".gif", ".pdf"}:
                continue
            text = path.read_text("utf-8", errors="ignore")
            for pattern in SECRET_PATTERNS:
                with self.subTest(path=str(path.relative_to(ROOT)), pattern=pattern.pattern):
                    self.assertIsNone(pattern.search(text))

    def test_secret_patterns_detect_real_shapes(self):
        sample = "Authorization: Bearer " + "a" * 32 + " https://x/mcp?key=" + "b" * 32
        self.assertTrue(all(p.search(sample) for p in SECRET_PATTERNS))
        self.assertFalse(any(p.search('"Authorization": "Bearer ${MCD_MCP_TOKEN}"') for p in SECRET_PATTERNS))


if __name__ == "__main__":
    unittest.main()
