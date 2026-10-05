import logging
import struct

import numpy as np
import piexif
import pillow_heif
from PIL import Image as PILImage

from . import utils
from .image_object import ImageMode, ImageObject

logger = logging.getLogger(__name__)

HEIF_EXTENSIONS = ('.heic', '.heics', '.heif', '.heifs', '.hif')

# How much of the file to read when looking for the "meta" box. Camera and
# encoder output always places "meta" before "mdat" so the metadata can be
# read without downloading the (potentially huge) pixel payload; a few MB is
# generous headroom even for files with several embedded thumbnails.
_HEIF_METADATA_SCAN_BYTES = 4 * 1024 * 1024

# Maps an "irot" box value (number of 90 degree steps rotated anti-clockwise,
# per ISO/IEC 23008-12) to the classic EXIF orientation value that describes
# the same result, so display code can treat both sources the same way.
_IROT_TO_EXIF_ORIENTATION = {0: 1, 1: 8, 2: 3, 3: 6}


def _iter_isobmff_boxes(data: bytes, start: int, end: int):
    """
    Walks a sequence of ISO Base Media File Format boxes (ISO/IEC 14496-12),
    the generic container structure every HEIF-family file is built from,
    regardless of which vendor's encoder produced it.

    Yields (box_type, payload_start, box_end) tuples for each box found in
    data[start:end].
    """
    pos = start
    while pos + 8 <= end:
        size = struct.unpack_from(">I", data, pos)[0]
        box_type = data[pos + 4:pos + 8]
        header_len = 8
        if size == 1:
            if pos + 16 > end:
                break
            size = struct.unpack_from(">Q", data, pos + 8)[0]
            header_len = 16
        elif size == 0:
            size = end - pos
        if size < header_len:
            break
        yield box_type, pos + header_len, pos + size
        pos += size


def _find_isobmff_box(data: bytes, start: int, end: int, box_type: bytes):
    """Returns (payload_start, box_end) for the first child box of box_type, or None."""
    for found_type, payload_start, box_end in _iter_isobmff_boxes(data, start, end):
        if found_type == box_type:
            return payload_start, box_end
    return None


