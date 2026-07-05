import os

import cv2
import numpy as np
import piexif
from PIL import Image as PILImage

from . import image_utils
from .image_object import ImageObject
from .pillow_image_object import STANDARD_IMG_EXTENSIONS
from .structures import ImageMode


class OpencvImageObject(ImageObject):
    """
    ImageObject subclass for standard image formats like PNG, JPEG, BMP, etc.

    This class primarily uses OpenCV (`cv2`) to load image data, which allows it
    to handle both 8-bit and 16-bit images. It also uses Pillow to accurately
    determine the original color mode (e.g., 'RGB', 'RGBA', 'L') before storing
    the data in a NumPy array. It handles images with 'L', 'RGB', and 'RGBA' modes.
    """

    def __init__(self, image_path: str):
        """
        Initializes the object by loading a standard image file.

        It uses a dual-loading strategy:
        1.  `cv2.imread` is used to load the image data, preserving 16-bit depth if present.
        2.  `PIL.Image.open` is used in parallel to inspect the image's metadata and
            accurately determine the color mode, as OpenCV can be ambiguous.
        """
        super().__init__(image_path)

        # Validate file extension
        if self._file_extension not in STANDARD_IMG_EXTENSIONS:
            raise ValueError(f"Invalid image file extension \"{self._file_extension}\". Expected {STANDARD_IMG_EXTENSIONS}")

        print(f"Loading standard image file: {self.image_path}")
        # This is a bit hacky since OpenCV always loads image as BGR or BGRA while
        # Pillow doesn't support 16 bit images# https://github.com/python-pillow/Pillow/issues/7723
        # So we load the image twice
        #   - once with OpenCV to be able to get the 16 bit data if present
        #   - once with Pillow to determine the color mode (RGB, RGBA) of the image
        # Then we convert the OpenCV loaded image data to match the logical color mode determined by Pillow

        # Load image with OpenCV to be able to get the 16 bit data if present
        cv_image = cv2.imread(self.image_path, cv2.IMREAD_UNCHANGED)
        if cv_image is None:
            raise OSError(f"Error: Could not read image from '{self.image_path}'")

        # Determine original bits per channel based on image dtype
        if cv_image.dtype == np.uint16:
            self._original_bpc = 16
        else:
            self._original_bpc = 8

        # Load with Pillow to determine color mode
        with PILImage.open(self.image_path) as pil_image:
            # Keep image data in OpenCV's native format (BGR or BGRA)
            if pil_image.mode == 'L':
                self._mode = ImageMode.GRAY
                self._image_data = cv_image # OpenCV reads grayscale as 2D array
            elif pil_image.mode == 'RGB':
                self._mode = ImageMode.BGR # OpenCV loads as BGR
                self._image_data = cv_image
            elif pil_image.mode == 'RGBA':
                self._mode = ImageMode.BGRA # OpenCV loads as BGRA
                self._image_data = cv_image
            elif pil_image.mode == 'P':
                # This should not be reached because of the factory logic
                raise ValueError("Paletted images should be handled by PalettedImageObject.")
            else:
                raise ValueError(f"Unsupported Pillow image mode in StandardImageObject: {pil_image.mode}")

        self._exif_dict = self._load_exif_data()

    def save_cropped(self, rect: tuple[int, int, int, int], output_path: str):
        """Saves a cropped version of the image, preserving original format and EXIF data."""
        print(f"Cropping image file: {self.image_path}")

        x, y, w, h = rect

        cropped_data = self.image_data[y:y+h, x:x+w]

        cropped_data = self._apply_exposure_correction(cropped_data)

        # The data is already in BGR/BGRA format, which cv2 expects.
        image_utils.imwrite(output_path, cropped_data)
        print(f"  Cropped image saved to {output_path}")

        # Handle EXIF data using piexif
        if self._exif_dict and os.path.splitext(output_path)[1].lower() in ('.jpg', '.jpeg'):
            try:
                self._update_exif_dimensions(self._exif_dict, w, h)
                self._neutralize_exposure_bias(self._exif_dict)

                exif_bytes = piexif.dump(self._exif_dict)
                piexif.insert(exif_bytes, output_path)
                print(f"  Updated EXIF data for {output_path}")
            except Exception as e:
                print(f"Warning: Could not update EXIF data for {output_path}: {e}")
