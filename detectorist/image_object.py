import os
import shutil
from abc import ABC, abstractmethod

import cv2
import numpy as np
import pillow_heif
import rawpy
from PIL import Image as PILImage

from . import image_utils
from .exif_wrapper import ExifWrapper
from enum import Enum

class ImageMode(Enum):
    """
    Represents the color mode of an image.
    """
    RGB = "RGB"
    RGBA = "RGBA"
    BGR = "BGR"
    BGRA = "BGRA"
    GRAY = "GRAY"


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
            return StandardImageObject(image_path)
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
    def image_data_bgr_8bit(self) -> np.ndarray:
        """Returns image_data in 8-bit BGR format"""
        # Convert to 8-bit if necessary
        if self._original_bpc > 8:
            data_8bit = image_utils.convert_16bit_to_8bit(self._image_data)
        else:
            data_8bit = self._image_data.astype(np.uint8)

        # Handle RGBA blending if the mode is RGBA
        if self._mode == ImageMode.RGBA:
            alpha = data_8bit[:, :, 3].astype(np.float32) / 255.0
            alpha = np.stack([alpha] * 3, axis=-1)
            rgb = data_8bit[:, :, :3]
            white_bg = np.full_like(rgb, 255)
            data_to_convert = (rgb * alpha + white_bg * (1.0 - alpha)).astype(np.uint8)
            current_mode = ImageMode.RGB # After blending, it's effectively RGB
        else:
            data_to_convert = data_8bit
            current_mode = self._mode

        # Convert to BGR based on the current mode
        if current_mode == ImageMode.BGR:
            bgr_data = data_to_convert
        elif current_mode == ImageMode.BGRA:
            bgr_data = cv2.cvtColor(data_to_convert, cv2.COLOR_BGRA2BGR)
        elif current_mode == ImageMode.RGB:
            bgr_data = cv2.cvtColor(data_to_convert, cv2.COLOR_RGB2BGR)
        elif current_mode == ImageMode.GRAY:
            bgr_data = cv2.cvtColor(data_to_convert, cv2.COLOR_GRAY2BGR)
        else:
            raise ValueError(f"Unsupported image mode for BGR conversion: {current_mode}")

        return bgr_data

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
    def save_cropped(self, rect: tuple[int, int, int, int], output_dir: str):
        """
        Saves a cropped version of the image to the specified output directory.
        The cropped image retains the original file format and file extension except
        for RAW files are encoded as 16bit PNG as we cannot save proprietary raw file formats.

        Args:
            rect (tuple): A tuple of (x, y, width, height) for the crop.
            output_dir (str): Directory to save the cropped image file.
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
        self._bit_depth = heif_file.info.get('bit_depth', 8)
        self._chroma = heif_file.info.get('chroma', '420')
        self._nclx_profile = heif_file.info.get('nclx_profile')
        self._exif = heif_file.info.get('exif')
        self._xmp = heif_file.info.get('xmp')
        # Map pillow_heif modes to our descriptive strings
        if heif_file[0].mode == 'L':
            self._mode = ImageMode.GRAY
        elif heif_file[0].mode == 'RGB':
            self._mode = ImageMode.RGB
        elif heif_file[0].mode == 'RGBA':
            self._mode = ImageMode.RGBA
        else:
            raise ValueError(f"Unsupported HEIF image mode: {heif_file[0].mode}")

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

    def save_cropped(self, rect: tuple[int, int, int, int], output_dir: str, quality=80):
        """
        Saves a cropped version of the HEIF image, preserving its original
        bit depth, metadata, and HEIF format.
        """
        output_path = os.path.join(output_dir, os.path.basename(self.image_path))
        print(f"Cropping HEIF image file: {self.image_path}")

        # Use stored metadata
        bit_depth = self._bit_depth
        chroma = self._chroma
        nclx_profile = self._nclx_profile
        exif = self._exif
        xmp = self._xmp
        mode = self._mode

        orientation = self._get_exif_orientation(exif)
        orientation_text = self._get_human_readable_exif_orientation(orientation)
        print(f"  EXIF orientation: {orientation} ({orientation_text})")

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
        data = unrotated_np.tobytes()
        #data = adjust_exposure(unrotated_np, -1.7*-1.0, 2.2, bit_depth).tobytes()  # just a hard coded (EV=-1.7, gamma=2.2) test to see if we can adjust exposure on the cropped image

        # HEIF images with a bit depth larger than 8 are stored in 16 bit nd_arrays as pillow-heif scaled up the pixel values when loading to fill the full 16-bit range (0-65535).
        # For a 10 bit HEIF, with the bit_depth in raw_mode, we tell pillow-heif "Interpret this 16-bit buffer as 10-bit data".
        # At this point, no data conversion or scaling occurs (at save time, pillow-heif will scale the data down to 10 bit range 0-1023).
        raw_mode = mode
        if bit_depth > 8:
            raw_mode = f"{mode};{bit_depth}"
        
        # Create a new HeifImage from the cropped numpy array using pillow_heif.from_bytes()
        #print(f"Creating new HEIF image with\n\tmode: {mode}, size: {size}, data length: {len(data)}, raw_mode: {raw_mode}")
        new_heif_image = pillow_heif.from_bytes(mode=mode, size=size, data=data, raw_mode=raw_mode)

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

    def save_cropped(self, rect: tuple[int, int, int, int], output_dir: str):
        """Saves a cropped version of the RAW image as a 16-bit PNG file."""
        output_path = os.path.join(output_dir, os.path.basename(self.image_path))
        output_path = os.path.splitext(output_path)[0] + '.png'
        print(f"Cropping RAW image file: {self.image_path}")

        x, y, w, h = rect
        cropped_np_array = self._image_data[y:y+h, x:x+w]

        self._save_16bit_image(cropped_np_array, output_path)


class StandardImageObject(ImageObject):
    """ImageObject subclass for standard 8-bit and 16-bit image formats like PNG, JPEG."""
    def __init__(self, image_path: str):
        """Initializes the object by loading a standard image file using OpenCV."""
        super().__init__(image_path)
        # Validate file extension
        if self._file_extension not in STANDARD_IMG_EXTENSIONS:
            raise ValueError(f"Invalid image file extension \"{self._file_extension}\". Expected {STANDARD_IMG_EXTENSIONS}")

        print(f"Loading standard image file: {self.image_path}")

        image = cv2.imread(self.image_path, cv2.IMREAD_UNCHANGED)
        if image is None:
            raise OSError(f"Error: Could not read image from '{self.image_path}'")

        # Determine original bits per channel based on image mode
        # PNGs for example can be 8 or 16 bit per channel
        if image.dtype == np.uint16:
            self._original_bpc = 16
        else:
            self._original_bpc = 8

        self._image_data = image

        # Determine the mode based on the number of channels
        if len(image.shape) == 2:
            self._mode = ImageMode.GRAY
        elif len(image.shape) == 3:
            if image.shape[2] == 3:
                self._mode = ImageMode.BGR
            elif image.shape[2] == 4:
                self._mode = ImageMode.BGRA
            else:
                raise ValueError(f"Unsupported standard image with {image.shape[2]} channels.")
        else:
            raise ValueError(f"Unsupported standard image with shape {image.shape}.")

        # Keep a PIL image instance for metadata compatibility
        pil_image = PILImage.open(self.image_path)
        self._exif_handler = ExifWrapper(pil_image)

    @property
    def image_data(self) -> np.ndarray:
        """Returns the image data as a NumPy array, in RGB or RGBA format."""
        return self._image_data

    def save_cropped(self, rect: tuple[int, int, int, int], output_dir: str):
        """Saves a cropped version of the image using OpenCV, preserving transparency."""
        output_path = os.path.join(output_dir, os.path.basename(self.image_path))
        print(f"Cropping image file: {self.image_path}")

        x, y, w, h = rect
        cropped_data = self.image_data[y:y+h, x:x+w]

        output_image = cropped_data

        # Ensure PNG format for images with transparency if not already PNG
        if len(output_image.shape) == 3 and output_image.shape[2] == 4 and self._file_extension.lower() != '.png':
            print(f"  Saving with transparency, converting to PNG format.")
            output_path = os.path.splitext(output_path)[0] + '.png'

        cv2.imwrite(output_path, output_image)
