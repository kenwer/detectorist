// Detectorist office-door poster.
// Build with scripts/build_poster.py (renders qr.png, then compiles this).
// Paper: A3 portrait. To switch to A4, change the `paper` below; the layout
// uses relative sizing so it reflows, but re-check the screenshot scale.

#let accent = rgb("#2bb3c2")      // teal-cyan sampled from the app icon
#let accent-dark = rgb("#12707d")
#let ink = rgb("#1c2b2a")
#let muted = rgb("#5c6b6a")
#let panel = rgb("#f2f9fa")
#let hairline = rgb("#d5e2e0")

#set page(
  paper: "a3",
  margin: (x: 22mm, y: 20mm),
)
#set text(
  font: ("Helvetica Neue", "Helvetica", "Arial"),
  fill: ink,
  size: 11pt,
)
#set par(leading: 0.62em)

// A labelled feature block; hero: true renders the wider, bolder variant
// used for the single headline capability.
#let feature(title, body, hero: false) = block(
  fill: panel,
  inset: if hero { 14pt } else { 11pt },
  radius: 6pt,
  width: 100%,
  stroke: if hero { (left: 3pt + accent) } else { none },
  stack(
    spacing: if hero { 16pt } else { 15pt },
    text(weight: "bold", size: if hero { 14pt } else { 12pt }, fill: accent-dark, title),
    text(size: if hero { 11pt } else { 10.5pt }, fill: muted, body),
  ),
)

// Header
#grid(
  columns: (34mm, 1fr),
  column-gutter: 8mm,
  align: horizon,
  image("/assets/icon.png", width: 34mm),
  stack(
    spacing: 23pt,
    text(size: 40pt, weight: "extralight", fill: muted)[Detectorist],
    text(size: 18pt, weight: "bold")[Sort and crop photos using local AI object detection],
  ),
)

#v(4pt)
#line(length: 100%, stroke: 1.5pt + accent)
#v(6pt)

// Intro
#text(size: 12.5pt)[
  A cross platform desktop application that uses machine learning for object detection and
  instance segmentation to sort and crop photos. It saves time when cropping similar objects
  across large batches of images, for example thousands of underwater photos of fish, or a
  season's worth of bee sightings, using confidence, aspect ratio, and padding settings you
  control.
]

#v(6pt)

// Screenshot
#block(
  radius: 6pt,
  clip: true,
  image("/docs/poster/screenshot.jpg", width: 100%),
)
#align(center, text(size: 9pt, fill: muted)[
  Fish segmentation with adjustable confidence, crop mode, and per-image EXIF metadata.
])

#v(8pt)

// Feature grid
#feature("Detect objects using local AI", hero: true)[
  Run bounding-box detection or instance segmentation with built-in detection transformer based models for fish,
  Apoidea (bees and similar looking insects). Confidence threshold and class
  filter update detections live.
]

#v(7pt)

#grid(
  columns: (1fr, 1fr),
  gutter: 7pt,
  feature("View images")[
    Load images from a local folder via drag & drop or the file dialog. Supports JPG, PNG, BMP,
    10-bit HEIF, and Sony RAW (.arw). An EXIF viewer shows camera, lens, exposure, and other
    metadata for the selected image.
  ],
  feature("Crop and sort")[
    Choose a crop mode (top confidence, union, most centered, each object), aspect ratio, and
    padding. Preview the effect on any selected image before running batch actions on the entire set.
  ],
  feature("Batch export")[
    Run Crop & Export or Group into Folders across your whole image list in one pass. Output
    lands in a `processed` subfolder alongside a detections CSV and settings JSON, both named
    for the confidence and model used.
  ],
  feature("Model Manager")[
    Browse, download, and update supported AI models without leaving the app. New detection
    and segmentation models can be added as they become available, and existing ones updated
    in place.
  ],
)

#v(1fr)

// Footer: how to get it
#line(length: 100%, stroke: 0.75pt + hairline)
#v(6pt)
#grid(
  columns: (1fr, 30mm),
  column-gutter: 8mm,
  align: horizon,
  [
    #text(weight: "bold", size: 13pt)[Get it]
    #v(3pt)
    Pre-built binaries for macOS, Windows, and Linux, as well as additional information, can
    be found at: \
    #text(weight: "bold", fill: accent-dark)[github.com/kenwer/detectorist]
    #v(10pt)
    #text(size: 9.5pt, fill: muted)[
      Ken Werner · ken.werner\@uni-tuebingen.de · AGPL-3.0 licensed
    ]
  ],
  align(center)[
    #image("/docs/poster/qr.png", width: 28mm)

    #text(size: 8pt, fill: muted)[scan for more info]
  ],
)
