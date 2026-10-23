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

// A labelled feature block.
#let feature(title, body, height: auto) = block(
  fill: panel,
  inset: 12pt,
  radius: 6pt,
  width: 100%,
  height: height,
  stroke: (left: 3pt + accent),
  stack(
    spacing: 14pt,
    text(weight: "bold", size: 13pt, fill: accent-dark, title),
    text(size: 11pt, fill: muted, body),
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
    text(size: 18pt, weight: "bold")[Find, crop and identify animals in large photo sets with local AI],
  ),
)

#v(4pt)
#line(length: 100%, stroke: 1.5pt + accent)
#v(6pt)

// Teaser
#text(size: 14pt)[
  Detectorist is a desktop application for macOS, Windows and Linux that finds, crops and identifies animals in large sets of photos. It runs the detection, segmentation and species classification models locally on your computer.
]

#v(6pt)

// Screenshot
#block(
  radius: 6pt,
  clip: true,
  image("/docs/poster/screenshot.jpg", width: 100%),
)
#align(center, text(size: 9pt, fill: muted)[
  Fish segmentation and species classification with detection and taxon thresholds, results table, and EXIF metadata.
])

#v(32pt)

// Use cases, copied verbatim from the README's About section.
#let use-cases = (
  ("screen large image sets for the animals you study", [
    such as the several thousand photos of a dive or a field day. A detection model locates
    every fish or Apoidea individual, tells sharp from out-of-focus ones, and separates the
    images with detections from those without.
  ]),
  ("need standardized crops of each detection", [
    with a fixed aspect ratio and padding, for photo-identification of individuals or as
    training data for other models.
  ]),
  ("want to know which species you photographed.", [
    A classifier assigns a family, genus and species to each detection and names it down to
    the deepest rank that reaches a user-set confidence threshold.
  ]),
  ("want to analyze the results further", [
    e.g. in R or Python. Each export writes CSV files with the detections and, with a
    classifier, the name and score at each rank. A settings file records the models and
    thresholds used, so the analysis can be reproduced.
  ]),
)

#text(size: 16pt, weight: "bold")[Detectorist is the right tool for you if you...]
#v(4pt)
// Typst cannot stretch a block to its grid row, so measure the tallest tile at
// the column width and give all four that height.
#layout(size => {
  let gutter = 7pt
  let column = (size.width - gutter) / 2
  let tallest = calc.max(..use-cases.map(((title, body)) => measure(
    feature(title, body),
    width: column,
  ).height))
  grid(
    columns: (1fr, 1fr),
    gutter: gutter,
    ..use-cases.map(((title, body)) => feature(title, body, height: tallest)),
  )
})

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
