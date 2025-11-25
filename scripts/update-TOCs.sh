#!/bin/bash
set -euo pipefail

# This script generates a Table of Contents (TOC) for markdown files using md-toc.

echo "Generating TOC for README.md..."
uv run md_toc --in-place --skip-lines 1 github README.md

echo "Generating TOC for FAQ.md..."
uv run md_toc --in-place --skip-lines 1 github FAQ.md

echo "Generating TOC for FAQ.md and inserting into README.md..."
export FAQ_TOC
FAQ_TOC=$(uv run md_toc --skip-lines 1 github FAQ.md | sed 's|](#|](FAQ.md#|g')
awk '
/<!-- FAQ_TOC_START -->/,/<!-- FAQ_TOC_END -->/ {
  if ($0 ~ /<!-- FAQ_TOC_START -->/) {
    print;
    print ENVIRON["FAQ_TOC"];
  }
  if ($0 ~ /<!-- FAQ_TOC_END -->/) {
    print;
  }
  next;
}
{ print }
' README.md > README.md.tmp && mv README.md.tmp README.md

#echo "Generating TOC for CHANGELOG.md..."
#uv run md_toc --in-place github CHANGELOG.md
echo "TOC generation complete."
