#!/bin/bash
set -euo pipefail

# This script generates a Table of Contents (TOC) for markdown files using md-toc.

echo "Generating TOC for README.md..."
uv run md_toc --in-place --skip-lines 1 github README.md
echo "Generating TOC for FAQ.md..."
uv run md_toc --in-place --skip-lines 1 github FAQ.md
#echo "Generating TOC for CHANGELOG.md..."
#uv run md_toc --in-place github CHANGELOG.md
echo "TOC generation complete."
