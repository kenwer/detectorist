import os
import cv2
import numpy as np
from PIL import Image as PILImage

from .exif_wrapper import ExifWrapper
from . import image_utils

class ImageObject:
    """
    A class to handle image loading, processing, and saving.
    It can be instantiated with an image path to load an image,
    and provides methods for various image utility operations. 
    Think of it as the "Model" in the MVC pattern.
    """
    def __init__(self, image_path: str):
        """
        Initializes the ImageProcessor by loading an image from the given path.
        Supports standard image formats and Sony ARW raw files.
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Error: Image file not found at '{image_path}'")

        self._image_path = image_path
        self._image_data = None
        self._is16bit = False
        self._file_extension = os.path.splitext(self.image_path)[1].lower()
        self._exif_handler = None # Initialize to None

        # Load the image (depending on the file extension)
        if self.file_extension == '.arw': # Load 16-bit RAW image data
            self._image_data = image_utils.load_arw_image(self.image_path, output_bps=16)
            self._exif_handler = ExifWrapper(self.image_path)
        else: # All other 8 bit image formats are handled by Pillow
            pil_image = PILImage.open(self.image_path)
            self._exif_handler = ExifWrapper(pil_image)
            self._image_data = np.array(pil_image)

        if self._image_data.dtype == np.uint16:
            self._is16bit = True

        if self._image_data is None:
            raise IOError(f"Error: Could not read image from '{self.image_path}'")

        print(f"image loaded: {self.image_path}")
        print(f"  image_data dtype: {self._image_data.dtype}")
        print(f"  image_data shape: {self._image_data.shape}")
        # TODO: how do I find out infos about the color depth?
        # HIF have BitDepthChroma and BitDepthLuma in EXIF, ARW and JPG have BitsPerSample
        # but I ideally I don't want to rely on EXIF data for this

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
    def is16bit(self) -> bool:
        """Returns True if the image is 16-bit."""
        return self._is16bit

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
        if self.is16bit:
            data = image_utils.convert_16bit_to_8bit(self._image_data)
        else:
            data = self._image_data

        resized_image = cv2.resize(data, (input_width, input_height))
        model_input_image = resized_image.astype(np.float32)
        model_input_image /= 255.0
        model_input_image = model_input_image.transpose(2, 0, 1)
        model_input_image = np.expand_dims(model_input_image, axis=0)
        return model_input_image


    def draw_boxes(self, boxes: list) -> np.ndarray:
        """Draws bounding boxes on a copy of the loaded image."""
        output_image = self._image_data.copy()

        if self.is16bit:
            color = (0, 65535, 0)  # Green for 16-bit images
        else:
            color = (0, 255, 0)   # Green for 8-bit images

        for box in boxes:
            x, y, w, h = box
            x2 = x + w
            y2 = y + h
            cv2.rectangle(output_image, (x, y), (x2, y2), color, 2)
        return output_image

    def crop(self, rect: tuple[int, int, int, int]):
        """Crops the image to the given rectangle tuple (x, y, w, h)."""
        x, y, w, h = rect
        self._image_data = self._image_data[y:y+h, x:x+w]