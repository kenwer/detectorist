# Changelog

## [Unreleased]
### Added
- Added builds for macOS Intel (x64), Linux arm64, and Windows arm64.
- [Dev] Added `poe build` task that automatically calls the appropriate platform-specific build task.

### Changed
- Release archive filenames now include OS and architecture (e.g., `Detectorist-macos-arm64.zip`). 
- The binaries inside the archives include the version number (e.g., `Detectorist-0.7.3.app`).

## [0.7.2] - 2025-11-25
### Added
- Add `Crop & Export & Remove selected Images` action that allows to start a batch process that crops and exports the selected image(s) into a subfolder and also removes the image(s) from the list once it completed.
- Selected images can now be removed from the list view via the context menu or using the backspace keyboard shortcut.
  - Note: The images are just removed from the list view in the UI, the images on the filesystem are untouched. 

### Changed
- The `Copy Filename to Clipboard` is now called `Copy Filenames to Clipboard` because it allows to copy all of the selected filenames into the clipboard.
- Rename the `Reveal Image in File Manager` action to `Locate Image in Filemanager`.
- [Dev] Move action definitions into the .ui file.

## [0.7.1] - 2025-11-20
### Added
- Add option to crop to the most centrally located of all detected objects.
- Add option to set the aspect ratio of the crop to the aspect ratio of the detect frame ("aspect ratio: same as detection frame").
- New context menu for the image list view with the following image specific actions:
  - "Reveal Image in File Manager" to easily locate an image in your native file manager (Finder, Explorer, etc), and
  - "Copy Filename to Clipboard" that copies the file name string of the selected image to your clipboard.
- File menu item to clear the image list.
- Navigating through the list of images using the keyboard:
    | Shortcut Windows/Linux | Shortcut macOS | Action |
    | --- | --- | --- |
    | Ctrl+Up    | ⌘⬆︎ | jump to first image |
    | Ctrl+Left  | ⌘⬅︎ | jump to first image |
    | Ctrl+Down  | ⌘⬇︎ | jump to last image |
    | Ctrl+Right | ⌘➡︎ | jump to last image |

### Changed
- Remove `Crop & copy current image` because we now have the `Crop & export selected images`action.
- Rename `Sort images into folders` action to `Group images into folders` because it groups images by the detected object class.
- Rename `save` actions to `export` actions to clarify that the original images are not overwritten.
- Adjust keybord shortcuts:
    | Shortcut Windows/Linux | Shortcut macOS | Action |
    | --- | --- | --- |
    | Shift+Ctrl+G   | ⇧⌘G | Group images into folder |
    | Ctrl+E | ⌘E | Crop & Export selected Images |
    | Shift+Ctrl+E | ⇧⌘E | Crop & Export all Images |

## [0.7.0] - 2025-11-14
### Added
- New "Open Image(s)..." action at the File menu to open and load selected files only (also works for dropping slected files).
- Allow selecting a subset of the loaded images to be cropped & saved.
- Display the GPS coordinates if available in EXIF.
- Allow text selection in the EXIF info widget to be able to copy text.

### Changed
- Shortcut to open/load folders now is Ctrl+Shift+O, since Ctrl+O is for opening images within folders.
- Enhanced UI responsiveness by offloading image loading and object detection to a dedicated `DetectionWorker` thread for asynchronous processing.
- Remember the last opened directory for the current session (not persistent).
- [Dev] Refactor ImageObject subclasses into dedicated files and let them handle EXIF individually.
- [Dev] Adopt piexif to handle EXIF and remove the now unused exifread dependency.

### Fixed
- When auto correcting the exposure for a cropped image, also reset the ExposureBiasValue in the EXIF.
- Fix UI layout for the crop settings.

## [0.6.2] - 2025-11-06
### Changed
- The `Tools` menu is now called `Actions` to make it clearer that its entries trigger immediate actions.
- Enable the auto correct camera exposure bios functionality by default.
- Add '_crop' to the name of the resulting file when cropping images.
- [Dev] Clarify bit depth handling for HEIF images.
- [Dev] Use context manager when loading EXIF data from PIL images.
- [Dev] Update dependencies.

### Fixed
- Memory leak when cropping HEIF images (fixed with upgrading pillow-heif).
- Progress bar visibility when cropping multiple images (fixed with pyside6 upgrade).
- Ignore exposure compensation requests for images that don't have the ExposureBiasValue data present in their EXIF.

## [0.6.1] - 2025-11-03
### Added
- Support to automatically adjust the exposure when cropping images to correct for any exposure bias present in the EXIF data.
- Add support for palette-based images such as GIFs.

### Changed
- [Dev] Move the detectorist sources into a `src` directory and:
  - Use relative imports within the package (e.g., from .module import ...).
  - Use absolute imports for entry points or scripts (e.g., from detectorist.module import ...).

### Fixed
- Support for handling 8 bit CMYK images.

