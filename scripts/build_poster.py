#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["typst", "qrcode[pil]", "pillow"]
# ///
"""Builds the poster.

Generates a scan-to-download QR code, fetches the screenshot referenced in
the README if it's not already cached locally, then compiles poster.typ to
both a print-ready PDF and a PNG preview. The app icon is used straight from
assets/icon.png, no local copy needed. No system Typst install is needed:
the `typst` wheel ships the compiler, and uv runs this in a throwaway
environment.

    uv run scripts/build_poster.py
"""

import io
import os
import platform
import re
import subprocess
import urllib.request
from pathlib import Path

import qrcode
import typst
from PIL import Image

REPO_ROOT = Path(__file__).parent.parent
POSTER_DIR = REPO_ROOT / "docs" / "poster"
REPO_URL = "https://github.com/kenwer/detectorist#detectorist"
ACCENT = (43, 179, 194)  # teal-cyan sampled from the app icon

SCREENSHOT_PATH = POSTER_DIR / "screenshot.jpg"


def build_qr() -> None:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=12, border=1)
    qr.add_data(REPO_URL)
    qr.make(fit=True)
    img = qr.make_image(fill_color=ACCENT, back_color="white").convert("RGB")
    img.save(POSTER_DIR / "qr.png")


def fetch_screenshot() -> None:
    """Download the screenshot linked in the README, so the poster stays in sync with it."""
    if SCREENSHOT_PATH.exists():
        return
    readme = (REPO_ROOT / "README.md").read_text()
    match = re.search(r"!\[[^\]]*\]\((https://\S+)\)", readme)
    if not match:
        raise RuntimeError("Could not find a screenshot URL in README.md")
    with urllib.request.urlopen(match.group(1)) as response:
        data = response.read()
    # Re-save through Pillow so the file matches the .jpg extension poster.typ expects,
    # regardless of what format GitHub actually served it as.
    Image.open(io.BytesIO(data)).convert("RGB").save(SCREENSHOT_PATH, format="JPEG", quality=90)


def build_poster() -> None:
    src = POSTER_DIR / "poster.typ"
    # root=REPO_ROOT lets poster.typ reach assets/icon.png outside docs/poster/.
    typst.compile(src, output=POSTER_DIR / "poster.pdf", root=REPO_ROOT)
    # ppi 200 gives a crisp on-screen preview without a huge file.
    typst.compile(src, output=POSTER_DIR / "poster_preview_{n}.png", format="png", ppi=200, root=REPO_ROOT)


def open_pdf(path: Path) -> None:
    system = platform.system()
    if system == "Darwin":
        subprocess.run(["open", str(path)], check=True)
    elif system == "Windows":
        os.startfile(str(path))
    else:
        subprocess.run(["xdg-open", str(path)], check=True)


if __name__ == "__main__":
    build_qr()
    fetch_screenshot()
    build_poster()
    print("Wrote poster.pdf, poster_preview.png, and qr.png in", POSTER_DIR)
    open_pdf(POSTER_DIR / "poster.pdf")
