## Development

To run the application from source code, I recommend to use `Python 3.14` and `uv`.

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

    The compiled `ui_*.py` and `*_rc.py` files are not checked in, so on a fresh clone run `uv run poe compile-ui` and `uv run poe compile-qrc` (or `uv run poe run`) once before running it directly:
    ```shell
    uv run detectorist
    # or
    python3 detectorist/main.py
    ```


## Testing

The tests use `pytest` with `pytest-qt` and run headless on Qt's offscreen platform.

```shell
uv run poe test        # everything
uv run poe test-fast   # skips the slow tier, takes a few seconds
uv run poe test-slow   # only the slow tier
uv run poe lint
```

The fast tier needs no model files. `Detector` is tested against two tiny ONNX models in `tests/data`, whose outputs are fixed values defined in `tests/tiny_models.py`. After changing those values, regenerate the files with `uv run --script scripts/make_test_models.py`.

The slow tier loads every model listed in `models/models.json` from `./models`. A model whose Git LFS file has not been fetched is skipped, which is why this tier does nothing in CI.

To run the fast tier before every push, enable the tracked git hook once per clone:

```shell
uv run poe install-hooks
```


## Building distributables

You can build standalone executables for macOS and Windows. The build process uses `poethepoet` to run scripts defined in `pyproject.toml`.

Make sure you have a python3 and uv installed.

### macOS App Bundle

On macOS:
1.  **Install the prerequisites on macOS:**
    ```shell
    brew install uv python@3.14
    ```

2.  **Set up the build environment and run the build:**
    ```shell
    uv venv -p "$HOMEBREW_PREFIX/bin/python3.14" .venv
    uv sync --group dev
    source .venv/bin/activate
    poe build-mac
    ```
    This will use Nuitka to compile the Python code into a `.app` bundle in the `dist/macos/` directory.

### Windows Executable

On Windows:
1.  **Install the prerequisites on Windows:**
    ```shell
    winget install Microsoft.VisualStudio.2022.Community --silent --override "--wait --quiet --addProductLang En-us --add Microsoft.VisualStudio.Workload.NativeDesktop --includeRecommended"
    winget install astral-sh.uv Python.Python.3.14 --scope user
    ```

2.  **Set up the build environment and run the build:**
    ```shell
    uv venv -p 3.14 .venv
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
