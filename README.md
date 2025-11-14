# Detectorist

This desktop application uses machine learning for object detection to sort and crop photos. The main use case is to save time when cropping similar objects across a large number of images. For example, imagine returning from a diving session with thousands of photos of fish and wanting to quickly crop them for better viewing. Or, if you're into bees and want to discard any images that don't contain bees or similar looking insects. This niche application allows you to do that with adjustable parameters like confidence, aspect ratio, and padding. Detectorist supports various image formats, including JPG, PNG, BMP, 10 bit HEIF, and Sony RAW (.arw) files.

![Main application interface](https://github.com/user-attachments/assets/6d30d59d-a3b3-4026-844d-fc07e159d4bb)


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

*   Select the AI model you want to use from the drop down list at the top right.
*   Go to `File > Open Folder...` or simply drag a folder containing images onto the application window.
*   The folder will be scanned for supported images and the first image will load automatically.
*   The AI model will automatically run, and detection boxes will be drawn on the image.
*   Click on an item in the list on the left to navigate through the image set.
*   Use the slider and spin-box on the right to adjust the **Confidence** threshold. Detections will update automatically.
    * The Confidence threshold specifies the minimum confidence how sure the model must be about detecting an object before it reports that detection.
*   You can sort the images into sub folders that are named after the detected object class using the corresponding item in the Actions menu. The images are copied, not moved.
*   Optionally configure the crop & padding settings, and start cropping via the Actions menu.
    * The cropped images will be placed in a subdirectory of the directory that is currently being viewed.
    * The name of the output directory encodes the confidence level and the model used (like: `detectorist_conf75_fish-detect-2025-09-11`).


## FAQ

Frequently asked questions can be found at the [FAQ page](FAQ.md).


## Development

To run the application from source code, I recommend to use `Python 3.12+` and `uv`.

1.  **Clone the repository:**
    ```shell
    git clone https://github.com/kenwer/detectorist.git
    cd detectorist
    ```

2.  **Create a virtual environment and install dependencies:**
    This project uses `uv` to manage dependencies. The following command creates a virtual environment in `.venv` and installs all required packages.

    ```shell
    uv venv
    uv sync --group dev
    ```

3. **Run from source:**

    Use `poe run` to implicitly compile the .ui and .qrc files:
    ```shell
    uv run poe run
    ```

    To run it directly:
    ```shell
    uv run detectorist
    # or
    python3 detectorist/main.py
    ```


## Building distributables

You can build standalone executables for macOS and Windows. The build process uses `poethepoet` to run scripts defined in `pyproject.toml`.

Make sure you have a python3 and uv installed.

### macOS App Bundle

On macOS:
1.  **Install the prerequisites on macOS:**
    ```shell
    brew install uv python@3.13
    ```

2.  **Set up the build environment and run the build:**
    ```shell
    uv venv -p "$HOMEBREW_PREFIX/bin/python3.13" .venv
    uv sync --group dev
    source .venv/bin/activate
    poe build-mac
    ```
    This will use Nuitka to compile the Python code into a `.app` bundle in the `dist/macos/` directory.

### Windows Executable

On Windows:
1.  **Install the prerequisites on Windows:**
    ```shell
    winget install astral-sh.uv Python.Python.3.12 --scope user
    ```

2.  **Set up the build environment and run the build:**
    ```shell
    uv venv -p 3.12 .venv
    uv sync --group dev
    .venv\Scripts\activate
    poe build-windows
    ```
    This will use Nuitka to create a standalone executable inside a folder in the `dist/windows/` directory.

### Linux Binary

On Linux:
1.  **Ensure you have python3 and uv installed.**
2.  **Set up the build environment and run the build:**
    ```shell
    uv venv -p `which python3` .venv
    uv sync --group dev
    source .venv/bin/activate
    poe build-linux
    ```
    This will use Nuitka to compile the Python code into a x86 Linux ELF binary in the `dist/linux/` directory.

## Roadmap/TODOs

*   Implement support for **persistent settings**.
*   Model support
    *   Train and include more/better models
    *   Allow users to bring their own models


## Changelog

### [0.7.0] - 2025-11-14
#### Added
- New "Open Image(s)..." action at the File menu to open and load selected files only (also works for dropping slected files).
- Allow selecting a subset of the loaded images to be cropped & saved.
- Display the GPS coordinates if available in EXIF.
- Allow text selection in the EXIF info widget to be able to copy text.

#### Changed
- Shortcut to open/load folders now is Ctrl+Shift+O, since Ctrl+O is for opening images within folders.
- Enhanced UI responsiveness by offloading image loading and object detection to a dedicated `DetectionWorker` thread for asynchronous processing.
- Remember the last opened directory for the current session (not persistent).
- [Dev] Refactor ImageObject subclasses into dedicated files and let them handle EXIF individually.
- [Dev] Adopt piexif to handle EXIF and remove the now unused exifread dependency.

#### Fixed
- When auto correcting the exposure for a cropped image, also reset the ExposureBiasValue in the EXIF.
- Fix UI layout for the crop settings.

### [0.6.2] - 2025-11-06
#### Changed
- The `Tools` menu is now called `Actions` to make it clearer that its entries trigger immediate actions.
- Enable the auto correct camera exposure bios functionality by default.
- Add '_crop' to the name of the resulting file when cropping images.
- [Dev] Clarify bit depth handling for HEIF images.
- [Dev] Use context manager when loading EXIF data from PIL images.
- [Dev] Update dependencies.

#### Fixed
- Memory leak when cropping HEIF images (fixed with upgrading pillow-heif).
- Progress bar visibility when cropping multiple images (fixed with pyside6 upgrade).
- Ignore exposure compensation requests for images that don't have the ExposureBiasValue data present in their EXIF.

### [0.6.1] - 2025-11-03
#### Added
- Support to automatically adjust the exposure when cropping images to correct for any exposure bias present in the EXIF data.
- Add support for palette-based images such as GIFs.

#### Changed
- [Dev] Move the detectorist sources into a `src` directory and:
  - Use relative imports within the package (e.g., from .module import ...).
  - Use absolute imports for entry points or scripts (e.g., from detectorist.module import ...).

#### Fixed
- Support for handling 8 bit CMYK images.

### [0.6.0] - 2025-10-31
#### Added
- Display Exposure Compensation for a loaded image from its EXIF data.
- Display the Bits Per Channel (color depth) of the loaded image.
- Add support for 16 bit standard image files (e.g. 16 bit PNG).
- [Dev] Switch from Pillow to OpenCV to support 16 bit standard image files.

#### Changed
- UI space for EXIF data expands to display more contents (if the app window size is increased vertically).
- [Dev] Refactor image data loading/holding/saving logic to make it more robust and universal.

#### Fixed
- Drag & drop for images.

### [0.5.1] - 2025-10-02
#### Added
- Support loading 4 channel CMYK JPG images.
- [Dev] Add ruff for linting.

#### Changed
- [Dev] GitHub Actions, pull models using git-lfs for releases only.
- [Dev] Remove unused code.

### [0.5.0] - 2025-09-22
#### Added
- Add option to crop all detected objects into new (cropped) images.
- Support for additional crop aspect ratios.

#### Changed
- When the crop rectangle is larger than the image, the center point of is now preserved to prevent the cropping frame from shifting away (in case the padding is increased).

#### Fixed
- Allow the about dialog to change its size so the content always fits (e.g. when different fonts are used).
- In case a new folder is opened that doesn't contain any supported images, any previous detection infos are cleared.

### [0.4.2] - 2025-09-18
#### Changed
- Minimum allowed confidence threshold is 1 instead of 0.
- Remove the NMS slider & spin-box, and use a default of 0.4.

#### Fixed
- When processing multiple images, ensure that the progress dialog is closed when the action has been completed or canceled.

### [0.4.1] - 2025-09-15
#### Added
- Build ELF binary for Linux x64.

#### Changed
- [Dev] Poe tasks now depend on building the `.ui` and `.qrc` files.

#### Fixed
- Handle images with alpha channels - this fixes loading PNGs.

### [0.4.0] - 2025-09-11
#### Added
- Additional model for detecting bees in images.
- Re-run object detection when the model is changed.
- [Dev] Add poe ruff task.

#### Changed
- [Dev] Track model files with git lfs.
- Update model for fish detection that works better for images with multiple fish.

### [0.3.4] - 2025-09-10
#### Changed
- [Dev] Simplify build process of the binary distributables.

#### Fixed
- Fixed instructions to build distributables.
- [Windows] Ensure the splash screen disappears when the main application window starts.

### [0.3.3] - 2025-09-07
#### Added
- When processing multiple images, write a log file to the output directory providing information about the detections.
- [Dev] Added ruff for linting.

#### Changed
- Name of the output directory changed (example: `detectorist_conf-75_fish-detect-2025-08-01`).
- [Dev] Migrate from PEP 621-style dependencies to PEP 695 dependency-groups.

#### Fixed
- [Dev] Consistent code formatting.

### [0.3.2] - 2025-09-06
#### Added
- Display the class of the detected object in the tooltip.
- Support for sorting images into sub folders that are named after the detected object class using the corresponding action in the Tools menu.

#### Fixed
- Information corrected in the About dialog.

### [0.3.1] - 2025-09-05
#### Fixed
- Ensure the cropping rectangle always fits the image and maintains aspect ratio.
- Ensure the object bounding box always stays within the image boundaries.

### [0.3.0] - 2025-09-02
#### Changed
- Renamed the project to Detectorist.

### [0.2.1] - 2025-08-30
#### Added
- Initial [FAQ](FAQ.md) added.

#### Changed
- Improved the GitHub actions build & release workflow.

#### Fixed
- Fixed the macOS app bundle build and binary release.

### [0.2.0] - 2025-08-29
#### Added
- Cropping feature to save detected objects as separate images.
- Configurable aspect ratios (3:2, 4:4, 16:9) and padding for cropped images.
- Confidence scores are now shown as tooltips when hovering over bounding boxes.
- Object detection information is displayed in the UI.
- The native file explorer is opened to show the cropped images after the crop action is finished.
- Simple About dialog added with link to the project page.

#### Changed
- The "Crop" actions have been moved into a dedicated "Tools" menu.
- Reworked path handling for cropping to be more robust.
- Refactored `Image` to `ImageObject` and `Exif` to `ExifWrapper` for better code organization.
- Updated dependencies to their latest versions.

#### Fixed
- Support for RAW image files has been fixed.
- Cropping of non-HEIF images is now correctly handled using PIL.
- The "Crop & Save All" action now works correctly even if the currently displayed image has no detections.

### [0.1.3] - 2025-08-15
#### Changed
- Migrated GitHub Actions to use `astral-sh/setup-uv@v6` and `actions/upload-artifact@v4`.

#### Fixed
- Resolved problem with the Windows build process.
- Fixed the release packaging.

### [0.1.2] - 2025-08-15
#### Added
- Drag & drop support for folders and images.
- Added a GitHub Actions workflow for automated builds.

### [0.1.1] - 2025-08-12
#### Added
- Display selected EXIF data.

### [0.1.0] - 2025-08-01
#### Added
- Initial release with MVP functionality.
- Image browser with navigation added.
- Basic object detection using an ONNX model.
- Support for PNG, JPG, BMP, HEIC/HEIF, and Sony RAW (.ARW) images.


## License

This project is licensed under the AGPL-3.0 license. See the LICENSE file for the full text.
