
import cv2
import numpy as np
import piexif
from PIL import Image as PILImage

from . import image_utils
from .image_object import ImageObject
from .structures import ImageMode

STANDARD_IMG_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.bmp')


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
        self._exif = None

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

        self._exif = self._pil_image.info.get('exif')
        self._exif_dict = self._load_exif_data()

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
            ev_comp = -self.get_exposure_compensation()
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

        # Handle EXIF data
        if self._exif:
            try:
                exif_dict = piexif.load(self._exif)
                # Update image dimensions
                if 'Exif' in exif_dict:
                    exif_dict['Exif'][piexif.ExifIFD.PixelXDimension] = w
                    exif_dict['Exif'][piexif.ExifIFD.PixelYDimension] = h
                if '0th' in exif_dict:
                    exif_dict['0th'][piexif.ImageIFD.ImageWidth] = w
                    exif_dict['0th'][piexif.ImageIFD.ImageLength] = h

                if self._exposure_correction:
                    if 'Exif' not in exif_dict:
                        exif_dict['Exif'] = {}
                    exif_dict['Exif'][piexif.ExifIFD.ExposureBiasValue] = (0, 1)

                save_kwargs['exif'] = piexif.dump(exif_dict)
            except Exception as e:
                print(f"Warning: Could not update EXIF data: {e}")
                save_kwargs['exif'] = self._exif

        pil_cropped_image.save(output_path, **save_kwargs)
        print(f"  Cropped {original_format or 'image'} saved to {output_path}")
