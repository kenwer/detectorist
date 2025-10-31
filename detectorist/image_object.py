import os
import shutil

import cv2
import numpy as np
from PIL import Image as PILImage

from . import image_utils
from .exif_wrapper import ExifWrapper
from .image_utils import IMG_EXTENSIONS


class ImageObject:
    """
    A class to handle image loading, processing, and saving.
    It can be instantiated with an image path to load an image,
    and provides methods for various image utility operations.
    Think of it as the "Model" in the MVC pattern.
    """
    SUPPORTED_IMG_EXTENSIONS = IMG_EXTENSIONS

    def __init__(self, image_path: str):
        """
        Initializes the ImageObject by loading an image from the given path.
        Supports standard 8 bit image formats but also 10/12 bit HEIF/HIF, and 16 bit Sony ARW raw files.
        """
        self._image_path = image_path # The path to the image file
        self._image_data = None # The loaded image data as a NumPy array
        self._original_bpc = 8  # The original bits per channel (10 and 12 bit images will be converted to 16 bit numpy arrays)
        self._file_extension = os.path.splitext(self.image_path)[1].lower()
        self._exif_handler = None

        self._image_data, self._original_bpc = image_utils.load_image_data(self.image_path)

        # Create ExifWrapper based on file type
        if self._file_extension in image_utils.RAW_EXTENSIONS or self._file_extension in image_utils.HEIF_EXTENSIONS:
            self._exif_handler = ExifWrapper(self.image_path)
        else:
            # For other formats, Pillow is used, so we need to open the image again for ExifWrapper
            pil_image = PILImage.open(self.image_path)
            self._exif_handler = ExifWrapper(pil_image)

        if self._image_data is None:
            raise OSError(f"Error: Could not read image from '{self.image_path}'")

    @property
    def exif_wrapper(self) -> ExifWrapper:
        """Returns Exif handler object for this image."""
        return self._exif_handler

    @property
    def image_path(self) -> str:
        """Returns the path to the loaded image."""
        return self._image_path

    @property
    def image_data(self) -> np.ndarray:
        """Returns the loaded image data as a NumPy array."""
        return self._image_data

    @property
    def original_bpc(self) -> int:
        """Returns the original bits per channel of the loaded image based on
        the original bit depth (and not on the bit depth the numpy array that stores the actual image data)."""
        return self._original_bpc

    @property
    def file_extension(self) -> str:
        """Returns the file extension of this image."""
        return self._file_extension

    def preprocess_for_onnx(self, input_width: int, input_height: int) -> np.ndarray:
        """
        Preprocesses an image for ONNX model inference.
        - Resizes to the target dimensions.
        - Converts to float32 and normalizes to [0, 1].
        - Transposes from HWC to CHW format.
        - Adds a batch dimension.
        """
        if self._original_bpc > 8:
            data = image_utils.convert_16bit_to_8bit(self._image_data)
        else:
            data = self._image_data

        resized_image = cv2.resize(data, (input_width, input_height))
        model_input_image = resized_image.astype(np.float32)
        model_input_image /= 255.0
        model_input_image = model_input_image.transpose(2, 0, 1)
        model_input_image = np.expand_dims(model_input_image, axis=0)
        return model_input_image

    def copy_image(self, target_dir_path):
        """Copies the original image file to the specified output directory preserving its file name."""
        input_file_name = os.path.basename(self._image_path)
        output_path = os.path.join(target_dir_path, input_file_name)
        shutil.copy2(self._image_path, output_path)
