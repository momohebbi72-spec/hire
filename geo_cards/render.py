"""HTML → PNG (Playwright, or the Chrome already on your Mac) and story slides → silent MP4."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .settings import env

MAC_BROWSERS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
)
OTHER_BROWSERS = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge")


def find_chrome():
    candidates = [env("CHROME_PATH"), *MAC_BROWSERS]
    candidates += [shutil.which(name) or "" for name in OTHER_BROWSERS]
    for path in candidates:
        if path and Path(path).exists():
            return path
    return None


def _html_path(png: Path) -> Path:
    """post/01-hook.png → html/post/01-hook.html"""
    return png.parent.parent / "html" / png.parent.name / f"{png.stem}.html"


def _png_size(path: Path):
    with path.open("rb") as fh:
        head = fh.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def render_pngs(jobs: list, renderer: str = "auto", log=print) -> None:
    """jobs: [(html, png path, (width, height))]. The HTML files are kept next to the output for edits."""
    for page, png, _ in jobs:
        png.parent.mkdir(parents=True, exist_ok=True)
        source = _html_path(png)
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(page, encoding="utf-8")
    if renderer in ("auto", "playwright"):
        try:
            _render_playwright(jobs)
            return
        except ImportError:
            if renderer == "playwright":
                raise RuntimeError("Playwright نصب نیست: pip install playwright && playwright install chromium")
        except Exception as exc:
            if renderer == "playwright":
                raise
            log(f"Playwright کار نکرد، با کروم می‌سازم ({exc})")
    _render_chrome(jobs, log)


def _launch(pw):
    """Your own Chrome first (no browser download needed), then Playwright's bundled one."""
    attempts = []
    if env("CHROME_PATH"):
        attempts.append({"executable_path": env("CHROME_PATH")})
    attempts += [{"channel": "chrome"}, {}, {"channel": "msedge"}]
    last_error = None
    for kwargs in attempts:
        try:
            return pw.chromium.launch(**kwargs)
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"Playwright مرورگری پیدا نکرد: {last_error}")


def _render_playwright(jobs: list) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = _launch(pw)
        try:
            for page_html, png, (width, height) in jobs:
                page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
                page.set_content(page_html, wait_until="load")
                page.evaluate("() => document.fonts.ready.then(() => true)")
                page.screenshot(path=str(png))
                page.close()
        finally:
            browser.close()


# Headless Chrome paints a viewport shorter than --window-size, so the bottom of the slide
# would be cut. Render a taller window and crop back to the slide size.
_EXTRA_HEIGHT = 240


def _crop(png: Path, width: int, height: int) -> bool:
    try:
        from PIL import Image
    except ImportError:
        return False
    with Image.open(png) as image:
        cropped = image.crop((0, 0, width, height))
    cropped.save(png)
    return True


def _render_chrome(jobs: list, log) -> None:
    chrome = find_chrome()
    if not chrome:
        raise RuntimeError("کروم پیدا نشد. Google Chrome را نصب کن یا مسیرش را در CHROME_PATH بگذار.")
    with tempfile.TemporaryDirectory() as profile:
        for _, png, (width, height) in jobs:
            if png.exists():
                png.unlink()
            cmd = [chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                   "--no-default-browser-check", "--mute-audio", f"--user-data-dir={profile}",
                   "--force-device-scale-factor=1", f"--window-size={width},{height + _EXTRA_HEIGHT}",
                   "--virtual-time-budget=5000", f"--screenshot={png}", _html_path(png).resolve().as_uri()]
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                cmd.insert(1, "--no-sandbox")  # Chrome refuses to start as root (servers, containers)
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if proc.returncode != 0 or not png.exists():
                raise RuntimeError(f"ساخت {png.name} نشد: {(proc.stderr or '')[-300:]}")
            if not _crop(png, width, height):
                log("⚠ Pillow نصب نیست؛ تصویر برش نخورد: pip install Pillow")
            size = _png_size(png)
            if size and size != (width, height):
                log(f"⚠ اندازه‌ی {png.name} {size[0]}×{size[1]} شد، نه {width}×{height}")


def make_reel(frames: list, out: Path, seconds: float = 3.0, music=None, log=print) -> bool:
    """Silent slideshow MP4 for Reels. Add the trending sound inside Instagram."""
    ffmpeg = env("FFMPEG_PATH") or shutil.which("ffmpeg")
    if not frames:
        return False
    if not ffmpeg:
        log("ffmpeg نصب نیست؛ ریلز ساخته نشد (نصب روی مک: brew install ffmpeg)")
        return False
    playlist = out.with_suffix(".txt")
    lines = []
    for frame in frames:
        lines += [f"file '{Path(frame).resolve().as_posix()}'", f"duration {seconds}"]
    lines.append(f"file '{Path(frames[-1]).resolve().as_posix()}'")  # concat demuxer needs the last frame twice
    playlist.write_text("\n".join(lines) + "\n", encoding="utf-8")
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(playlist)]
    if music:
        cmd += ["-i", str(music)]
    cmd += ["-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-movflags", "+faststart"]
    if music:
        cmd += ["-c:a", "aac", "-b:a", "160k", "-shortest"]
    cmd.append(str(out))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    finally:
        playlist.unlink(missing_ok=True)
    if proc.returncode != 0:
        log(f"⚠ ساخت ریلز نشد: {(proc.stderr or '')[-300:]}")
        return False
    return True
