import os
import shutil
from abc import ABC, abstractmethod
from enum import Enum

import cv2
import numpy as np
import pillow_heif
import rawpy
from PIL import Image as PILImage

from . import image_utils
from .exif_wrapper import ExifWrapper


class ImageMode(Enum):
    """
    Represents the color mode of an image.
    """
    RGB = "RGB"
    RGBA = "RGBA"
    BGR = "BGR"
    BGRA = "BGRA"
    GRAY = "GRAY"
    PALETTE = "P"


# Ensure the HEIF Pillow plugin is registered
pillow_heif.register_heif_opener()

# Files with these extensions will be treated as HEIF files (using pillow_heif)
HEIF_EXTENSIONS = ('.heic', '.heics', '.heif', '.heifs', '.hif')

# Files with these extensions will be treated as RAW files (using rawpy)
RAW_EXTENSIONS = ('.arw', '.nef', '.cwr', 'cr2', 'cr3', 'orf', 'pef' )

# All supported image file extensions
STANDARD_IMG_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.bmp')


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
    SUPPORTED_IMG_EXTENSIONS = STANDARD_IMG_EXTENSIONS + HEIF_EXTENSIONS + RAW_EXTENSIONS

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
        self._exif_handler = None
        self._exposure_correction = False

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
        """Returns image_data in 8-bit BGR format"""
        # Paletted images are handled by the overridden method in PalettedImageObject
        if self._mode == ImageMode.PALETTE:
            raise NotImplementedError("This should be handled by a subclass.")

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


