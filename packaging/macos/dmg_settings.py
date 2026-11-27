# dmgbuild settings, executed by dmgbuild with `defines` holding the -D values.
# Usage: dmgbuild -s packaging/macos/dmg_settings.py -D app=<path to Detectorist.app> Detectorist <out.dmg>
# dmgbuild writes the window layout into .DS_Store itself, so no Finder or AppleScript is needed
# and it runs on a headless CI runner.
# Relative paths resolve against the working directory, the repo root when run by poe build-mac,
# because dmgbuild does not set __file__ for this file.

import os.path

# dmgbuild runs this file with its options dict as globals, so `defines` exists only at run time
app = globals()["defines"]["app"]
app_name = os.path.basename(app)

# ULMO (LZMA) makes the DMG about 30% smaller than ULFO (LZFSE) and needs macOS 10.15, below what Qt 6 requires.
format = "ULMO"
filesystem = "HFS+"

files = [app]
symlinks = {"Applications": "/Applications"}

# dmgbuild merges dmg-background@2x.png from the same folder into a HiDPI TIFF.
# Edit dmg-background.svg and rerun scripts/render_dmg_background.py to change it.
background = "packaging/macos/dmg-background.png"

# The bounds include the title bar, so 428 leaves a content area of about 400 over the 660x430
# background. The position is only where the window first opens.
window_rect = ((200, 160), (660, 428))
show_toolbar = False
show_sidebar = False
show_status_bar = False
show_pathbar = False

icon_size = 128
text_size = 13
# Icon centres, which the arrow in dmg-background.svg lines up with
icon_locations = {
    app_name: (165, 180),
    "Applications": (495, 180),
}
hide_extensions = [app_name]
