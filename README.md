# Detectorist
<!--TOC-->

- [About](#about)
- [Download](#download)
- [Key features](#key-features)
- [Using Detectorist](#using-detectorist)
  - [Typical usage scenario](#typical-usage-scenario)
  - [Keyboard shortcuts](#keyboard-shortcuts)
    - [Global shortcuts](#global-shortcuts)
    - [Image navigation shortcuts](#image-navigation-shortcuts)
    - [Shortcuts that operate on a set of selected images](#shortcuts-that-operate-on-a-set-of-selected-images)
- [FAQ](#faq)
- [AI model info](#ai-model-info)
  - [Segmentation models](#segmentation-models)
  - [Classification models](#classification-models)
- [Changelog](#changelog)
- [Roadmap/TODOs](#roadmaptodos)
- [Development](#development)
- [Acknowledgements](#acknowledgements)
- [Citation](#citation)
- [License](#license)

<!--TOC-->

## About
Detectorist is a desktop application for macOS, Windows and Linux that finds, crops and identifies animals in large sets of photos. It runs the detection, segmentation and species classification models locally on your computer. Models are currently available for fish and Apoidea. The fish classifier covers the species of the Sulawesi area. The application supports various image formats, including JPG, PNG, BMP, 10-bit HEIF, and Sony RAW (.arw) files.

Detectorist is the right tool for you if you:
- **screen large image sets for the animals you study**, such as the several thousand photos of a dive or a field day. A detection model locates every fish or Apoidea individual, tells sharp from out-of-focus ones, and separates the images with detections from those without.
- **need standardized crops of each detection**, with a fixed aspect ratio and padding, for photo-identification of individuals or as training data for other models.
- **want to know which species you photographed.** A classifier assigns a family, genus and species to each detection and names it down to the deepest rank that reaches a user-set confidence threshold.
- **want to analyze the results further**, e.g. in R or Python. Each export writes CSV files with the detections and, with a classifier, the name and score at each rank. A settings file records the models and thresholds used, so the analysis can be reproduced.

Note: The classifiers only know the species they were trained on (see [AI model info](#ai-model-info)). The identifications are suggestions to be verified by an expert.

![Main application interface](https://github.com/user-attachments/assets/8ba0c70e-4824-4b45-9ea9-49d1cb9d1b5d)


## Download
Download the binary for your operating system and start the application.
- macOS (Apple Silicon with macOS >=26): [Detectorist-macos-arm64.zip](https://github.com/kenwer/detectorist/releases/latest/download/Detectorist-macos-arm64.zip)
  - Note: The macOS app is not signed with a certificate from the Apple Developer Program. But you can still open the app as described in the [FAQ](FAQ.md).
  - Note: Intel Macs are no longer supported. The last release with an Intel build is [v0.11.0](https://github.com/kenwer/detectorist/releases/tag/v0.11.0).
- Windows (x86_64): [Detectorist-windows-x86_64.zip](https://github.com/kenwer/detectorist/releases/latest/download/Detectorist-windows-x86_64.zip)
  - Note: The compiled Windows executable is not signed and since it extracts additional contents to load afterwards it's common that Anti Virus/Malware tools like Defender detect the application as malicious.
  - Note: Windows aarch64 is not supported [yet](https://github.com/microsoft/onnxruntime/issues/27123) because `onnxruntime` doesn't provide wheels for that platform. Windows ARM users might use the x86_64 version via emulation.
- Linux (x86_64): [Detectorist-linux-x86_64.tar.gz](https://github.com/kenwer/detectorist/releases/latest/download/Detectorist-linux-x86_64.tar.gz)
- Linux (aarch64): [Detectorist-linux-aarch64.tar.gz](https://github.com/kenwer/detectorist/releases/latest/download/Detectorist-linux-aarch64.tar.gz)
  - Note: On Linux you can also easily run Detectorist from the source as described below.


## Key features
-   **Image browser:** Open a folder, or drop it onto the window to step through its images. The app reads JPG, PNG, BMP, 10-bit HEIC/HEIF and Sony RAW (.arw).
-   **Detection and segmentation:** Bounding box and instance mask are shown for each individual.
-   **Species classification:** Names family, genus and species for each detection, each with its own score.
-   **Adjustable thresholds:** Detection and taxon confidence thresholds can be changed interactively to see the effect on detection and classification in real time.
-   **Class filter:** Restricts the displayed and exported detections to one class, e.g. in-focus individuals only.
-   **Results table:** Lists the detections of the current image with their class, taxa and scores.
-   **Cropping:** Various cropping setting (e.g crop of the most centered or best classified species. Padding can be adjusted.
-   **Export:** Crops or whole images, named after their taxa, their class, or both.
-   **CSV data:** `detectorist-detections.csv` has one row per image, and `detectorist-classification.csv` one row per detection, its bounding box, and the name and score at each rank.
-   **Reproducibility:** `detectorist-settings.json` records the models, thresholds and class filter of an export and can be imported to repeat it.
-   **EXIF metadata:** Shows camera, lens, date, GPS coordinates and exposure settings of the current image.
-   **Exposure correction:** Optionally compensates the camera's exposure bias in the displayed and exported images.
-   **Model Manager:** Download, update and remove the models you need.

## Using Detectorist
### Typical usage scenario
-   On first launch, the application will prompt you to download models. Alternatively open the model manager via `File -> Manage Models...` to browse, download, or update available models.
-   In the main UI select the AI model you want to use from the drop down list at the top right.
-   Go to `File -> Open Folder...` or simply drag and drop a folder containing images onto the application window.
-   The folder will be scanned for supported images and the first image will be loaded.
-   The AI model will automatically run, and detection boxes will be drawn on the image.
-   Click on an image item in the list on the left or use the arrow keys to navigate through the image set.
-   Use the slider and spin-box on the right to adjust the **Confidence** threshold. Detections will update automatically.
    - The Confidence threshold specifies the minimum confidence how sure the model must be about detecting an object before it reports that detection.
-   Optionally configure the crop mode, aspect ratio and padding, then choose `Export Images...` in the File menu (`Ctrl+E`). The Export dialog previews the files and lets you choose:
    - All images, or only the selected ones.
    - Whether to crop each detection (`Fish_IMG_0042_crop.jpg`) or copy the whole image (`Fish_IMG_0042.jpg`).
    - What the file names start with: the class, the taxa (with a classifier), both, or nothing (`Fish_in-focus_Pomacentridae_Amphiprion_ocellaris_IMG_0042_crop.jpg`). Taxa name every rank that reaches the taxon confidence and `unidentified` for the rest (`Pomacentridae_Amphiprion_unidentified_IMG_0042_crop.jpg`). Detections of a class the classifier does not name keep their class instead. Images without detections start with `no-detection_`.
    - The output folder: a `processed` subdirectory of the image folder, or another folder. The original images are never changed.
    - Only the detections of the class chosen in `Show` are exported, as the dialog notes.
    - Files from an earlier export are overwritten where the names match and kept otherwise.
    - Next to the images go `detectorist-detections.csv`, `detectorist-classification.csv` (with a classifier) and `detectorist-settings.json`, which records the settings used, such as models, confidence levels and the Show filter. Import it with `Import Settings...` in the File menu to repeat the export.

### Keyboard shortcuts
The shortcuts are also listed in the app's `Help -> Keyboard Shortcuts` menu.

#### Global shortcuts
| Windows | Linux | macOS | Action | Description |
| --- | --- | --- | --- | --- |
| Ctrl+O         | Ctrl+O         | ⌘O  | **Open Image(s)...** | Brings up the file dialog to load one or more images |
| Shift+Ctrl+O   | Shift+Ctrl+O   | ⇧⌘O | **Open Folder...** | Brings up the file dialog to open an entire folder with images |
| Ctrl+E         | Ctrl+E         | ⌘E  | **Export Images...** | Opens the Export dialog to export all or the selected images, as crops or whole, named by taxon or class |
| Shift+Ctrl+M   | Shift+Ctrl+M   | ⇧⌘M | **Manage Models...** | Opens the Manage Models dialog to download, update or remove detection models |
| Ctrl+Backspace | Ctrl+Backspace | ⌘⌫  | **Clear Image List** | Clears the list of loaded images |
| Alt+F4         | Ctrl+Q         | ⌘Q  | **Quit** | Quits Detectorist |
| Ctrl+/, F1     | Ctrl+/, F1     | ⌘/, ⌘? | **Keyboard Shortcuts** | Shows this list of shortcuts |
| B              | B              | B   | **Show Boxes** | Toggles the visibility of the bounding boxes of detected objects |
| L              | L              | L   | **Show Labels** | Toggles the visibility of the labels naming the family, genus or species of classified objects |
| M              | M              | M   | **Show Masks** | Toggles the visibility of the segmentation masks of detected objects |
| H              | H              | H   | **Show/Hide All** | Hides the boxes, labels, and masks if any of them are shown, otherwise shows all of them |

#### Image navigation shortcuts
| Windows | Linux | macOS | Action | Description |
| --- | --- | --- | --- | --- |
| Right, Down                | Right, Down                | ➡︎, ⬇︎           | **Next Image** | Jumps to the next image in the list |
| Left, Up                   | Left, Up                   | ⬅︎, ⬆︎           | **Previous Image** | Jumps to the previous image in the list |
| Home, Ctrl+Left, Ctrl+Up   | Home, Ctrl+Left, Ctrl+Up   | Fn⬅︎, ⌘⬅︎, ⌘⬆︎ | **First Image** | Jumps to the first image in the list |
| End, Ctrl+Right, Ctrl+Down | End, Ctrl+Right, Ctrl+Down | Fn➡︎, ⌘➡︎, ⌘⬇︎ | **Last Image** | Jumps to the last image in the list |

#### Shortcuts that operate on a set of selected images
| Windows | Linux | macOS | Action | Description |
| --- | --- | --- | --- | --- |
| Ctrl+R            | Ctrl+R            | ⌘R    | **Reveal in File Manager** | Shows the image in its folder |
| Ctrl+C            | Ctrl+C            | ⌘C    | **Copy Filenames to Clipboard** | Puts the filenames of the selected image(s) into your clipboard |
| Del, Backspace    | Del, Backspace    | ⌫, ⌦ | **Remove selected Images from List** | Removes the selected image(s) from the list (not deleted, just removed from the view) |


## FAQ
Frequently asked questions can be found at the [FAQ page](FAQ.md).
<!-- FAQ_TOC_START -->
- [Q1: When starting the app on macOS, how do I get past the  "*Detectorist.app Not Opened*" message?](FAQ.md#q1-when-starting-the-app-on-macos-how-do-i-get-past-the--detectoristapp-not-opened-message)
- [Q2: When starting the Windows executable, how do I get past the "*Windows protected your PC*" / "*Don't run*" message?](FAQ.md#q2-when-starting-the-windows-executable-how-do-i-get-past-the-windows-protected-your-pc--dont-run-message)
- [Q3: How do I reset the application settings?](FAQ.md#q3-how-do-i-reset-the-application-settings)
  - [macOS:](FAQ.md#macos)
  - [Windows:](FAQ.md#windows)
  - [Linux:](FAQ.md#linux)
<!-- FAQ_TOC_END -->


## AI model info
### Segmentation models
- **Fish Segmentation (Focus-Aware)** - Locates fish using a transformer-based instance segmentation model with two classes that separate in-focus from out-of-focus fish.
- **Apoidea Segmentation (Focus-Aware)** - Locates bees, wasps, and related Apoidea species using a transformer-based instance segmentation model with two classes that separate in-focus from out-of-focus individuals.

Both models are based on the DETR (DEtection TRansformer) architecture.

| Model | Parameters | Precision | Input size | Class indexing | Classes |
|---|---|---|---|---|---|
| **Fish Segmentation (Focus-Aware)** | 32.5 M | FP32 | 504px | 0-indexed | `[0]: 'Fish'`, `[1]: 'Fish_out-of-focus'` |
| **Apoidea Segmentation (Focus-Aware)** | 32.5 M | FP32 | 504px | 0-indexed | `[0]: 'Apoidea_in-focus'`, `[1]: 'Apoidea_out-of-focus'` |

The fish models are trained on underwater photos from University of Tübingen field courses. The Apoidea models are trained on photos from iNaturalist.

### Classification models
- **Sulawesi Fish Species Classification** - Names the family, genus and species of each detected fish. Knows 1196 species in 359 genera and 82 families. Used together with a fish segmentation model.
- **Apoidea Species Classification** - Names the family, genus and species of each detected bee or apoid wasp. Knows 3147 species in 377 genera and 11 families. Used together with an Apoidea segmentation model.

Both classifiers are fine-tuned from BioCLIP 2 (ViT-L/14) and look at a 224px crop around each detection. Their weights are stored as 16-bit floats (FP16), which halves the download size compared to FP32. The FP16 models pick the same species as the full-precision model on 99.9% of validation crops. 8-bit quantization (INT8) agreed on only about 95% and is not used.

| Model | Parameters | Precision | Input size | Classifies | Families | Genera | Species |
|---|---|---|---|---|---|---|---|
| **Sulawesi Fish Species Classification** | 305.8 M | FP16 | 224px | `Fish*` | 82 | 359 | 1196 |
| **Apoidea Species Classification** | 308.8 M | FP16 | 224px | `Apoidea*` | 11 | 377 | 3147 |


## Changelog
The changelog can be found at the [CHANGELOG page](CHANGELOG.md).


## Roadmap/TODOs
- Add more and improved models.


## Development
For instructions on how to run the application from source, build the distributables, or view the changelog, please see the [DEVELOPMENT.md](DEVELOPMENT.md) file.

## Acknowledgements
Many thanks to the following projects and people that made this work possible:

- The High Performance and Cloud Computing Group at the Zentrum für Datenverarbeitung, University of Tübingen, for providing computing resources via [bwForCluster BinAC 2](https://uni-tuebingen.de/en/einrichtungen/zentrum-fuer-datenverarbeitung/dienstleistungen/server/computing/resources/bwforcluster-binac-2/), funded by the state of Baden-Württemberg through bwHPC and the German Research Foundation (DFG) under Project number 455787709.
- [Prof. Dr. Nico Michiels](https://uni-tuebingen.de/en/fakultaeten/mathematisch-naturwissenschaftliche-fakultaet/fachbereiche/biologie/institute/evolution-und-oekologie/lehrbereiche/animal-evolutionary-ecology/people/nico-michiels/) (University of Tübingen) and the participants of the university's marine biodiversity field courses for the more than 40,000 identified underwater photos from Indonesia and Egypt used for training the fish models.
- [Dr. Anja Buttstedt](https://uni-tuebingen.de/fakultaeten/mathematisch-naturwissenschaftliche-fakultaet/fachbereiche/biologie/institute/evolution-und-oekologie/lehrbereiche/vergleichende-zoologie/gruppe/anja-buttstedt/) for Apoidea images and testing the Windows version.
- [iNaturalist](https://www.inaturalist.org) and its community of observers and identifiers.
- [RF-DETR](https://github.com/roboflow/rf-detr) (Robinson et al., [arXiv:2511.09554](https://arxiv.org/abs/2511.09554), 2025)
- [BioCLIP 2](https://imageomics.github.io/bioclip-2/) (Gu et al., [arXiv:2505.23883](https://arxiv.org/abs/2505.23883), 2025)
- [SAM 3](https://ai.meta.com/sam3/) (Carion et al., [arXiv:2511.16719](https://arxiv.org/abs/2511.16719), 2025)
- [CVAT](https://www.cvat.ai)
- [ONNX Runtime](https://onnxruntime.ai/)
- [Qt](https://www.qt.io/) / [PySide6](https://doc.qt.io/qtforpython/)
- [Python](https://www.python.org)
- [OpenCV](https://opencv.org)
- [NumPy](https://numpy.org)
- [Pillow](https://python-pillow.org) / [pillow-heif](https://github.com/bigcat88/pillow_heif) / [libheif](https://github.com/strukturag/libheif)
- [rawpy](https://github.com/letmaik/rawpy) / [LibRaw](https://www.libraw.org)
- [piexif](https://github.com/hMatoba/Piexif)
- [pyqt-toast-notification](https://github.com/niklashenning/pyqttoast)
- [Nuitka](https://nuitka.net)
- [uv](https://docs.astral.sh/uv/)

## Citation
If you use Detectorist in your work, you can [cite](CITATION.cff) it:

```bibtex
@software{Werner_Detectorist_2026,
  author  = {Werner, Ken},
  title   = {Detectorist},
  url     = {https://github.com/kenwer/detectorist},
  version = {0.13.0},
  year    = {2026}
}
```

## License
This project is licensed under the AGPL-3.0 license. See the LICENSE file for the full text.