class HeifImageObject(ImageObject):
    """ImageObject subclass for HEIF images (.heic, .heif, .hif)."""
    def __init__(self, image_path: str):
        """Initializes the object by loading a HEIF image file using pillow_heif."""
        super().__init__(image_path)
        # Validate file extension
        if self._file_extension not in HEIF_EXTENSIONS:
            raise ValueError(f"Invalid HEIF file extension \"{self._file_extension}\". Expected {HEIF_EXTENSIONS}")

        print(f"Loading HEIF file: {self.image_path}")
        heif_file = pillow_heif.open_heif(self.image_path, convert_hdr_to_8bit=False)
        print(f"  Image\n\tmode: {heif_file[0].mode}, size: {heif_file[0].size}, stride: {heif_file[0].stride}, data length: {len(heif_file[0].data)}")

        # Store metadata
        self._original_bpc = heif_file.info.get('bits', heif_file.info.get('bit_depth', 8))
        self._chroma = heif_file.info.get('chroma', '420')
        self._nclx_profile = heif_file.info.get('nclx_profile')
        self._exif = heif_file.info.get('exif')
        self._xmp = heif_file.info.get('xmp')
        self._heif_mode = heif_file[0].mode
        # Map pillow_heif modes to our descriptive strings
        if self._heif_mode == 'L':
            self._mode = ImageMode.GRAY
        elif self._heif_mode.startswith('RGB'):
            self._mode = ImageMode.RGB
        elif self._heif_mode.startswith('RGBA'):
            self._mode = ImageMode.RGBA
        else:
            raise ValueError(f"Unsupported HEIF image mode: {self._heif_mode}")

        # pillow-heif appears to rotate the image data based on EXIF orientation automatically.
        # So we create a numpy array view of the (rotated) image data and also
        # make a copy to ensure we have our own data (as the underlying buffer may be freed when heif_file is closed).
        self._image_data = np.asarray(heif_file[0]).copy()

        self._exif_handler = ExifWrapper(self.image_path)

        if self._image_data is None:
            raise OSError(f"Error: Could not read image from '{self.image_path}'")

    def _get_exif_orientation(self, exif):
        """
        Extracts the orientation value from EXIF data.
        Defaults to 1 (Normal) if orientation tag is not present.

        This function parses the raw EXIF data bytes to find the orientation
        tag (0x0112). If the EXIF data is not present or the orientation tag
        is missing, it defaults to 1, which corresponds to the "Normal"
        orientation.

        Args:
            exif (bytes or None): The raw EXIF data from the image.
        Returns:
            int: The EXIF orientation value (1-8), or 1 as a default.
        """
        if not exif:
            return 1
        # use Pillow's Exif class to parse the EXIF data (from PIL import Image)
        # note: this is different from our custom Exif class in exif.py
        exif_obj = PILImage.Exif()
        exif_obj.load(exif)
        return exif_obj.get(0x0112, 1)

    def _get_human_readable_exif_orientation(self, orientation):
        """
        Returns a human-readable string for an EXIF orientation value.

        Args:
            orientation (int): The EXIF orientation value (1-8).
        Returns:
            str: A human-readable description of the orientation.
        """
        orientation_map = {
            1: "Normal",
            2: "Mirrored horizontal",
            3: "Rotated 180",
            4: "Mirrored vertical",
            5: "Mirrored horizontal then rotated 90 CCW",
            6: "Rotated 90 CW",
            7: "Mirrored horizontal then rotated 90 CW",
            8: "Rotated 90 CCW"
        }
        return orientation_map.get(orientation, "Unknown")

    def save_cropped(self, rect: tuple[int, int, int, int], output_path: str, quality=80):
        """
        Saves a cropped version of the HEIF image, preserving its original
        bit depth, metadata, and HEIF format.
        """
        print(f"Cropping HEIF image file: {self.image_path}")

        # Use stored metadata
        bit_depth = self._original_bpc
        chroma = self._chroma
        nclx_profile = self._nclx_profile
        exif = self._exif
        xmp = self._xmp

        orientation = self._get_exif_orientation(exif)
        orientation_text = self._get_human_readable_exif_orientation(orientation)
        print(f"  EXIF orientation: {orientation} ({orientation_text})")

        # The image data in self._image_data is already rotated based on EXIF orientation by pillow-heif
        rotated_np_array = self._image_data

        # Crop the array using numpy slicing
        # The cropping performed on the rotated_np_array before we reverse the pixel data arrangement to the original value so that the crop rectangle matches the users intend.
        x, y, w, h = rect
        cropped_np_array = rotated_np_array[y:y+h, x:x+w]

        # Reverse the pixel data arrangement based on the EXIF orientation to get the original pixel data arrangement
        if orientation == 1: # Normal
            unrotated_np = cropped_np_array
        elif orientation == 2: # Mirrored horizontal
            unrotated_np = np.fliplr(cropped_np_array)
        elif orientation == 3: # Rotated 180
            unrotated_np = np.rot90(cropped_np_array, 2)
        elif orientation == 4: # Mirrored vertical
            unrotated_np = np.flipud(cropped_np_array)
        elif orientation == 5: # Mirrored horizontal then rotated 90 CCW (by pillow-heif, which is rot270)
            # To reverse: rot90(data) then fliplr
            unrotated_np = np.fliplr(np.rot90(cropped_np_array, 1))
        elif orientation == 6: # Rotated 90 CW (by pillow-heif, which is rot270)
            # To reverse: rot90
            unrotated_np = np.rot90(cropped_np_array, 1)
        elif orientation == 7: # Mirrored horizontal then rotated 90 CW (by pillow-heif, which is rot90)
            # To reverse: rot270(data) then fliplr
            unrotated_np = np.fliplr(np.rot90(cropped_np_array, -1))
        elif orientation == 8: # Rotated 90 CCW (by pillow-heif, which is rot90)
            # To reverse: rot270
            unrotated_np = np.rot90(cropped_np_array, -1)
        else:
            unrotated_np = cropped_np_array

        size = (unrotated_np.shape[1], unrotated_np.shape[0])

        # Apply exposure correction based on EXIF data if requested
        if self._exposure_correction:
            ev_comp = self.exif_wrapper.get('Exif ExposureBiasValue')
            if ev_comp is not None and ev_comp != 0.0:
                ev_comp = -ev_comp
                print(f"  Applying exposure correction of {ev_comp} EV based on EXIF data")
                unrotated_np = image_utils.adjust_exposure(unrotated_np, ev_comp, 2.2, bit_depth)

        data = unrotated_np.tobytes()

        # HEIF images with a bit depth larger than 8 (e.g. 10 or 12 bit) are stored in 16 bit
        # nd_arrays as pillow-heif scaled up the pixel values when loading to fill the full
        # 16-bit range (0-65535). In those cases the self._heif_mode also indicates 16 bit
        # ("RGB;16") while self._original_bpc shows the original (non scaled) bit depth (e.g. 10
        # or 12).
        # When creating a new HEIF image from the scaled and cropped numpy array using
        # pillow_heif.from_bytes() we need to submit a raw_mode that matches the actual numpy array
        # structure (e.g. 16-bit for images with a original bit depth of 10 bit).
        # For images with bit depth > 8, pillow-heif expects a 'raw_mode' parameter to correctly
        # interpret the 16-bit data buffer.
        new_heif_image = pillow_heif.from_bytes(mode=self._heif_mode, size=size, data=data, raw_mode=self._heif_mode)

        # Adjust Exif Image Width & Height to the cropped size if Exif data exists
        if exif:
            exif_obj = PILImage.Exif()
            exif_obj.load(exif)
            exif_obj[0xa002] = size[0]  # Exif Image Width
            exif_obj[0xa003] = size[1]  # Exif Image Height
            updated_exif = exif_obj.tobytes()
        else:
            updated_exif = None

        # Save the new image, preserving original bit depth and chroma plus meta data for orientation
        # The bit_depth parameter explicitly instructs the HEIF encoder to save the final file with the specified bit depth (e.g. 10 bit).
        #  For images with >8 bit, it knows the in-memory data is 16-bit and it knows the desired output is e.g. 10-bit.
        #  It scales the pixel values back down from the [0, 65535] range to the [0, 1023] range before encoding and saving the file.
        new_heif_image.save(output_path, format="HEIF", quality=quality, bit_depth=bit_depth, chroma=chroma, nclx_profile=nclx_profile, exif=updated_exif, xmp=xmp)
        #print(f"Cropped image to {w}x{h} at ({x},{y}) and saved to {output_path}")


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

        self._exif_handler = ExifWrapper(self.image_path)

        if self._image_data is None:
            raise OSError(f"Error: Could not read image from '{self.image_path}'")

    def _load_raw_image_data(self, path: str, output_bps=16) -> np.ndarray:
        """
        Opens a Sony ARW raw file, processes it, and returns it as 8 or 16-bit RGB numpy array.
        The bit depth of the output is determined by the output_bps parameter.
        """
        print(f"Reading RAW file: {path}")
        with rawpy.imread(path) as raw:
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
            cv2.imwrite(output_path, bgr_image, params)
        else:  # PNG
            cv2.imwrite(output_path, bgr_image)

    def save_cropped(self, rect: tuple[int, int, int, int], output_path: str):
        """Saves a cropped version of the RAW image as a 16-bit PNG file."""
        output_path = os.path.splitext(output_path)[0] + '.png'
        print(f"Cropping RAW image file: {self.image_path}")

        x, y, w, h = rect
        cropped_np_array = self._image_data[y:y+h, x:x+w]

        # Apply exposure correction based on EXIF data if requested
        if self._exposure_correction:
            ev_comp = self.exif_wrapper.get('Exif ExposureBiasValue')
            if ev_comp is not None and ev_comp != 0.0:
                ev_comp = -ev_comp
                print(f"  Applying exposure correction of {ev_comp} EV based on EXIF data")
                cropped_np_array = image_utils.adjust_exposure(cropped_np_array, ev_comp, 2.2, self._original_bpc)

        self._save_16bit_image(cropped_np_array, output_path)


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

        self._exif_handler = ExifWrapper(self.image_path)

    def save_cropped(self, rect: tuple[int, int, int, int], output_path: str):
        """Saves a cropped version of the image, preserving original format."""
        print(f"Cropping image file: {self.image_path}")

        x, y, w, h = rect

        cropped_data = self.image_data[y:y+h, x:x+w]

        # Apply exposure correction based on EXIF data if requested
        if self._exposure_correction:
            ev_comp = self.exif_wrapper.get('Exif ExposureBiasValue')
            if ev_comp is not None and ev_comp != 0.0:
                ev_comp = -ev_comp
                print(f"  Applying exposure correction of {ev_comp} EV based on EXIF data")
                cropped_data = image_utils.adjust_exposure(cropped_data, ev_comp, 2.2, self._original_bpc)

        # The data is already in BGR/BGRA format, which cv2.imwrite expects.
        cv2.imwrite(output_path, cropped_data)
        print(f"  Cropped image saved to {output_path}")