## [0.6.0] - 2025-10-31
### Added
- Display Exposure Compensation for a loaded image from its EXIF data.
- Display the Bits Per Channel (color depth) of the loaded image.
- Add support for 16 bit standard image files (e.g. 16 bit PNG).
- [Dev] Switch from Pillow to OpenCV to support 16 bit standard image files.

### Changed
- UI space for EXIF data expands to display more contents (if the app window size is increased vertically).
- [Dev] Refactor image data loading/holding/saving logic to make it more robust and universal.

### Fixed
- Drag & drop for images.

## [0.5.1] - 2025-10-02
### Added
- Support loading 4 channel CMYK JPG images.
- [Dev] Add ruff for linting.

### Changed
- [Dev] GitHub Actions, pull models using git-lfs for releases only.
- [Dev] Remove unused code.

## [0.5.0] - 2025-09-22
### Added
- Add option to crop all detected objects into new (cropped) images.
- Support for additional crop aspect ratios.

### Changed
- When the crop rectangle is larger than the image, the center point of is now preserved to prevent the cropping frame from shifting away (in case the padding is increased).

### Fixed
- Allow the about dialog to change its size so the content always fits (e.g. when different fonts are used).
- In case a new folder is opened that doesn't contain any supported images, any previous detection infos are cleared.

## [0.4.2] - 2025-09-18
### Changed
- Minimum allowed confidence threshold is 1 instead of 0.
- Remove the NMS slider & spin-box, and use a default of 0.4.

### Fixed
- When processing multiple images, ensure that the progress dialog is closed when the action has been completed or canceled.

## [0.4.1] - 2025-09-15
### Added
- Build ELF binary for Linux x64.

### Changed
- [Dev] Poe tasks now depend on building the `.ui` and `.qrc` files.

### Fixed
- Handle images with alpha channels - this fixes loading PNGs.

## [0.4.0] - 2025-09-11
### Added
- Additional model for detecting bees in images.
- Re-run object detection when the model is changed.
- [Dev] Add poe ruff task.

### Changed
- [Dev] Track model files with git lfs.
- Update model for fish detection that works better for images with multiple fish.

## [0.3.4] - 2025-09-10
### Changed
- [Dev] Simplify build process of the binary distributables.

### Fixed
- Fixed instructions to build distributables.
- [Windows] Ensure the splash screen disappears when the main application window starts.

## [0.3.3] - 2025-09-07
### Added
- When processing multiple images, write a log file to the output directory providing information about the detections.
- [Dev] Added ruff for linting.

### Changed
- Name of the output directory changed (example: `detectorist_conf-75_fish-detect-2025-08-01`).
- [Dev] Migrate from PEP 621-style dependencies to PEP 695 dependency-groups.

### Fixed
- [Dev] Consistent code formatting.

## [0.3.2] - 2025-09-06
### Added
- Display the class of the detected object in the tooltip.
- Support for sorting images into sub folders that are named after the detected object class using the corresponding action in the Tools menu.

### Fixed
- Information corrected in the About dialog.

## [0.3.1] - 2025-09-05
### Fixed
- Ensure the cropping rectangle always fits the image and maintains aspect ratio.
- Ensure the object bounding box always stays within the image boundaries.

## [0.3.0] - 2025-09-02
### Changed
- Renamed the project to Detectorist.

## [0.2.1] - 2025-08-30
### Added
- Initial [FAQ](FAQ.md) added.

### Changed
- Improved the GitHub actions build & release workflow.

### Fixed
- Fixed the macOS app bundle build and binary release.

## [0.2.0] - 2025-08-29
### Added
- Cropping feature to save detected objects as separate images.
- Configurable aspect ratios (3:2, 4:4, 16:9) and padding for cropped images.
- Confidence scores are now shown as tooltips when hovering over bounding boxes.
- Object detection information is displayed in the UI.
- The native file explorer is opened to show the cropped images after the crop action is finished.
- Simple About dialog added with link to the project page.

### Changed
- The "Crop" actions have been moved into a dedicated "Tools" menu.
- Reworked path handling for cropping to be more robust.
- Refactored `Image` to `ImageObject` and `Exif` to `ExifWrapper` for better code organization.
- Updated dependencies to their latest versions.

### Fixed
- Support for RAW image files has been fixed.
- Cropping of non-HEIF images is now correctly handled using PIL.
- The "Crop & Save All" action now works correctly even if the currently displayed image has no detections.

## [0.1.3] - 2025-08-15
### Changed
- Migrated GitHub Actions to use `astral-sh/setup-uv@v6` and `actions/upload-artifact@v4`.

### Fixed
- Resolved problem with the Windows build process.
- Fixed the release packaging.

## [0.1.2] - 2025-08-15
### Added
- Drag & drop support for folders and images.
- Added a GitHub Actions workflow for automated builds.

## [0.1.1] - 2025-08-12
### Added
- Display selected EXIF data.

## [0.1.0] - 2025-08-01
### Added
- Initial release with MVP functionality.
- Image browser with navigation added.
- Basic object detection using an ONNX model.
- Support for PNG, JPG, BMP, HEIC/HEIF, and Sony RAW (.ARW) images.