# Detectorist

A desktop application for sorting and cropping photos using machine learning for object detection. The main use case is to save time when cropping similar objects in large number of images. Imagine you're coming back from a diving session with hundreds or thousands of images of fish, and now you want to crop these to better view the fish. Or you want to discard any images that don't contain fish. This niche application allows you to do that with adjustable parameters like confidence, aspect ratio, and padding. Detectorist features support for various image formats, including 10 bit HEIF, and Sony RAW (.arw) files.

![Main application interface](https://github.com/user-attachments/assets/6d30d59d-a3b3-4026-844d-fc07e159d4bb)


## Key Features

*   **Image Browser:** Load and browse images from a local folder with drag & drop support.
*   **AI model Inference:** Run object detection using the included ONNX model.
*   **Adjustable Thresholds:** Interactively change confidence and NMS thresholds to see their effect on detections in real-time.
*   **Multiple Image Formats:** Supports common image formats like PNG, JPG, BMP, and also 10 bit HEIC/HEIF or Sony RAW (.ARW).
*   **EXIF Data Viewer:** Displays selected EXIF metadata for the current image.
*   **Drag & Drop:** Easily open folders or images by dragging them into the application window.
*   Allows to **save cropped copies** that isolates detected objects.
*   **Configurable aspect ratio for cropping:** with 3:2, 4:4, 16:9, plus support for padding.


## AI model info
* The `fish-detect-2025-09-11` model has been trained for 150 epochs on 863 images of fish.
  * Class name mapping: `[0]: 'Bee'` (a single-class detector).
* The `bee-detect-2025-09-10` model has been trained for 150 epochs on 171 images of bees.
  * Class name mapping: `[0]: 'Fish'` (a single-class detector).
* Both models use:
  * an image input image size of 1024px (larger images are downscaled automatically).
  * largest detection stride of 32 (the model’s coarsest feature map is 32× smaller than the input spatial resolution).
  * 3 input channels (RGB).


## Usage

### Download

Download the binary for your operating system from the [release page](https://github.com/kenwer/detectorist/releases) and start the application.
* macOS: [Detectorist.app.zip](https://github.com/kenwer/detectorist/releases/latest/download/Detectorist.app.zip) 
  * Note: The macOS app is not signed with a certificate from the Apple Developer Program. But you can still open the app as described in the [FAQ](FAQ.md).
* Windows: [Detectorist.exe.zip](https://github.com/kenwer/detectorist/releases/latest/download/Detectorist.exe.zip)
  * Note: The compiled Windows executable is not signed and since it extract additional contents to load it afterwards it's common that Anti Virus/Malware tools like Defender detects the application as malicious.

### Using Detectorist

*   Go to `File > Open Folder...` or simply drag a folder containing images onto the application window.
*   The folder will be scanned for supported images and the first image will load automatically.
*   The AI model will automatically run, and detection boxes will be drawn on the image.
*   Click on an item in the list on the left to navigate through the image set.
*   Use the sliders and spin-boxes on the right to adjust the **Confidence** and **NMS** thresholds. Detections will update automatically.
    * The **Confidence** threshold specifies the minimum confidence how sure the model must be about detecting an object before it reports that detection.
    * The **NMS** (non-maximum suppression) threshold helps to eliminate redundant and overlapping bounding boxes. The lower the threshold, the more strictly bounding boxes are calculated.
*   You can sort the images into sub folders that are named after the detected object class using the corresponding action in the Tools menu. The images are copied, not moved.
*   Optionally configure the crop & padding settings, and start cropping via the Tools menu actions
    * The cropped images will be placed in a subdirectory of the directory that is currently being viewed.
    * The name of the output directory encodes the confidence level and the model used (like: `detectorist_conf75_fish-detect-2025-08-01`).


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
    ```shell
    uv run detectorist
    ```


## Building distributables

You can build standalone executables for macOS and Windows. The build process uses `poethepoet` to run scripts defined in `pyproject.toml`.

Make sure you have a python3 and uv installed.

### macOS App Bundle

On macOS:
*   **Set up the build environment and run the build:**
    ```shell
    uv venv -p `which python3` .venv
    uv sync --group dev
    source .venv/bin/activate
    poe build-mac
    ```
    This will use Nuitka to compile the Python code into a `.app` bundle in the `dist/macos/` directory.

### Windows Executable

On Windows:
1.  **Set up the build environment and run the build:**
    ```shell
    uv venv .venv --python 3.12
    uv sync --group dev
    .venv\Scripts\activate
    poe build-windows
    ```
    This will create a standalone executable inside a folder in the `dist/windows/` directory.


## Roadmap/TODOs

*   Implement support for **persistent settings**.
*   Model support
    *   Train and include more/better models
    *   Allow users to bring their own models


## Changelog

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

#### Changed
- Name of the output directory changed (example: `detectorist_conf-75_fish-detect-2025-08-01`).
- [Dev] Migrate from PEP 621-style dependencies to PEP 695 dependency-groups.

#### Added
- When processing multiple images, write a log file to the output directory providing information about the detections.
- [Dev] Added ruff for linting.

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
#### Fixed
- Resolved problem with the Windows build process.
- Fixed the release packaging.

#### Changed
- Migrated GitHub Actions to use `astral-sh/setup-uv@v6` and `actions/upload-artifact@v4`.

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

This project is licensed under the Apache License, Version 2.0. See the LICENSE file for the full text.