class PillowImageObject(ImageObject):
    """
    ImageObject subclass for image modes requiring special handling via Pillow.

    This class uses the Pillow library to load and process images with specific
    or complex modes that are not handled by the other subclasses. It is responsible
    for:
    - Paletted images (mode 'P'), such as GIFs.
    - Grayscale with an alpha channel (mode 'LA').
    - CMYK images.

    It keeps the Pillow image object in memory to simplify operations.
    """
    def __init__(self, image_path: str):
        """
        Initializes the object by loading a paletted ('P'), grayscale-alpha ('LA'),
        or CMYK image file using the Pillow library.
        """
        super().__init__(image_path)
        self._pil_image = None

        # Validate file extension
        if self._file_extension not in STANDARD_IMG_EXTENSIONS:
            raise ValueError(f"Invalid image file extension \"{self._file_extension}\". Expected {STANDARD_IMG_EXTENSIONS}")

        print(f"Loading image file with Pillow: {self.image_path}")

        self._pil_image = PILImage.open(self.image_path)

        if self._pil_image.mode not in ('P', 'LA', 'CMYK'):
            self._pil_image.close()
            raise ValueError(f"Image at {image_path} is not a P, LA, or CMYK image (mode is {self._pil_image.mode}).")

        self._image_data = np.array(self._pil_image)
        self._original_bpc = self._image_data.dtype.itemsize * 8

        if self._pil_image.mode == 'P':
            self._mode = ImageMode.PALETTE
        elif self._pil_image.mode == 'LA':
            self._mode = ImageMode.GRAY  # Treat as Grayscale with Alpha
        elif self._pil_image.mode == 'CMYK':
            self._mode = ImageMode.BGR  # Will be converted to BGR for display

        self._exif_handler = ExifWrapper(self.image_path)

    def __del__(self):
        """Closes the Pillow image file handle."""
        if hasattr(self, '_pil_image') and self._pil_image:
            self._pil_image.close()

    @property
    def image_data_bgr_8bit(self) -> np.ndarray:
        """Returns image_data in 8-bit BGR format"""
        if self._pil_image.mode == 'P':
            pil_img_rgb = self._pil_image.convert('RGB')
            data_8bit = np.array(pil_img_rgb)
            bgr_data = cv2.cvtColor(data_8bit, cv2.COLOR_RGB2BGR)
        elif self._pil_image.mode == 'LA':
            # Create a light gray background
            bg_color = (240, 240, 240)  # Light gray
            bg = PILImage.new('RGB', self._pil_image.size, bg_color)

            # Paste the LA image onto the background, using its alpha channel as a mask
            bg.paste(self._pil_image, mask=self._pil_image.split()[1])

            # Convert to numpy array and then to BGR
            rgb_data = np.array(bg)
            bgr_data = cv2.cvtColor(rgb_data, cv2.COLOR_RGB2BGR)
        elif self._pil_image.mode == 'CMYK':
            pil_img_rgb = self._pil_image.convert('RGB')
            data_8bit = np.array(pil_img_rgb)
            bgr_data = cv2.cvtColor(data_8bit, cv2.COLOR_RGB2BGR)
        else:
            raise ValueError(f"Unsupported PIL mode in PillowImageObject: {self._pil_image.mode}")

        return bgr_data.copy()

    def save_cropped(self, rect: tuple[int, int, int, int], output_path: str):
        """Saves a cropped version of the image, preserving original format."""
        print(f"Cropping image file with Pillow: {self.image_path}")

        x, y, w, h = rect
        # PIL crop is (left, upper, right, lower)
        pil_cropped_image = self._pil_image.crop((x, y, x + w, y + h))

        # Apply exposure correction based on EXIF data if requested
        if self._exposure_correction:
            ev_comp = self.exif_wrapper.get('Exif ExposureBiasValue')
            if ev_comp is not None and ev_comp != 0.0:
                ev_comp = -ev_comp
                print(f"  Applying exposure correction of {ev_comp} EV based on EXIF data")

                original_mode = pil_cropped_image.mode

                # Determine if we need to handle an alpha channel
                has_alpha = original_mode == 'LA' or (original_mode == 'P' and 'transparency' in pil_cropped_image.info)
                adjust_mode = 'RGBA' if has_alpha else 'RGB'

                # Convert to the appropriate adjustment mode (RGB or RGBA)
                image_for_adjustment = pil_cropped_image.convert(adjust_mode)

                # Perform exposure adjustment on the numpy array
                adjusted_np = np.array(image_for_adjustment)
                adjusted_np = image_utils.adjust_exposure(adjusted_np, ev_comp, 2.2, 8)
                adjusted_pil = PILImage.fromarray(adjusted_np)

                # Convert back to the original mode
                if original_mode == 'P':
                    # Quantize back to a palette.
                    pil_cropped_image = adjusted_pil.quantize()
                else:  # 'LA' or 'CMYK'
                    pil_cropped_image = adjusted_pil.convert(original_mode)

        # Preserve format (e.g., GIF) and transparency
        save_kwargs = {}
        original_format = self._pil_image.format
        if original_format:
            save_kwargs['format'] = original_format

        if self._pil_image.mode == 'P' and self._pil_image.info.get('transparency') is not None:
            save_kwargs['transparency'] = self._pil_image.info.get('transparency')

        pil_cropped_image.save(output_path, **save_kwargs)
        print(f"  Cropped {original_format or 'image'} saved to {output_path}")
