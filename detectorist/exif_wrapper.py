import exifread
from PIL import Image as PILImage
from PIL.ExifTags import TAGS, GPSTAGS, IFD
from fractions import Fraction
from typing import Any, Union
import os

from .structures import CaseInsensitiveDict


class ExifWrapper:
    """
    A class that represents EXIF data of an image.
    """
    def __init__(self, image_source: Union[str, PILImage.Image]):
        self._exif_data = CaseInsensitiveDict()
        if isinstance(image_source, str):
            file_extension = os.path.splitext(image_source)[1].lower()
            if file_extension == '.arw':
                self._exif_data = self._load_exif_data_raw(image_source)
            else:
                # For non-ARW files, open with PIL and then load EXIF
                try:
                    pil_image = PILImage.open(image_source)
                    self._exif_data = self._load_exif_data_pil(pil_image)
                except Exception as e:
                    print(f"Could not open image {image_source} with PIL: {e}")
                    self._exif_data = CaseInsensitiveDict() # Ensure it's initialized even on error
        elif isinstance(image_source, PILImage.Image):
            self._exif_data = self._load_exif_data_pil(image_source)
        else:
            raise TypeError("Exif class must be initialized with an image path (str) or a PIL Image object.")

        # for k, v in self._exif_data.items():
        #     print(f"  {k}: {v}")


    @property
    def data(self) -> CaseInsensitiveDict:
        """Returns the entire decoded EXIF data dictionary."""
        return self._exif_data


    @staticmethod
    def _parse_fraction(value, round_to=2):
        """
        Convert fractional string to float, handling various edge cases.
        
        Args:
            value (str or numeric): Value to convert
            round_to (int, optional): Number of decimal places to round to. Defaults to 2.
        
        Returns:
            float or original value if conversion fails
        """
        if isinstance(value, (int, float)):
            return round(value, round_to)
        
        if not isinstance(value, str) or '/' not in value:
            return value
        
        try:
            num, denom = map(float, value.split('/'))
            return round(num / denom, round_to) if denom != 0 else value
        except (ValueError, TypeError):
            return value

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

    def _load_exif_data_pil(self, img: PILImage) -> CaseInsensitiveDict:
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
                        try:
                            val = float(val)
                        except (ValueError, TypeError):
                            pass # Keep original val if cannot convert to float
                        val = self._parse_fraction(val)
                    elif full_tag_name == 'Exif ExposureTime':
                        val = self._format_exposure_time(val)
                    elif full_tag_name == 'Exif FocalLength':
                        try:
                            val = round(float(val), 2)
                        except (ValueError, TypeError):
                            pass
                    
                    exif_data[full_tag_name] = val

            except KeyError:
                continue
        return exif_data

    def _load_exif_data_raw(self, image_path: str) -> CaseInsensitiveDict:
        """
        Loads EXIF data from the image file using the exifread library into self._exif_data.
        """
        exif_data = CaseInsensitiveDict()
        try:
            with open(image_path, 'rb') as f:
                tags = exifread.process_file(f, details=False)
                if tags:
                    for tag, value in tags.items():
                        # Skip thumbnail data
                        if tag in ('JPEGThumbnail', 'TIFFThumbnail'):
                            continue
                        
                        val = value.printable
                        if tag == 'EXIF FNumber':
                            val = self._parse_fraction(val)
                        elif tag == 'EXIF ExposureTime':
                            val = self._format_exposure_time(val)
                        elif tag == 'EXIF FocalLength':
                            try:
                                val = round(float(val), 2)
                            except (ValueError, TypeError):
                                pass
                        
                        exif_data[tag] = val
        except Exception as e:
            print(f"Could not load EXIF data for {image_path}: {e}")
        return exif_data