def _get_heif_container_orientation(file_path: str) -> int | None:
    """
    Reads the primary image's rotation from the HEIF container's own "irot"
    property box and returns it as a classic EXIF orientation value (1-8).

    Some HEIF encoders, including Sony's in-camera HEIF ("HIF") encoder,
    record rotation only in this container-level box and never write the
    classic EXIF Orientation tag (0x0112). This is display-only: it is not
    used for cropping, since libheif already applies "irot" automatically
    while decoding pixel data, and nothing re-adds a rotation box or tag
    when a cropped HEIF file is saved, so treating this value as something
    to "reverse" before saving would rotate the output the wrong way.

    Returns None if the box structure can't be parsed, no "irot" property
    is associated with the primary item, or the item also carries a mirror
    ("imir") property, since combining mirror and rotation isn't handled
    here.
    """
    try:
        with open(utils.long_path(file_path), "rb") as f:
            data = f.read(_HEIF_METADATA_SCAN_BYTES)
    except OSError:
        return None

    meta = _find_isobmff_box(data, 0, len(data), b'meta')
    if meta is None:
        return None
    meta_payload_start, meta_end = meta
    inner_start = meta_payload_start + 4  # skip the "meta" FullBox version/flags

    pitm = _find_isobmff_box(data, inner_start, meta_end, b'pitm')
    iprp = _find_isobmff_box(data, inner_start, meta_end, b'iprp')
    if pitm is None or iprp is None:
        return None
    pitm_payload, _ = pitm
    pitm_version = data[pitm_payload]
    if pitm_version == 0:
        primary_item_id = struct.unpack_from(">H", data, pitm_payload + 4)[0]
    else:
        primary_item_id = struct.unpack_from(">I", data, pitm_payload + 4)[0]

    iprp_payload, iprp_end = iprp
    ipco = _find_isobmff_box(data, iprp_payload, iprp_end, b'ipco')
    ipma = _find_isobmff_box(data, iprp_payload, iprp_end, b'ipma')
    if ipco is None or ipma is None:
        return None
    ipco_payload, ipco_end = ipco
    properties = list(_iter_isobmff_boxes(data, ipco_payload, ipco_end))

    ipma_payload, _ = ipma
    ipma_version = data[ipma_payload]
    ipma_flags = struct.unpack_from(">I", data, ipma_payload)[0] & 0xFFFFFF
    pos = ipma_payload + 4
    entry_count = struct.unpack_from(">I", data, pos)[0]
    pos += 4
    property_indices = None
    for _ in range(entry_count):
        if ipma_version < 1:
            item_id = struct.unpack_from(">H", data, pos)[0]
            pos += 2
        else:
            item_id = struct.unpack_from(">I", data, pos)[0]
            pos += 4
        assoc_count = data[pos]
        pos += 1
        indices = []
        for _ in range(assoc_count):
            if ipma_flags & 1:
                raw = struct.unpack_from(">H", data, pos)[0]
                pos += 2
                indices.append(raw & 0x7FFF)
            else:
                raw = data[pos]
                pos += 1
                indices.append(raw & 0x7F)
        if item_id == primary_item_id:
            property_indices = indices
            break

    if not property_indices:
        return None

    rotation = None
    mirrored = False
    for index in property_indices:
        if index < 1 or index > len(properties):
            continue
        prop_type, prop_payload_start, _ = properties[index - 1]
        if prop_type == b'irot':
            rotation = data[prop_payload_start] & 0x3
        elif prop_type == b'imir':
            mirrored = True

    if rotation is None or mirrored:
        return None
    return _IROT_TO_EXIF_ORIENTATION[rotation]


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

        logger.debug("Loading HEIF file: %s", image_path)
        heif_file = pillow_heif.open_heif(self.long_image_path, convert_hdr_to_8bit=False)

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
        logger.debug(
            "HEIF image mode: %s, size: %s, stride: %s, data length: %s, bits per channel: %s, chroma: %s",
            self._heif_mode, heif_file[0].size, heif_file[0].stride, len(heif_file[0].data),
            self._original_bpc, self._chroma,
        )

        # Map pillow_heif modes to our descriptive strings
        if self._heif_mode == 'L':
            self._mode = ImageMode.GRAY
        # RGBA before RGB, as "RGBA" and "RGBA;16" also start with "RGB"
        elif self._heif_mode.startswith('RGBA'):
            self._mode = ImageMode.RGBA
        elif self._heif_mode.startswith('RGB'):
            self._mode = ImageMode.RGB
        else:
            raise ValueError(f"Unsupported HEIF image mode: {self._heif_mode}")

        # Initialize the image data by copying the pixel data from the heif file. A HEIF container could
        # hold multiple images, but we only load the first. We make a copy to ensure we have our own data
        # as the underlying buffer may be freed when heif_file is closed.
        # Note: pillow-heif (via libheif) rotates the image data automatically based on the container's
        # own "irot" property box, not the classic EXIF Orientation tag. It helps when displaying the
        # image, but we need to be aware of this when cropping and saving later.
        self._image_data = np.asarray(heif_file[0]).copy()

        if self._image_data is None:
            raise OSError(f"Error: Could not read image from '{self.image_path}'")

        # Initialize EXIF data dictionary using the overwritten _load_exif_data() method
        self._exif_dict = self._load_exif_data()

        heif_file = None # Allow the Python GC to free resources


    def _load_exif_data(self) -> dict:
        """
        Loads EXIF dict from the raw EXIF that we extracted from the HEIF image file using
        pillow_heif. Returns an empty dict if there is no EXIF data or it cannot be parsed,
        like the base class does, so callers never have to handle None.
        """
        if not self._exif: # self._exif holds the raw EXIF bytes we've got from pillow_heif
            return {}
        try:
            return piexif.load(self._exif)
        except Exception as e:
            # Unreadable metadata is no reason to refuse an image that decoded fine
            logger.warning("Could not parse EXIF data of %s: %s", self._image_path, e)
            return {}

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

    def get_exif_summary(self) -> str:
        """
        Returns the EXIF summary, adding an Orientation line derived from
        this file's HEIF container "irot" box when the classic EXIF
        Orientation tag is absent, as with Sony's in-camera HEIF encoder.
        """
        summary = super().get_exif_summary()
        classic_orientation = (self.exif_data or {}).get('0th', {}).get(piexif.ImageIFD.Orientation)
        if classic_orientation:
            return summary  # base class already added an Orientation line

        container_orientation = _get_heif_container_orientation(self.long_image_path)
        if container_orientation is None:
            return summary

        line = f"Orientation\t: {self._get_human_readable_exif_orientation(container_orientation)}"
        return f"{summary}\n{line}" if summary else line

    def save_cropped(self, rect: tuple[int, int, int, int], output_path: str, quality=80):
        """
        Saves a cropped version of the HEIF image, preserving its original
        bit depth, metadata, and HEIF format.
        """
        logger.debug("Cropping HEIF image file: %s", self.image_path)

        # Use stored metadata
        bit_depth = self._original_bpc
        chroma = self._chroma
        nclx_profile = self._nclx_profile
        exif = self._exif
        xmp = self._xmp

        orientation = self._get_exif_orientation(exif)
        orientation_text = self._get_human_readable_exif_orientation(orientation)
        logger.debug("EXIF orientation: %s (%s)", orientation, orientation_text)

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
                logger.warning("Could not update EXIF data: %s", e)
                updated_exif = exif # fallback to original exif
        else:
            updated_exif = None

        # Save the new image, preserving original bit depth and chroma plus meta data for orientation
        # The bit_depth parameter explicitly instructs the HEIF encoder to save the final file with the specified bit depth (e.g. 10 bit).
        #  For images with >8 bit, it knows the in-memory data is 16-bit and it knows the desired output is e.g. 10-bit.
        #  It scales the pixel values back down from the [0, 65535] range to the [0, 1023] range before encoding and saving the file.
        new_heif_image.save(utils.long_path(output_path), format="HEIF", quality=quality, bit_depth=bit_depth, chroma=chroma, nclx_profile=nclx_profile, exif=updated_exif, xmp=xmp)
