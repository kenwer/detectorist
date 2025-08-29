# Fish Model Viewer

A desktop application for viewing images and running local AI to perform object (fish) detection. This niche application is designed for inspecting image datasets and testing model performance with adjustable parameters like confidence and Non-Maximum Suppression (NMS) thresholds. It features support for various image formats, including Sony RAW (.arw) files, and displays selected EXIF information.

![Main application interface](https://github.com/user-attachments/assets/407526be-5a97-4f85-b89a-3951cc4435c2)


## Key Features

*   **Image Browser:** Load and browse images (ideally showing fish) from a local folder with drag & drop support.
*   **AI model Inference:** Run object detection using a pre-loaded ONNX model.
*   **Adjustable Thresholds:** Interactively change confidence and NMS thresholds to see their effect on detections in real-time.
*   **Multiple Image Formats:** Supports common image formats like PNG, JPG, BMP, and also 10 bit HEIC/HEIF or Sony RAW (.ARW).
*   **EXIF Data Viewer:** Displays selected EXIF metadata for the current image.
*   **Drag & Drop:** Easily open folders or images by dragging them into the application window.
*   Allows to **save cropped copies** that isolates detected objects.
*   **Configurable aspect ratio for cropping:** with 3:2, 4:4, 16:9, plus support for padding.

## Roadmap/TODOs

*   Implement support for **persistent settings**.

## Usage

### Download

Download the binary for your operating system from the releases section and start the application.

### Using Fish Model Viewer

*   Go to `File > Open Folder...` or simply drag a folder containing images onto the application window.
*   The folder will be scanned for supported images and the first image will load automatically.
*   The AI model will automatically run, and detection boxes will be drawn on the image.
*   Click on an item in the list on the left to navigate through the image set.
*   View image and EXIF information in the panels on the right.
*   Use the sliders and spin-boxes on the right to adjust the **Confidence** and **NMS** thresholds. Detections will update automatically.
    * The **Confidence** threshold specifies the minimum confidence how sure the model must be about detecting an object before it reports that detection.
    * The **NMS** (non-maximum suppression) threshold helps to eliminate redundant and overlapping bounding boxes. The lower the threshold, the more strictly bounding boxes are calculated.
*   Optionally configure the crop & padding settings, and start cropping via the menu actions
    * The cropped images will be placed in a subdirectory of the directory that is currently being viewed.
    * The name of the output directory encodes the confidence level and the model used (like: `toutput_conf75_fish-detect-2025-08-01`).

## AI Model
The current fish detection model has been trained for approximately 130 epochs on around 900 images of fish. It's a start...

## Development

To run the application from source code, I recommend to use `Python 3.12+` and `uv`.

1.  **Clone the repository:**
    ```shell
    git clone https://github.com/kenwer/fish_model_viewer.git
    cd fish_model_viewer
    ```

2.  **Create a virtual environment and install dependencies:**
    This project uses `uv` to manage dependencies. The following command creates a virtual environment in `.venv` and installs all required packages.

    ```shell
    uv venv
    uv pip install -e '.[dev]'
    ```

3. **Run from source:**
    ```shell
    uv run modelviewer
    ```


## Building Distributables

You can build standalone executables for macOS and Windows. The build process uses `poethepoet` to run scripts defined in `pyproject.toml`.

Make sure you have a python3 and uv installed.

### macOS App Bundle

On macOS:
*   **Set up the build environment and run the build:**
    ```shell
    uv venv -p `which python3` .venv
    uv pip install -e '.[dev]'
    source .venv/bin/activate
    poe build-mac
    ```
    This will use Nuitka to compile the Python code into a `.app` bundle in the `dist/macos/` directory.

### Windows Executable

On Windows:
1.  **Set up the build environment and run the build:**
    ```shell
    uv venv .venv --python 3.12
    uv pip install -e '.[dev]'
    .venv\Scripts\activate
    poe build-windows
    ```
    This will create a standalone executable inside a folder in the `dist/windows/` directory.


## Changelog

### [0.2.0] - 2025-08-29
#### Added
- Cropping feature to save detected objects as separate images.
- Configurable aspect ratios (3:2, 4:4, 16:9) and padding for cropped images.
- Confidence scores are now shown as tooltips when hovering over bounding boxes.
- Object detection information is displayed in the UI.
- The native file explorer is opened to show the cropped images after the crop action is finished.
- Simple About dialog added with link to the project page

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
- Image browser with navigation
- Basic object detection using an ONNX model.
- Support for PNG, JPG, BMP, HEIC/HEIF, and Sony RAW (.ARW) images.


## License

This project is licensed under the Apache License, Version 2.0. See the LICENSE file for the full text.
