#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = ["pillow"]
# ///
"""Convert a PNG to a multi-size ICO, used for assets/icon.ico in the Windows build.

Usage:
    scripts/png2ico.py assets/icon.png
    scripts/png2ico.py input.png -o output.ico -s 16 32 48 256
"""

import argparse
from pathlib import Path

from PIL import Image

# Windows picks 256 for large icons and Explorer's big views, the small ones for title bars and lists
DEFAULT_SIZES = [16, 24, 32, 48, 64, 128, 256]


def convert_to_ico(source: Path, target: Path, sizes: list[int]) -> None:
    Image.open(source).convert("RGBA").save(target, format="ICO", sizes=[(s, s) for s in sizes])
    print(f"Wrote {target} with sizes {sizes}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("input", type=Path, help="PNG file to convert")
    parser.add_argument("-o", "--output", type=Path, help="ICO file to write (default: input with .ico)")
    parser.add_argument("-s", "--sizes", nargs="+", type=int, default=DEFAULT_SIZES, help="Icon sizes in pixels")
    args = parser.parse_args()
    convert_to_ico(args.input, args.output or args.input.with_suffix(".ico"), args.sizes)


if __name__ == "__main__":
    main()
