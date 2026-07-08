import os

import cv2
import numpy as np
import rawpy

from . import image_utils
from .image_object import ImageObject
from .structures import ImageMode

RAW_EXTENSIONS = ('.arw', '.nef', '.cwr', '.cr2', '.cr3', '.orf', '.pef')


class RawImageObject(ImageObject):
    """ImageObject subclass for RAW image formats (e.g., .arw, .nef)."""

    def __init__(self, image_path: str):
        """Initializes the object by loading a RAW image file using rawpy."""
        super().__init__(image_path)
        # validate file extension
        if self._file_extension not in RAW_EXTENSIONS:
            raise ValueError(f"Invalid RAW file extension \"{self._file_extension}\". Expected {RAW_EXTENSIONS}")

        print(f"Loading RAW file: {self.image_path}")
        self._image_data = self._load_raw_image_data(self.image_path, output_bps=16)
        self._mode = ImageMode.RGB
        if self._image_data.dtype == np.uint16:
            self._original_bpc = 16
        else:
            self._original_bpc = 8

        if self._image_data is None:
            raise OSError(f"Error: Could not read image from '{self.image_path}'")

        self._exif_dict = self._load_exif_data()

    def _load_raw_image_data(self, path: str, output_bps=16) -> np.ndarray:
        """
        Opens a Sony ARW raw file, processes it, and returns it as 8 or 16-bit RGB numpy array.
        The bit depth of the output is determined by the output_bps parameter.
        """
        print(f"Reading RAW file: {path}")
        # rawpy.imread(path) hands the path to LibRaw's own file opener, which has the
        # same MAX_PATH/Unicode issues on Windows as cv2's. Passing a file object instead
        # makes rawpy read the bytes via open_buffer(), sidestepping LibRaw's path handling.
        with open(self.long_image_path, "rb") as f, rawpy.imread(f) as raw:
            print("Loading and processing RAW image...")
            # Process the raw image to get an RGB image
            # The output is 16-bit if output_bps=16
            rgb_image_data = raw.postprocess(
                use_camera_wb=True,
                no_auto_bright=True,
                output_bps=output_bps, # 16 or 8 bit output
                four_color_rgb=True,
                gamma=(2.222, 4.5),    # power,slope: default is (2.222, 4.5) for rec. BT.709
                bright=2.0,
                #user_wb=[10058.0, 1024.0, 1207.0, 1024.0],
                fbdd_noise_reduction=rawpy.FBDDNoiseReductionMode.Off,
                demosaic_algorithm=rawpy.DemosaicAlgorithm.DCB,
                dcb_iterations=3,
                dcb_enhance=True
            )
        # Returns the image as a 8 or 16-bit RGB numpy array
        return rgb_image_data

    def _save_16bit_image(self, image_16bit: np.ndarray, output_path: str):
        """
        Saves a 16-bit numpy array as a 16 bit PNG or TIFF file.
        The file format is inferred from the output_path extension.

        Args:
            image_16bit (np.ndarray): The 16-bit image data to save (dtype must be uint16).
            output_path (str): The path where the image will be saved.
        """
        if image_16bit.dtype != np.uint16:
            raise TypeError(f"Input image must be of dtype uint16, but got {image_16bit.dtype}.")

        file_format = os.path.splitext(output_path)[1].lower()
        if file_format.lower() not in ('.png', '.tiff'):
            raise ValueError(f"Unknown file format for saving 16-bit image: {file_format}")

        # Convert the image from RGB to BGR format for OpenCV by reversing the order of its color channels
        # using a NumPy array slicing operation that reverses the order of the last dimension.
        # The processed_image has shape (height, width, 3), where the last dimension represents RGB channels (Red, Green, Blue)
        # then [...,::-1] will reverse this to BGR order (Blue, Green, Red).
        bgr_image = image_16bit[...,::-1]

        # Set parameters based on file format
        if file_format.lower() == '.tiff':
            params = [cv2.IMWRITE_TIFF_COMPRESSION, 8]  # DEFLATE compression
            image_utils.imwrite(output_path, bgr_image, params)
        else:  # PNG
            image_utils.imwrite(output_path, bgr_image)

    def save_cropped(self, rect: tuple[int, int, int, int], output_path: str):
        """Saves a cropped version of the RAW image as a 16-bit PNG file."""
        output_path = os.path.splitext(output_path)[0] + '.png'
        print(f"Cropping RAW image file: {self.image_path}")

        x, y, w, h = rect
        cropped_np_array = self._image_data[y:y+h, x:x+w]

        cropped_np_array = self._apply_exposure_correction(cropped_np_array)

        self._save_16bit_image(cropped_np_array, output_path)
