# Detectorist

<!--TOC-->

- [About](#about)
- [Download](#download)
- [Key features](#key-features)
- [Using Detectorist](#using-detectorist)
  - [Typical usage scenario](#typical-usage-scenario)
  - [Keyboard shortcuts](#keyboard-shortcuts)
    - [Global shortcuts](#global-shortcuts)
    - [Shortcuts that operate on a set of selected images](#shortcuts-that-operate-on-a-set-of-selected-images)
    - [Image navigation shortcuts](#image-navigation-shortcuts)
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
* macOS (Apple Silicon): [Detectorist-macos-arm64.zip](https://github.com/kenwer/detectorist/releases/latest/download/Detectorist-macos-arm64.zip)
* macOS (Intel): [Detectorist-macos-x86_64.zip](https://github.com/kenwer/detectorist/releases/latest/download/Detectorist-macos-x86_64.zip)
  * Note: The macOS apps are not signed with a certificate from the Apple Developer Program. But you can still open the app as described in the [FAQ](FAQ.md).
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
*   **Filter by object class:** Filter displayed detections by object class using.
*   **Multiple Image Formats:** Supports common image formats like PNG, JPG, BMP, and also 10 bit HEIC/HEIF or Sony RAW (.ARW).
*   **EXIF Data Viewer:** Displays selected EXIF metadata for the current image.
*   **Save cropped copies:** Automatically isolate detected objects in all loaded images.
*   **Configurable aspect ratio for cropping:** with 3:2, 4:4, 16:9, plus support for padding.
*   **Sort into subfolder:** Detect object classes and sort images into corresponding sub folders.
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
*   You can sort the images into sub folders that are named after the detected object class using the corresponding item in the Actions menu. The images are copied, not moved.
*   Optionally configure the crop & padding settings, then start cropping via the Actions menu.
    * The cropped and sorted images all land in a `processed` subdirectory of the directory that is currently being viewed.
    * Cropped images keep their original filename with a `_crop` suffix. Images without a usable detection are copied in with a `_ncrop` suffix instead.
    * The accompanying detections CSV and exported settings JSON encode the confidence level and model used in their filenames (like: `detectorist-detections-conf-75-fish-seg-transformer-2026-02-24.csv`).

### Keyboard shortcuts

#### Global shortcuts
| Windows/Linux | macOS | Action | Decription |
| --- | --- | --- | --- |
| Ctrl+O          | ⌘O  | **Open Image(s)...** | Brings up the file dialog to load one or more images |
| Shift+Ctrl+O    | ⇧⌘O | **Open Folder...** | Brings up the file dialog to open an entire folder with images |
| Ctrl+Backspace | ⌘⌫  | **Clear Image List** | Clears the list of loaded images |
| Shift+Ctrl+G    | ⇧⌘G | **Group Images into Folders** | Starts a batch process that groups all images by its detected object classes into individual sub folders |
| Shift+Ctrl+E    | ⇧⌘E | **Crop & Export all Images** | Starts a batch process that crops and exports all loaded images into a subfolder |

#### Shortcuts that operate on a set of selected images
| Windows/Linux | macOS | Action | Decription |
| --- | --- | --- | --- |
| Ctrl+L    | ⌘L | **Locate Image in Filemanager** | Locates the image in your filemanager |
| Ctrl+C    | ⌘C | **Copy selected Filenames to Clipboard**| Puts the filenames of the selected image(s) into your clipboard |
| Ctrl+E    | ⌘E | **Crop & Export selected Images** | Starts a batch process that crops and exports the selected images into a subfolder |
| Alt+E     | ⌥E | **Crop & Export & Remove selected Images from List** | Starts a batch process that crops and exports the selected image(s) into a subfolder and also removes the image(s) from the list |
| Backspace | ⌫  | **Remove selected Image from List** | Removes the selected image(s) from the list (not deleted, just removed from the view) |

#### Image navigation shortcuts
| Windows/Linux | macOS | Action | Decription |
| --- | --- | --- | --- |
| Right      | ➡︎  | **Next Image** | Jumps to the next image in the list, same as Down / ⬇︎ |
| Left       | ⬅︎  | **Previous Image** | Jumps to the previous image in the list, same as Up / ⬆︎ |
| Ctrl+Right | ⌘➡︎ | **Last Image** | Jumps to the last image in the list, same as Ctrl+Down / ⌘⬇︎ |
| Ctrl+Left  | ⌘⬅︎ | **First Image** | Jumps to the first image in the list, same as Ctrl+Up / ⌘⬆︎ |
| Down       | ⬇︎  | **Next Image** | Jumps to the next image in the list, same as Right / ➡︎ |
| Up         | ⬆︎  | **Previous Image** | Jumps to the previous image in the list, same as Left / ⬅︎ |
| Ctrl+Down  | ⌘⬇︎ | **Last Image** | Jumps to the last image in the list, same as Ctrl+Right / ⌘➡︎ |
| Ctrl+Up    | ⌘⬆︎ | **First Image** | Jumps to the first image in the list, same as Ctrl+Left / ⌘⬅︎ |


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

### Detection models
* **Fish Detection** - Locates fish using a transformer-based bounding box detection model. Best for batch sorting and cropping.
  * Trained for 25 epochs on 25641 images of fish (98247 annotations).
* **Apoidea Detection** - Locates bees, wasps, and related Apoidea species using a transformer-based bounding box detection model. Best for batch sorting and cropping.
  * Trained for 32 epochs on 25141 images of Apoidea (30505 annotations).
* **Generic Object Detection** - Detects 80 common object classes (person, bicycle, car, and more) using a transformer-based bounding box detection model.

### Segmentation models
* **Fish Segmentation** - Locates fish using a transformer-based instance segmentation model. Best for visualizing detected objects.
* **Apoidea Segmentation** - Locates bees, wasps, and related Apoidea species using a transformer-based instance segmentation model. Best for visualizing detected objects.
* **Generic Instance Segmentation** - Detects 80 common object classes (person, bicycle, car, and more) using a transformer-based instance segmentation model.

### All models
All models are based on the DETR (DEtection TRansformer) architecture.

| Model | Type | Parameters | Input size | Class indexing | Classes |
|---|---|---|---|---|---|
| **Fish Detection** | Detection | 33.9 M | 704px | 1-indexed | `[1]: 'Fish'` |
| **Apoidea Detection** | Detection | 33.9 M | 704px | 1-indexed | `[1]: 'Apoidea'` |
| **Generic Object Detection** | Detection | 33.9 M | 704px | 1-indexed | 80 (COCO classes) |
| **Fish Segmentation** | Segmentation | 36.2 M | 504px | 0-indexed | `[0]: 'Fish'` |
| **Apoidea Segmentation** | Segmentation | 36.2 M | 504px | 0-indexed | `[0]: 'Apoidea'` |
| **Generic Instance Segmentation** | Segmentation | 36.2 M | 504px | 0-indexed | 80 (COCO classes) |


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
* [Qt](https://www.qt.io/) / [PySide6](https://doc.qt.io/qtforpython/) for the application framework.
* [ONNX Runtime](https://onnxruntime.ai/) for providing a runtime for inference.

## Citation

If you use Detectorist in your work, you can [cite](CITATION.cff). it:

```bibtex
@software{Werner_Detectorist_2026,
  author  = {Werner, Ken},
  title   = {Detectorist},
  url     = {https://github.com/kenwer/detectorist},
  version = {0.10.2},
  year    = {2026}
}
```

## License

This project is licensed under the AGPL-3.0 license. See the LICENSE file for the full text.
