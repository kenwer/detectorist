# Detectorist

<!--TOC-->

- [About](#about)
- [Download](#download)
- [Key features](#key-features)
- [AI model info](#ai-model-info)
- [Using Detectorist](#using-detectorist)
  - [Typical usage scenario](#typical-usage-scenario)
  - [Keyboard shortcuts](#keyboard-shortcuts)
    - [Global shortcuts](#global-shortcuts)
    - [Shortcuts that operate on a set of selected images](#shortcuts-that-operate-on-a-set-of-selected-images)
    - [Image navigation shortcuts](#image-navigation-shortcuts)
- [Changelog](#changelog)
- [Roadmap/TODOs](#roadmaptodos)
- [FAQ](#faq)
- [Development](#development)
- [License](#license)

<!--TOC-->

## About

Detectorist is a multi platform desktop application that uses machine learning for object detection to sort and crop photos. The main use case is to save time when cropping similar objects across a large number of images by using local AI. For example, imagine returning from a diving session with thousands of photos of fish and wanting to quickly crop them for better viewing. Or, if you're into bees and want to discard any images that don't contain bees or similar looking insects. This niche application allows you to do that with adjustable parameters like confidence, aspect ratio, and padding. Detectorist supports various image formats, including JPG, PNG, BMP, 10 bit HEIF, and Sony RAW (.arw) files.

![Main application interface](https://github.com/user-attachments/assets/5483da55-39e3-421c-9053-131ea1d22d95)


## Download

Download the binary for your operating system from the [release page](https://github.com/kenwer/detectorist/releases) and start the application.
* macOS (Apple Silicon): [Detectorist.app.zip](https://github.com/kenwer/detectorist/releases/latest/download/Detectorist.app.zip) 
  * Note: The macOS app is not signed with a certificate from the Apple Developer Program. But you can still open the app as described in the [FAQ](FAQ.md).
* Windows: [Detectorist.exe.zip](https://github.com/kenwer/detectorist/releases/latest/download/Detectorist.exe.zip)
  * Note: The compiled Windows executable is not signed and since it extract additional contents to load it afterwards it's common that Anti Virus/Malware tools like Defender detects the application as malicious.
* Linux (x64): [Detectorist.tar.gz](https://github.com/kenwer/detectorist/releases/latest/download/Detectorist.tar.gz)
  * Note: on Linux you can also easily run Detectorist from the source as described below.


## Key features

*   **Image Browser:** Load and browse images from a local folder using drag & drop.
*   **Detect and crop objects using AI:** Run model inference using the included ONNX models.
*   **Adjustable Confidence Threshold:** Interactively change confidence to see the effect on detections in real-time.
*   **Multiple Image Formats:** Supports common image formats like PNG, JPG, BMP, and also 10 bit HEIC/HEIF or Sony RAW (.ARW).
*   **EXIF Data Viewer:** Displays selected EXIF metadata for the current image.
*   **Save cropped copies:** Automatically isolate detected objects in all loaded images.
*   **Configurable aspect ratio for cropping:** with 3:2, 4:4, 16:9, plus support for padding.
*   **Sort into subfolder:** Detect object classes and sort images into corresponding sub folders.
*   **CSV log when processing multiple images:** Write log file to the output directory providing information about the detections like the 	number of detected objects and the highest confidence score.


## AI model info
* The `fish-detect-2025-09-11` model has been trained for 150 epochs on 863 images of fish.
  * Class name mapping: `[0]: 'Fish'` (single-class detector).
* The `bee-detect-2025-09-10` model has been trained for 150 epochs on 171 images of bees.
  * Class name mapping: `[0]: 'Bee'` (single-class detector).
* Both models use:
  * an image input image size of 1024px (larger images are downscaled automatically).
  * largest detection stride of 32 (the model’s coarsest feature map is 32× smaller than the input spatial resolution).
  * 3 input channels (RGB).


## Using Detectorist

### Typical usage scenario
*   Select the AI model you want to use from the drop down list at the top right.
*   Go to `File > Open Folder...` or simply drag and drop a folder containing images onto the application window.
*   The folder will be scanned for supported images and the first image will load automatically.
*   The AI model will automatically run, and detection boxes will be drawn on the image.
*   Click on an item in the list on the left or use the arrow keys to navigate through the image set.
*   Use the slider and spin-box on the right to adjust the **Confidence** threshold. Detections will update automatically.
    * The Confidence threshold specifies the minimum confidence how sure the model must be about detecting an object before it reports that detection.
*   You can sort the images into sub folders that are named after the detected object class using the corresponding item in the Actions menu. The images are copied, not moved.
*   Optionally configure the crop & padding settings, and start cropping via the Actions menu.
    * The cropped images will be placed in a subdirectory of the directory that is currently being viewed.
    * The name of the output directory encodes the confidence level and the model used (like: `detectorist_conf75_fish-detect-2025-09-11`).

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


## Changelog

The changelog can be found at the [CHANGELOG page](CHANGELOG.md).


## Roadmap/TODOs

*   Implement support for **persistent settings**.
*   Model support
    *   Train and include more/better models
    *   Allow users to bring their own models


## FAQ

Frequently asked questions can be found at the [FAQ page](FAQ.md).

<!-- FAQ_TOC_START -->
- [Q1: When starting the app on macOS, how do I get past the  "*Detectorist.app Not Opened*" message?](FAQ.md#q1-when-starting-the-app-on-macos-how-do-i-get-past-the--detectoristapp-not-opened-message)
- [Q2: When starting the Windows executable, how do I get past the "*Windows protected your PC*" / "*Don't run*" message?](FAQ.md#q2-when-starting-the-windows-executable-how-do-i-get-past-the-windows-protected-your-pc--dont-run-message)
<!-- FAQ_TOC_END -->

## Development

For instructions on how to run the application from source, build the distributables, or view the changelog, please see the [DEVELOPMENT.md](DEVELOPMENT.md) file.

## License

This project is licensed under the AGPL-3.0 license. See the LICENSE file for the full text.
