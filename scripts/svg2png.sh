#!/bin/bash

# Width and height defaults
WIDTH="512"
HEIGHT="512"

# Check if Inkscape is installed
if ! command -v inkscape &> /dev/null
then
    echo "Inkscape is not installed. Please install it first."
    exit 1
fi

# Check if an input file was provided
if [ $# -eq 0 ]; then
    echo "Usage: $0 <input.svg> [output.png] [width] [height]"
    exit 1
fi

# Input SVG file
INPUT_SVG="$1"

# Output PNG file (optional)
if [ $# -ge 2 ]; then
    OUTPUT_PNG="$2"
else
    # If no output specified, use input filename with .png extension
    OUTPUT_PNG="${INPUT_SVG%.*}.png"
fi

if [ $# -ge 3 ]; then
    WIDTH="--export-width=$3"
fi

if [ $# -ge 4 ]; then
    HEIGHT="--export-height=$4"
fi

# Convert SVG to PNG
inkscape "$INPUT_SVG" \
    --export-type=png \
    --export-filename="$OUTPUT_PNG" \
    $WIDTH \
    $HEIGHT

# Check if conversion was successful
if [ $? -eq 0 ]; then
    echo "Successfully converted $INPUT_SVG to $OUTPUT_PNG"
else
    echo "Error converting $INPUT_SVG to PNG"
    exit 1
fi
