"""Strip local symbols from every Mach-O file in a macOS app bundle, then re-sign it.

The wheels ship their extensions unstripped. strip -x keeps the global symbols
that dlopen and the Python C API resolve. Stripping invalidates the signature
Nuitka wrote, so the bundle is re-signed ad hoc with the flags Nuitka uses.

Usage:
    python scripts/strip_macos_bundle.py dist/macos-arm64/Detectorist.app
"""

import subprocess
import sys
from pathlib import Path

# Thin 64-bit and fat (universal) Mach-O headers, as the first four bytes on disk
MACHO_MAGICS = (bytes.fromhex("cffaedfe"), bytes.fromhex("cafebabe"))


def find_machos(app: Path) -> list[Path]:
    machos = []
    for path in app.rglob("*"):
        if path.is_file() and not path.is_symlink():
            with path.open("rb") as f:
                if f.read(4) in MACHO_MAGICS:
                    machos.append(path)
    return machos


def main() -> None:
    app = Path(sys.argv[1])
    if not app.is_dir():
        raise SystemExit(f"Expected an app bundle, not found: {app}")
    machos = find_machos(app)
    before = sum(p.stat().st_size for p in machos)
    # Captured, since strip warns once per file that the signature becomes invalid
    result = subprocess.run(["strip", "-x", *machos], capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(f"strip failed:\n{result.stderr}")
    after = sum(p.stat().st_size for p in machos)
    print(f"Stripped {len(machos)} Mach-O files: {(before - after) // 2**20} MB saved")
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)], check=True)


if __name__ == "__main__":
    main()
