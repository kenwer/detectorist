# Fish Model Viewer

A desktop application for viewing images and running local AI to perform object (fish) detection. This niche application is designed for inspecting image datasets and testing model performance with adjustable parameters like confidence and Non-Maximum Suppression (NMS) thresholds. It features support for various image formats, including Sony RAW (.arw) files, and displays selected EXIF information.

![Main application interface](https://github.com/user-attachments/assets/a90bffff-b038-4a0c-aa35-e71d57ba8e63)


## Key Features

*   **Image Browser:** Load and browse images (ideally showing fish) from a local folder with drag & drop support.
*   **AI model Inference:** Run object detection using a pre-loaded ONNX model.
*   **Adjustable Thresholds:** Interactively change confidence and NMS thresholds to see their effect on detections in real-time.
*   **Broad Image Format Support:** Handles common formats (PNG, JPG, HEIC/HEIF, BMP) and Sony RAW (.ARW).
*   **EXIF Data Viewer:** Displays selected EXIF metadata for each image.
*   **Drag & Drop:** Easily open folders or images by dragging them into the application window.

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


## License

This project is licensed under the Apache License, Version 2.0. See the LICENSE file for the full text.
