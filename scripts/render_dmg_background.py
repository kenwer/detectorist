#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = ["PySide6-Essentials>=6.12"]
# ///
"""Render the macOS DMG background SVG to the 1x and 2x PNGs dmgbuild combines.

dmgbuild finds dmg-background@2x.png next to dmg-background.png and merges both into
one HiDPI TIFF, so Retina displays get a sharp window background.

Usage:
    scripts/render_dmg_background.py
"""

import os
import sys
from pathlib import Path

from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

SOURCE = Path(__file__).resolve().parent.parent / "packaging" / "macos" / "dmg-background.svg"


def render(renderer: QSvgRenderer, scale: int, target: Path) -> None:
    size = renderer.defaultSize() * scale
    # Opaque, the SVG's background rect covers the whole image
    image = QImage(size, QImage.Format.Format_RGB32)
    # tiffutil -cathidpicheck rejects a pair whose DPI ratio does not match the pixel ratio
    dots_per_meter = round(72 * scale / 0.0254)
    image.setDotsPerMeterX(dots_per_meter)
    image.setDotsPerMeterY(dots_per_meter)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    renderer.render(painter)
    painter.end()
    if not image.save(str(target)):
        sys.exit(f"Could not write {target}")
    print(f"Wrote {target} ({size.width()}x{size.height()})")


def main() -> None:
    # Text rendering needs a QGuiApplication for the font database, but no window or display
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    _app = QGuiApplication(sys.argv)
    renderer = QSvgRenderer(str(SOURCE))
    if not renderer.isValid():
        sys.exit(f"Could not parse {SOURCE}")
    render(renderer, 1, SOURCE.with_suffix(".png"))
    render(renderer, 2, SOURCE.with_name(f"{SOURCE.stem}@2x.png"))


if __name__ == "__main__":
    main()
