# Detectorist

<!--TOC-->

- [About](#about)
- [Download](#download)
- [Key features](#key-features)
- [Using Detectorist](#using-detectorist)
  - [Typical usage scenario](#typical-usage-scenario)
  - [Keyboard shortcuts](#keyboard-shortcuts)
- [FAQ](#faq)
- [AI model info](#ai-model-info)
  - [Detection models](#detection-models)
  - [Segmentation models](#segmentation-models)
  - [All models](#all-models)
- [Changelog](#changelog)
- [Roadmap/TODOs](#roadmaptodos)
- [Development](#development)
- [Acknowledgements](#acknowledgements)
- [Citation](#citation)
- [License](#license)

<!--TOC-->

## About

Detectorist is a multi platform desktop application that uses machine learning for object detection and instance segmentation to sort and crop photos. The main use case is to save time when cropping similar objects across a large number of images by using local AI. For example, imagine returning from a diving session with thousands of photos of fish and wanting to quickly crop them for better viewing. Or, if you're into bees and want to discard any images that don't contain bees or similar looking insects. This niche application allows you to do that with adjustable parameters like confidence, aspect ratio, and padding. Detectorist supports various image formats, including JPG, PNG, BMP, 10 bit HEIF, and Sony RAW (.arw) files.

![Main application interface](https://github.com/user-attachments/assets/2735df96-1f1a-4e36-a3be-a6f1da4b3eed)


## Download

Download the binary for your operating system and start the application.
* macOS (Apple Silicon with macOS >=26): [Detectorist-macos-arm64.zip](https://github.com/kenwer/detectorist/releases/latest/download/Detectorist-macos-arm64.zip)
  * Note: The macOS app is not signed with a certificate from the Apple Developer Program. But you can still open the app as described in the [FAQ](FAQ.md).
  * Note: Intel Macs are no longer supported. The last release with an Intel build is [v0.11.0](https://github.com/kenwer/detectorist/releases/tag/v0.11.0).
* Windows (x86_64): [Detectorist-windows-x86_64.zip](https://github.com/kenwer/detectorist/releases/latest/download/Detectorist-windows-x86_64.zip)
  * Note: The compiled Windows executable is not signed and since it extracts additional contents to load afterwards it's common that Anti Virus/Malware tools like Defender detect the application as malicious.
  * Note: Windows aarch64 is not supported [yet](https://github.com/microsoft/onnxruntime/issues/27123) because `onnxruntime` doesn't provide wheels for that platform. Windows ARM users might use the x86_64 version via emulation.
* Linux (x86_64): [Detectorist-linux-x86_64.tar.gz](https://github.com/kenwer/detectorist/releases/latest/download/Detectorist-linux-x86_64.tar.gz)
* Linux (aarch64): [Detectorist-linux-aarch64.tar.gz](https://github.com/kenwer/detectorist/releases/latest/download/Detectorist-linux-aarch64.tar.gz)
  * Note: On Linux you can also easily run Detectorist from the source as described below.


## Key features

*   **Image Browser:** Load and browse images from a local folder using drag & drop.
*   **Detect, segment, and crop objects using AI:** Run object detection or instance segmentation using ONNX models.
*   **Adjustable Confidence Threshold:** Interactively change confidence to see the effect on detections in real-time.
*   **Filter by object class:** Filter detections by object class. The filter applies to the displayed detections and to exports.
*   **Multiple Image Formats:** Supports common image formats like PNG, JPG, BMP, and also 10 bit HEIC/HEIF or Sony RAW (.ARW).
*   **EXIF Data Viewer:** Displays selected EXIF metadata for the current image.
*   **Export named copies:** Export crops or whole images, each named after its taxa (with a classifier), its detected class, or both.
*   **Configurable aspect ratio for cropping:** with 3:2, 4:4, 16:9, plus support for padding.
*   **CSV log when processing multiple images:** Write log file to the output directory providing information about the detections like the number of detected objects and the highest confidence score.
*   **Model Manager:** Browse, download, and update models from the project page.
*   **Settings persistence:** Application settings are saved and restored between sessions. Settings can also be imported/exported as JSON files.


## Using Detectorist

### Typical usage scenario
*   On first launch, the application will prompt you to download models. Alternatively open the model manager via `File -> Manage Models...` to browse, download, or update available models.
*   In the main UI select the AI model you want to use from the drop down list at the top right.
*   Go to `File -> Open Folder...` or simply drag and drop a folder containing images onto the application window.
*   The folder will be scanned for supported images and the first image will be loaded.
*   The AI model will automatically run, and detection boxes will be drawn on the image.
*   Click on an iamge-item in the list on the left or use the arrow keys to navigate through the image set.
*   Use the slider and spin-box on the right to adjust the **Confidence** threshold. Detections will update automatically.
    * The Confidence threshold specifies the minimum confidence how sure the model must be about detecting an object before it reports that detection.
*   Optionally configure the crop mode, aspect ratio and padding, then choose `Export Images...` in the File menu (`Ctrl+E`). The Export dialog previews the files and lets you choose:
    * All images, or only the selected ones.
    * Whether to crop each detection (`Fish_IMG_0042_crop.jpg`) or copy the whole image (`Fish_IMG_0042.jpg`).
    * What the file names start with: the class, the taxa (with a classifier), both, or nothing (`Fish_in-focus_Pomacentridae_Amphiprion_ocellaris_IMG_0042_crop.jpg`). Taxa name every rank that reaches the taxon confidence and `unidentified` for the rest (`Pomacentridae_Amphiprion_unidentified_IMG_0042_crop.jpg`). Detections of a class the classifier does not name keep their class instead. Images without detections start with `no-detection_`.
    * The output folder: a `processed` subdirectory of the image folder, or another folder. The original images are never changed.
    * Only the detections of the class chosen in `Show` are exported, as the dialog notes.
    * Files from an earlier export are overwritten where the names match and kept otherwise.
    * Next to the images go `detectorist-detections.csv`, `detectorist-classification.csv` (with a classifier) and `detectorist-settings.json`, which records the settings used, such as models, confidence levels and the Show filter. Import it with `Import Settings...` in the File menu to repeat the export.

### Keyboard shortcuts

The keyboard shortcuts can be found at the [Keyboard shortcuts page](SHORTCUTS.md). They are also available from the app's `Help -> Keyboard Shortcuts` menu.


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
* **Fish Segmentation (Focus-Aware)** - Locates fish using a transformer-based instance segmentation model with two classes that separate in-focus from out-of-focus fish.
* **Apoidea Segmentation (Focus-Aware)** - Locates bees, wasps, and related Apoidea species using a transformer-based instance segmentation model with two classes that separate in-focus from out-of-focus individuals.

Both models are based on the DETR (DEtection TRansformer) architecture.

| Model | Parameters | Input size | Class indexing | Classes |
|---|---|---|---|---|
| **Fish Segmentation (Focus-Aware)** | 36.2 M | 504px | 0-indexed | `[0]: 'Fish'`, `[1]: 'Fish_out-of-focus'` |
| **Apoidea Segmentation (Focus-Aware)** | 36.2 M | 504px | 0-indexed | `[0]: 'Apoidea_in-focus'`, `[1]: 'Apoidea_out-of-focus'` |


## Changelog

The changelog can be found at the [CHANGELOG page](CHANGELOG.md).


## Roadmap/TODOs

* Add more and improved models.
* Allow specifying a custom output directory for actions.


## Development

For instructions on how to run the application from source, build the distributables, or view the changelog, please see the [DEVELOPMENT.md](DEVELOPMENT.md) file.

## Acknowledgements

The author would like to thank the following projects and people that made this work possible:

* The High Performance and Cloud Computing Group at the Zentrum für Datenverarbeitung, University of Tübingen, for providing computing resources via [bwForCluster BinAC 2](https://uni-tuebingen.de/en/einrichtungen/zentrum-fuer-datenverarbeitung/dienstleistungen/server/computing/resources/bwforcluster-binac-2/), funded by the state of Baden-Württemberg through bwHPC and the German Research Foundation (DFG) under Project number 455787709.
* [RF-DETR](https://github.com/roboflow/rf-detr) (Robinson et al., [arXiv:2511.09554](https://arxiv.org/abs/2511.09554), 2025) for powering object detection.
* [Prof. Dr. Nico Michiels](https://uni-tuebingen.de/en/fakultaeten/mathematisch-naturwissenschaftliche-fakultaet/fachbereiche/biologie/institute/evolution-und-oekologie/lehrbereiche/animal-evolutionary-ecology/people/nico-michiels/) (University of Tübingen) for providing thousands of images used for training the fish models.
* [Dr. Anja Buttstedt](https://uni-tuebingen.de/fakultaeten/mathematisch-naturwissenschaftliche-fakultaet/fachbereiche/biologie/institute/evolution-und-oekologie/lehrbereiche/vergleichende-zoologie/gruppe/anja-buttstedt/) for Apoidea images and testing the Windows version.

Many thanks also to the people behind the projects Detectorist builds on:

* [ONNX Runtime](https://onnxruntime.ai/)
* [Qt](https://www.qt.io/) / [PySide6](https://doc.qt.io/qtforpython/)
* [Python](https://www.python.org)
* [OpenCV](https://opencv.org)
* [NumPy](https://numpy.org)
* [Pillow](https://python-pillow.org) / [pillow-heif](https://github.com/bigcat88/pillow_heif) / [libheif](https://github.com/strukturag/libheif)
* [rawpy](https://github.com/letmaik/rawpy) / [LibRaw](https://www.libraw.org)
* [piexif](https://github.com/hMatoba/Piexif)
* [pyqt-toast-notification](https://github.com/niklashenning/pyqttoast)
* [Nuitka](https://nuitka.net)
* [uv](https://docs.astral.sh/uv/)

## Citation

If you use Detectorist in your work, you can [cite](CITATION.cff). it:

```bibtex
@software{Werner_Detectorist_2026,
  author  = {Werner, Ken},
  title   = {Detectorist},
  url     = {https://github.com/kenwer/detectorist},
  version = {0.12.0},
  year    = {2026}
}
```

## License

This project is licensed under the AGPL-3.0 license. See the LICENSE file for the full text.
