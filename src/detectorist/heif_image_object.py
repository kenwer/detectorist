import numpy as np
import piexif
import pillow_heif
from PIL import Image as PILImage

from . import image_utils
from .image_object import ImageMode, ImageObject

HEIF_EXTENSIONS = ('.heic', '.heics', '.heif', '.heifs', '.hif')


# Ensure the HEIF Pillow plugin is registered
pillow_heif.register_heif_opener()

class HeifImageObject(ImageObject):
    """ImageObject subclass for HEIF images (.heic, .heif, .hif)."""
    def __init__(self, image_path: str):
        """Initializes the object by loading a HEIF image file using pillow_heif."""
        super().__init__(image_path)
        # Validate file extension
        if self._file_extension not in HEIF_EXTENSIONS:
            raise ValueError(f"Invalid HEIF file extension \"{self._file_extension}\". Expected {HEIF_EXTENSIONS}")

        print(f"Loading HEIF file: {image_path}")
        heif_file = pillow_heif.open_heif(self.image_path, convert_hdr_to_8bit=False)

        if heif_file is None or len(heif_file) == 0:
            raise OSError(f"Error: Could not load HEIF image from '{image_path}' or it contains no images.")

        if heif_file[0] is None:
            raise OSError(f"Error: First image in HEIF file '{image_path}' is None.")

        # Store metadata extracted from the HEIF file
        self._original_bpc = heif_file.info.get('bits', heif_file.info.get('bit_depth', 8))
        self._chroma = heif_file.info.get('chroma', '420')
        self._nclx_profile = heif_file.info.get('nclx_profile')
        self._exif = heif_file.info.get('exif')
        self._xmp = heif_file.info.get('xmp')
        self._heif_mode = heif_file[0].mode
        print(f"  Image\n\tmode: {self._heif_mode}, size: {heif_file[0].size}, stride: {heif_file[0].stride}, data length: {len(heif_file[0].data)}, bits per channel: {self._original_bpc}, chroma: {self._chroma}")

        # Map pillow_heif modes to our descriptive strings
        if self._heif_mode == 'L':
            self._mode = ImageMode.GRAY
        elif self._heif_mode.startswith('RGB'):
            self._mode = ImageMode.RGB
        elif self._heif_mode.startswith('RGBA'):
            self._mode = ImageMode.RGBA
        else:
            raise ValueError(f"Unsupported HEIF image mode: {self._heif_mode}")

        # Initialize the image data by copying the pixel data from the heif file. A HEIF container could
        # hold multiple images, but we only load the first. We make a copy to ensure we have our own data
        # as the underlying buffer may be freed when heif_file is closed.
        # Note: pillow-heif appears to rotate the image data based on EXIF orientation automatically. It
        # helps when displaying the image, but we need to be aware of this when cropping and saving later.
        self._image_data = np.asarray(heif_file[0]).copy()

        if self._image_data is None:
            raise OSError(f"Error: Could not read image from '{self.image_path}'")

        # Initialize EXIF data dictionary using the overwritten _load_exif_data() method
        self._exif_dict = self._load_exif_data()
        #self._print_exif_data(self._exif_dict)

        heif_file = None # Allow the Python GC to free resources


    def _load_exif_data(self) -> dict:
        """
        Loads EXIF dict from the raw EXIF that we extracted from the HEIF image file using
        pillow_heif. Returns a `dict` or `None` if no EXIF data is found.
        """
        if self._exif: # self._exif holds the raw EXIF bytes we've got from pillow_heif
            exif_dict = piexif.load(self._exif)
            return exif_dict
        return None

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

        unrotated_np = self._apply_exposure_correction(unrotated_np, bit_depth)

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
            try:
                exif_dict = piexif.load(exif)
                self._update_exif_dimensions(exif_dict, size[0], size[1])
                self._neutralize_exposure_bias(exif_dict)
                updated_exif = piexif.dump(exif_dict)
            except Exception as e:
                print(f"  Could not update EXIF data: {e}")
                updated_exif = exif # fallback to original exif
        else:
            updated_exif = None

        # Save the new image, preserving original bit depth and chroma plus meta data for orientation
        # The bit_depth parameter explicitly instructs the HEIF encoder to save the final file with the specified bit depth (e.g. 10 bit).
        #  For images with >8 bit, it knows the in-memory data is 16-bit and it knows the desired output is e.g. 10-bit.
        #  It scales the pixel values back down from the [0, 65535] range to the [0, 1023] range before encoding and saving the file.
        new_heif_image.save(image_utils.long_path(output_path), format="HEIF", quality=quality, bit_depth=bit_depth, chroma=chroma, nclx_profile=nclx_profile, exif=updated_exif, xmp=xmp)
        #print(f"Cropped image to {w}x{h} at ({x},{y}) and saved to {output_path}")
