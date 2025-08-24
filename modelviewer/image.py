import os
import cv2
import rawpy
import numpy as np
from PIL import Image as PILImage
import pillow_heif

from .exif import Exif

pillow_heif.register_heif_opener()


class Image:
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
            self._image_data = Image.load_arw_image(self.image_path, output_bps=16)
            self._exif_handler = Exif(self.image_path)
        else: # All other 8 bit image formats are handled by Pillow
            pil_image = PILImage.open(self.image_path)
            self._exif_handler = Exif(pil_image)
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
    def exif(self) -> Exif:
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

    

    @staticmethod
    def load_arw_image(path: str, output_bps=16) -> np.ndarray:
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

    @staticmethod
    def convert_16bit_to_8bit(image_16bit: np.ndarray) -> np.ndarray:
        """
        Converts a 16-bit image (uint16) to an 8-bit image (uint8) by scaling.
        """
        if image_16bit is None:
            raise ValueError("Input image data cannot be None.")
        if image_16bit.dtype != np.uint16:
            raise TypeError(f"Input image must be of dtype uint16, but got {image_16bit.dtype}.")

        # To convert from 16-bit to 8-bit, we right-shift the bits by 8.
        # This is equivalent to dividing by 256 and is a standard way to
        # convert 16-bit image data to 8-bit, preserving the most significant bits.
        image_8bit = (image_16bit >> 8).astype(np.uint8)
        return image_8bit

    @staticmethod
    def save_16bit_image(image_16bit: np.ndarray, output_path: str):
        """
        Save a 16-bit image to the specified path (PNG or TIFF).
        The file format is inferred from the output_path extension.
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

    @staticmethod
    def save_image_data_as(image_data: np.ndarray, output_path: str):
        """Converts and saves an image to the given file path and target format."""
        print(f"Saving image to {output_path}")

        if image_data.dtype == np.uint16:
            file_extension = os.path.splitext(output_path)[1].lower()
            if file_extension in ('.png', '.tiff', '.tif'):
                Image.save_16bit_image(image_data, output_path)
            else:  # reduce to 8 bit and save
                print(f"Format '{file_extension}' does not support 16-bit. Converting to 8-bit for saving.")
                image_8bit = Image.convert_16bit_to_8bit(image_data)
                if not cv2.imwrite(output_path, image_8bit):
                    raise IOError(f"Error: Could not save converted 8-bit image to {output_path}")
        else:
            if not cv2.imwrite(output_path, image_data):
                raise IOError(f"Error: Could not save image to {output_path}")

    def preprocess_for_onnx(self, input_width: int, input_height: int) -> np.ndarray:
        """
        Preprocesses an image for ONNX model inference.
        - Resizes to the target dimensions.
        - Converts to float32 and normalizes to [0, 1].
        - Transposes from HWC to CHW format.
        - Adds a batch dimension.
        """
        if self.is16bit:
            data = self.convert_16bit_to_8bit(self._image_data)
        else:
            data = self._image_data

        resized_image = cv2.resize(data, (input_width, input_height))
        model_input_image = resized_image.astype(np.float32)
        model_input_image /= 255.0
        model_input_image = model_input_image.transpose(2, 0, 1)
        model_input_image = np.expand_dims(model_input_image, axis=0)
        return model_input_image

    def save_as(self, output_path: str):
        """Saves an image to the given file path."""
        print(f"Saving image to {output_path}")

        if self.is16bit:
            file_extension = os.path.splitext(output_path)[1].lower()
            if file_extension in ('.png', '.tiff', '.tif'):
                Image.save_16bit_image(self._image_data, output_path)
            else:  # Reduce to 8 bit and save
                print(f"Format '{file_extension}' does not support 16-bit. Converting to 8-bit for saving.")
                image_8bit = self.convert_16bit_to_8bit(self._image_data)
                if not cv2.imwrite(output_path, image_8bit):
                    raise IOError(f"Error: Could not save converted 8-bit image to {output_path}")
        else:
            if not cv2.imwrite(output_path, self._image_data):
                raise IOError(f"Error: Could not save image to {output_path}")

    def save_with_boxes(self, output_path: str, boxes: list):
        """Saves an image with bounding boxes drawn on it to the given file path."""
        image_with_boxes = self.draw_boxes(boxes)
        Image.save_image_data_as(image_with_boxes, output_path)

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

    def crop(self, rect):
        """Crops the image to the given rectangle."""
        x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
        self._image_data = self._image_data[y:y+h, x:x+w]