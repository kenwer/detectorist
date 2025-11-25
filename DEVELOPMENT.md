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


## Changelog

See [CHANGELOG.md](CHANGELOG.md).
