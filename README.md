# Fish Model Viewer

A desktop application for viewing images and running a local AI model to perform object detection. This application is designed for easily inspecting image datasets and testing model performance with adjustable parameters like confidence and Non-Maximum Suppression (NMS) thresholds. It features support for various image formats, including Sony RAW (.arw) files, and displays selected EXIF information.

![Main application interface](FishModelViewer-0.1.3.jpg)


## Key Features

*   **Image Browser:** Load and browse images (ideally showing fish) from a local folder with drag & drop support.
*   **AI model Inference:** Run object detection using a pre-loaded ONNX model.
*   **Adjustable Thresholds:** Interactively change confidence and NMS thresholds to see their effect on detections in real-time.
*   **Broad Image Format Support:** Handles common formats (PNG, JPG, HEIC/HEIF, BMP) and Sony RAW (.ARW).
*   **EXIF Data Viewer:** Displays selected EXIF metadata for each image.
*   **Drag & Drop:** Easily open folders or images by dragging them into the application window.


## Usage

### Download

Download the binary for your operating system the releases section and start the application.

### Using the Fish Model Viewer
*   Go to `File > Open Folder...` or simply drag a folder containing images onto the application window.
*   The folder will be scanned for supported images and load the first image.
*   The AI model will automatically run, and detection boxes will be drawn on the image.
*   Click on an item in the list on the left to navigate the image set.
*   View image and EXIF information in the panels on the right.
*   Use the sliders and spin-boxes on the right to adjust the **Confidence** and **NMS** thresholds. Detections will update automatically.


## Development

To run the application from the source code, I recommend to use `Python 3.12+` and `uv`.

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

3. ***Run from source:**
    ```shell
    uv run modelviewer
    ```


## Building Distributables

You can build standalone executables for macOS and Windows. The build process uses `poethepoet` to run scripts defined in `pyproject.toml`.

Make sure you have a python3 and uv installed.

### macOS App Bundle

1.  **Set up the environment:**
    ```shell
    uv venv -p `which python3` .venv
    uv pip install -e '.[dev]'
    source .venv/bin/activate
    ```

2.  **Run the build command:**
    This command will use Nuitka to compile the Python code into a `.app` bundle in the `dist/` directory.
    ```shell
    poe build-mac
    ```

### Windows Executable

1.  **Set up the environment and run the build:**
    ```shell
    uv venv .venv --python 3.12
    uv pip install -e '.[dev]'
    .venv\Scripts\activate
    poe build-windows
    ```
    This will create a standalone executable inside a folder in the `dist/` directory.


## License

This project is licensed under the Apache License, Version 2.0. See the LICENSE file for the full text.
