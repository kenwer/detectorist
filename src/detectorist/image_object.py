import os
import shutil
from abc import ABC, abstractmethod
from fractions import Fraction
from typing import Any

import cv2
import numpy as np
from PIL import Image as PILImage
from PIL.ExifTags import GPSTAGS, IFD, TAGS

from . import image_utils
from .structures import CaseInsensitiveDict, ImageMode


class ImageObject (ABC):
    """
    An abstract base class for image processing.

    This class and its subclasses are used to handle image loading and
    processing. It should be instantiated using the `create(image_path)`
    factory method, which returns an appropriate subclass based on the
    image file type.

    It provides methods for various image utility operations and is designed
    to act as the "Model" in an MVC pattern for image data.
    """
    _supported_extensions = None

    @staticmethod
    def get_supported_extensions() -> tuple:
        """
        Returns a tuple of supported image file extensions.
        Imports are local to prevent circular dependencies.
        """
        if ImageObject._supported_extensions is None:
            from .heif_image_object import HEIF_EXTENSIONS
            from .opencv_image_object import STANDARD_IMG_EXTENSIONS
            from .raw_image_object import RAW_EXTENSIONS
            ImageObject._supported_extensions = HEIF_EXTENSIONS + RAW_EXTENSIONS + STANDARD_IMG_EXTENSIONS
        return ImageObject._supported_extensions

    def __init__(self, image_path: str):
        """
        Initializes the ImageObject with an image path.
        Image data loading is handled by subclasses.
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Error: Image file not found at '{image_path}'")

        self._image_path = image_path
        self._image_data = None
        self._original_bpc = None
        self._mode: ImageMode
        self._file_extension = os.path.splitext(self.image_path)[1].lower()
        self._exif_data = CaseInsensitiveDict()
        self._exposure_correction = False

    @staticmethod
    def _parse_fraction(value, round_to=2):
        """
        Convert fractional or float-like string to float, handling various edge cases.
        It covers three main scenarios:
            1. Fractional strings ("-3/10")
            2. Float-like strings ("-0.3")
            3. Actual numbers (-0.3)

        Args:
            value (str or numeric): Value to convert
            round_to (int, optional): Number of decimal places to round to. Defaults to 2.

        Returns:
            float or original value if conversion fails
        """
        if isinstance(value, int | float):
            return round(value, round_to)

        if not isinstance(value, str):
            return value

        if '/' in value:
            try:
                num, denom = map(float, value.split('/'))
                return round(num / denom, round_to) if denom != 0 else value
            except (ValueError, TypeError):
                return value  # Failed to parse fraction

        # If not a fraction, try to convert to float directly
        try:
            return round(float(value), round_to)
        except (ValueError, TypeError):
            return value  # Failed to convert, return original

    @staticmethod
    def _format_exposure_time(exposure_time):
        """
        Converts exposure time to a fraction string representation.

        This function takes an exposure time input and converts it to a fraction
        format (numerator/denominator) with a maximum denominator of 8000.

        Args:
            exposure_time (str or numeric): The exposure time to be formatted.
                Can be a string (including existing fraction strings),
                integer, or float.

        Returns:
            str: A fraction representation of the exposure time.
                 - If input is already a fraction string, returns it as-is
                 - If input cannot be converted to float, returns original input
                 - Otherwise, returns a simplified fraction string

        Examples:
            >>> _format_exposure_time(0.005)
            '1/200'
            >>> _format_exposure_time('1/250')
            '1/250'
            >>> _format_exposure_time(1/30)
            '1/30'
        """
        # If it's already a string with '/', return as-is
        if isinstance(exposure_time, str) and '/' in exposure_time:
            return exposure_time

        # Try to convert to float, if it fails, return the original value *shrug*
        try:
            exposure_float = float(exposure_time)
        except (ValueError, TypeError):
            return exposure_time

        # Use Fraction to get a precise rational representation
        frac = Fraction(exposure_float).limit_denominator(8000)

        # Convert to string representation
        return f"{frac.numerator}/{frac.denominator}"

    @staticmethod
    def _load_exif_data_pil(img: PILImage) -> CaseInsensitiveDict:
        """
        Loads EXIF data from a (non-RAW) image file using Pillow.
        """
        exif_data = CaseInsensitiveDict()
        exif = img.getexif()

        # Extract base tags
        for k, v in exif.items():
            tag_name = TAGS.get(k, k)
            if isinstance(v, bytes):
                try:
                    exif_data[f"Image {tag_name}"] = v.decode(errors='strict').strip()
                except UnicodeDecodeError:
                    exif_data[f"Image {tag_name}"] = repr(v)
            else:
                exif_data[f"Image {tag_name}"] = v

        # Extract IFD tags
        for ifd_id in IFD:
            try:
                ifd = exif.get_ifd(ifd_id)
                ifd_name = ifd_id.name

                # Choose appropriate tag resolver
                resolve = GPSTAGS if ifd_id == IFD.GPSInfo else TAGS

                for k, v in ifd.items():
                    tag_name = resolve.get(k, k)
                    full_tag_name = f"{ifd_name} {tag_name}"

                    val = v
                    if isinstance(v, bytes):
                        try:
                            val = v.decode(errors='strict').strip()
                        except UnicodeDecodeError:
                            val = repr(v)

                    if full_tag_name == 'Exif FNumber':
                        val = ImageObject._parse_fraction(val)
                    elif full_tag_name == 'Exif ExposureTime':
                        val = ImageObject._format_exposure_time(val)
                    elif full_tag_name == 'Exif FocalLength':
                        val = ImageObject._parse_fraction(val, 2)
                    elif full_tag_name == 'Exif ExposureBiasValue':
                        val = ImageObject._parse_fraction(val)

                    exif_data[full_tag_name] = val

            except KeyError:
                continue
        return exif_data

    @classmethod
    def create(cls, image_path: str) -> 'ImageObject':
        """
        Factory method to create the appropriate ImageObject based on file extension.

        Args:
            image_path (str or Path): Path to the image file

        Returns:
            ImageObject: Appropriate subclass instance

        Raises:
            ValueError: If no matching image type is found
        """
        from .heif_image_object import HEIF_EXTENSIONS, HeifImageObject
        from .opencv_image_object import STANDARD_IMG_EXTENSIONS, OpencvImageObject
        from .pillow_image_object import PillowImageObject
        from .raw_image_object import RAW_EXTENSIONS, RawImageObject

        file_extension = os.path.splitext(image_path)[1].lower()

        if file_extension in HEIF_EXTENSIONS:
            return HeifImageObject(image_path)
        elif file_extension in RAW_EXTENSIONS:
            return RawImageObject(image_path)
        elif file_extension in STANDARD_IMG_EXTENSIONS:
            # For standard extensions, we check the mode to see if it's paletted
            with PILImage.open(image_path) as pil_image:
                if pil_image.mode in ('P', 'LA', 'CMYK'):
                    return PillowImageObject(image_path)
                else:
                    return OpencvImageObject(image_path)
        else:
            raise ValueError(f"Unsupported image file extension: \"{file_extension}\" with path: {image_path}")

    @property
    def exif_data(self) -> CaseInsensitiveDict:
        """Returns Exif handler object for this image."""
        return self._exif_data

    def get(self, key: str, default: Any = "-") -> Any:
        """
        Returns the value for a specific EXIF key.

        Args:
            key (str): The EXIF tag name (e.g., 'Image Model', 'EXIF ExposureTime').
            default (Any): The default value to return if the key doesn't exist.

        Returns:
            The value of the tag, or the default value if the key doesn't exist.
        """
        return self._exif_data.get(key, default)

    def get_exposure_compensation(self) -> float:
        """
        Returns the exposure compensation value based on 'Exif ExposureBiasValue' as a float.
        """
        ev_comp = self.get('Exif ExposureBiasValue')
        try:
            return float(ev_comp)
        except (ValueError, TypeError):
            if isinstance(ev_comp, str) and '/' in ev_comp:
                try:
                    num, den = ev_comp.split('/')
                    if float(den) != 0:
                        return float(num) / float(den)
                except (ValueError, ZeroDivisionError):
                    return 0.0
            return 0.0

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

    @property
    def mode(self) -> ImageMode:
        """Returns the color mode of the loaded image (e.g., 'RGB', 'RGBA', 'BGR', 'GRAY')."""
        return self._mode

    @property
    def height(self) -> int:
        """Returns the height of the image."""
        if self._image_data is not None:
            return self._image_data.shape[0]
        return 0

    @property
    def width(self) -> int:
        """Returns the width of the image."""
        if self._image_data is not None:
            return self._image_data.shape[1]
        return 0

    @property
    def exposure_correction(self) -> bool:
        """Returns whether exposure correction based on EXIF data is enabled."""
        return self._exposure_correction

    @exposure_correction.setter
    def exposure_correction(self, value: bool):
        """Sets whether exposure correction based on EXIF data is enabled.
        This controls if exposure correction is applied when saving cropped images."""
        print(f"Setting exposure_correction to {value} for image: {self.image_path}")
        self._exposure_correction = value

    @property
    def image_data_bgr_8bit(self) -> np.ndarray:
        """
        Returns image_data in 8-bit BGR format
        """
        # Convert to 8-bit if necessary
        if self._original_bpc > 8:
            data_8bit = image_utils.convert_16bit_to_8bit(self._image_data)
        else:
            data_8bit = self._image_data.astype(np.uint8)
        current_mode = self._mode

        # Convert to BGR based on the current mode
        if current_mode == ImageMode.BGR:
            bgr_data = data_8bit
        elif current_mode == ImageMode.BGRA:
            bgr_data = cv2.cvtColor(data_8bit, cv2.COLOR_BGRA2BGR)
        elif current_mode == ImageMode.RGB:
            bgr_data = cv2.cvtColor(data_8bit, cv2.COLOR_RGB2BGR)
        elif current_mode == ImageMode.RGBA:
            bgr_data = cv2.cvtColor(data_8bit, cv2.COLOR_RGBA2BGR)
        elif current_mode == ImageMode.GRAY:
            bgr_data = cv2.cvtColor(data_8bit, cv2.COLOR_GRAY2BGR)
        else:
            raise ValueError(f"Unsupported image mode for BGR conversion: {current_mode}")

        return bgr_data.copy()

    @property
    def image_data_rgb_8bit(self) -> np.ndarray:
        """
        Returns image_data in 8-bit RGB format, suitable for display in UI.
        This is a convenience wrapper around image_data_bgr_8bit.
        """
        bgr_image = self.image_data_bgr_8bit
        rgb_image = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2RGB)
        return rgb_image

    def preprocess_for_onnx(self, input_width: int, input_height: int) -> np.ndarray:
        """
        Preprocesses an image for ONNX model inference.
        - Converts to 8-bit BGR.
        - Resizes to the target dimensions.
        - Converts to float32 and normalizes to [0, 1].
        - Transposes from HWC to CHW format.
        - Adds a batch dimension.
        """
        bgr_data = self.image_data_bgr_8bit

        resized_image = cv2.resize(bgr_data, (input_width, input_height))
        model_input_image = resized_image.astype(np.float32)
        model_input_image /= 255.0
        model_input_image = model_input_image.transpose(2, 0, 1)
        model_input_image = np.expand_dims(model_input_image, axis=0)
        return model_input_image

    def print_image_data_debug_info(self):
        """Prints debug information about the loaded image data."""
        # Debug info about the loaded image
        print(f"image loaded: {self.image_path}")
        print(f"  image_data dtype: {self.image_data.dtype}")
        print(f"  image_data shape: {self.image_data.shape}")
        print(f"  image_data mode: {self.mode}")
        # The actual bit depth of the data in the numpy array
        numpy_bits_per_channel = self.image_data.dtype.itemsize * 8
        # If self._image_data.ndim is 3, the number of channels is the 3rd dimension (self._image_data.shape[2]).
        # If the dimensions are 2, it's a single-channel (grayscale) image.
        num_channels = 1
        if self.image_data.ndim == 3:
            num_channels = self.image_data.shape[2]
        print(f"  number of channels: {num_channels}")
        print(f"  original bit depth per channel: {self.original_bpc}")
        print(f"  numpy array bit depth per channel: {numpy_bits_per_channel}")
        print(f"  color depth (based on numpy array): {numpy_bits_per_channel * num_channels} bpp")
        print(f"  color depth (based on original bit depth): {self.original_bpc * num_channels} bpp")

    def copy_image(self, target_dir_path):
        """Copies the original image file to the specified output directory preserving its file name."""
        input_file_name = os.path.basename(self._image_path)
        output_path = os.path.join(target_dir_path, input_file_name)
        shutil.copy2(self._image_path, output_path)

    @abstractmethod
    def save_cropped(self, rect: tuple[int, int, int, int], output_path: str):
        """
        Saves a cropped version of the image to the specified output directory.
        The cropped image retains the original file format and file extension except
        for RAW files are encoded as 16bit PNG as we cannot save proprietary raw file formats.

        Args:
            rect (tuple): A tuple of (x, y, width, height) for the crop.
            output_path (str): The full path to save the cropped image file.
        """
        pass





