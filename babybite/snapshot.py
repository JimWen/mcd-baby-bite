"""用本机 Chrome / Edge / Chromium 无头模式把 HTML 卡片渲染成 PNG（可选能力，没有浏览器时跳过）。"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from .errors import BabyBiteError

BROWSER_ENV = "BABYBITE_BROWSER"
CARD_SIZE = (1080, 1440)
POLL_INTERVAL = 0.2
MAC_BROWSERS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
)
PATH_BROWSERS = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "chrome")


def find_browser() -> Optional[str]:
    """环境变量 BABYBITE_BROWSER 优先（指向不存在的路径即视为禁用）；否则按常见安装位置查找。"""
    configured = os.environ.get(BROWSER_ENV, "").strip()
    if configured:
        return configured if Path(configured).exists() else None
    for path in MAC_BROWSERS:
        if Path(path).exists():
            return path
    for name in PATH_BROWSERS:
        found = shutil.which(name)
        if found:
            return found
    return None


def _wait_for_png(proc, png_path: Path, timeout: float) -> bool:
    """部分 Chrome 版本（实测 154）截图后进程不退出：图片已写出且大小稳定即视为成功。"""
    deadline = time.monotonic() + timeout
    last_size = -1
    while time.monotonic() < deadline:
        exited = proc.poll() is not None
        size = png_path.stat().st_size if png_path.exists() else -1
        if size > 0 and (exited or size == last_size):
            return True
        if exited:
            return False
        last_size = size
        time.sleep(POLL_INTERVAL)
    return False


def html_to_png(html_path, png_path, size=CARD_SIZE, browser: Optional[str] = None, timeout: int = 60) -> bool:
    """渲染成功返回 True；找不到浏览器返回 False；浏览器执行失败或超时抛 BabyBiteError。"""
    browser = browser or find_browser()
    if not browser:
        return False
    html_path, png_path = Path(html_path).resolve(), Path(png_path).resolve()
    if png_path.exists():
        png_path.unlink()
    with tempfile.TemporaryDirectory() as profile:
        cmd = [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
               "--no-default-browser-check", f"--user-data-dir={profile}", "--force-device-scale-factor=1",
               f"--window-size={size[0]},{size[1]}", f"--screenshot={png_path}", html_path.as_uri()]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            raise BabyBiteError(f"浏览器渲染卡片失败：{exc}") from None
        try:
            ok = _wait_for_png(proc, png_path, timeout)
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
    if not ok:
        raise BabyBiteError("浏览器渲染卡片失败：未生成图片")
    return True
