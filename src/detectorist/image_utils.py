import logging
import os

import cv2
import numpy as np

from .utils import long_path

logger = logging.getLogger(__name__)


def imread(path: str, flags: int = cv2.IMREAD_UNCHANGED) -> np.ndarray:
    """
    Read an image with OpenCV in a way that works for long paths and non-ASCII
    paths on Windows.

    ``cv2.imread`` builds the file via the Win32 APIs directly, so it neither
    honors the ``\\\\?\\`` long-path prefix nor handles Unicode paths reliably.
    Reading the bytes through Python's own ``open`` (via :func:`long_path`) and
    decoding them with ``cv2.imdecode`` avoids both problems.
    """
    with open(long_path(path), "rb") as f:
        buffer = np.frombuffer(f.read(), dtype=np.uint8)
    return cv2.imdecode(buffer, flags)


def imwrite(path: str, image: np.ndarray, params: list[int] | None = None) -> None:
    """
    Write an image with OpenCV in a way that works for long paths and non-ASCII
    paths on Windows.

    ``cv2.imwrite`` builds the file via the Win32 APIs directly, so it neither
    honors the ``\\\\?\\`` long-path prefix nor handles Unicode paths reliably.
    Encoding into an in-memory buffer with ``cv2.imencode`` and writing the bytes
    through Python's own ``open`` (via :func:`long_path`) avoids both problems.
    """
    ext = os.path.splitext(path)[1]
    success, buffer = cv2.imencode(ext, image, params or [])
    if not success:
        raise OSError(f"OpenCV failed to encode image for: {path}")
    with open(long_path(path), "wb") as f:
        f.write(buffer)


def adjust_exposure(image_data: np.ndarray, exposure_compensation: float, gamma: float = 2.2, bits_per_channel: int = None) -> np.ndarray:
    """
    Adjusts the exposure of the image data by the given exposure compensation value. It creates a copy and doesn't modify the given image_data.
    This function is designed to work with:
      * Multi-channel (like RGB, BGR, RGBA, RGBA) or single-channel (grayscale) image data.
        * Also handles alpha channels correctly by not applying exposure adjustments to them.
      * Data with a bit depth of 8 or 16 bits per channel.

    Args:
        image_data (np.ndarray): The input image data as a NumPy array.
        exposure_compensation (float): The exposure compensation value in EV stops (e.g. -0.3).
        gamma (float, optional): The gamma correction value of the image data. Most image files use a gamma of 2.2.
                                 For linear data, gamma should be set to 1.0. Defaults to 2.2.
        bits_per_channel (int, optional): The number of bits per channel for the image data (e.g. 8, 10, 12, 16).
                                           If not provided, it's inferred from the image data dtype,
                                           assuming 16 bits for uint16 data. Defaults to None.

    Returns:
        np.ndarray: The exposure-adjusted image data.
    """
    if exposure_compensation == 0.0:
        return image_data
    image_data_copy = image_data.copy()
    adjust_exposure_inplace(image_data_copy, exposure_compensation, gamma, bits_per_channel)
    return image_data_copy

def adjust_exposure_inplace(image_data: np.ndarray, exposure_compensation: float, gamma: float = 2.2, bits_per_channel: int = None) -> None:
    """
    Adjusts the exposure of the image data by the given exposure compensation value. It modifies the given image_data instead of creating a copy.
    This function is designed to work with:
      * Multi-channel (like RGB, BGR, RGBA, RGBA) or single-channel (grayscale) image data.
        * Also handles alpha channels correctly by not applying exposure adjustments to them.
      * Data with a bit depth of 8 or 16 bits per channel.


    Args:
        image_data (np.ndarray): The input image data as a NumPy array.
        exposure_compensation (float): The exposure compensation value in EV stops (e.g. -0.3).
        gamma (float, optional): The gamma correction value of the image data. Most image files use a gamma of 2.2.
                                 For linear data, gamma should be set to 1.0. Defaults to 2.2.
        bits_per_channel (int, optional): The number of bits per channel for the image data (e.g. 8, 10, 12, 16).
                                           If not provided, it's inferred from the image data dtype,
                                           assuming 16 bits for uint16 data. Defaults to None.
    """
    if exposure_compensation == 0.0:
        return

    # The exposure compensation is in stops, so we use 2^ev
    factor = np.float32(2.0**exposure_compensation)

    # If the resulting compensation factor is 1.0, do nothing.
    if factor == 1.0:
        return

    bpc = bits_per_channel
    # If bits_per_channel is not provided, infer it from the image data dtype
    if bpc is None:
        if image_data.dtype == np.uint8:
            bpc = 8
        elif image_data.dtype == np.uint16:
            bpc = 16  # Assume 16 if not specified for uint16 data (but it could be 10 or 12 - we just don't know)
        else:
            logger.warning("Cannot determine bits per channel for dtype %s. Returning original image data.", image_data.dtype)
            return

    if bpc not in [8, 10, 12, 16]:
        logger.warning("Unsupported bits per channel (%s) for exposure adjustment. Returning original image data.", bpc)
        return

    # Note on Gamma (see: https://en.wikipedia.org/wiki/Gamma_correction:
    #   Gamma encoding is used to optimize the usage of bits when encoding an image, by taking
    #   advantage of the non-linear manner in which humans perceive light and color. Our human
    #   vision has greater sensitivity to relative differences between darker tones than between
    #   lighter tones.
    #   The pixel values stored in standard image file formats do usually represent the light
    #   intensity via gamma-compressed values instead of a linear encoding. They are gamma-
    #   compensated
    #       - either using one of the standard gamma values such as 2.2 (encoding gamma value
    #         of 1/2.2) as with sRGB
    #       - or according to some gamma specified by metadata such as an ICC profile.
    #   This code assumes an encoding of 1/<gamma> (e.g. of 1/2.2) and therefore applies gamma
    #   correction using a decoding vaule of <gamma> (e.g. 2.2) back to the image data:
    #       - encoding: V_out = (V_in)^(1/γ)
    #       - decoding: V_out = (V_in)^γ

    # Separate color and alpha channels if alpha exists
    has_alpha = False
    if image_data.ndim == 3 and image_data.shape[2] in [2, 4]:
        has_alpha = True
        # Assume alpha is the last channel and separate it
        color_data = image_data[:, :, :-1]
    else:
        color_data = image_data

    # Determine the maximum value for the current NumPy array dtype. For >8 bit images,
    # pillow-heif scales the data to the full range of the dtype (e.g. uint16).
    max_val_dtype = (2**(image_data.dtype.itemsize * 8)) - 1

    # The adjustment depends only on a channel's value, so precompute it once
    # for every possible value and apply it as a lookup table. Evaluating the
    # gamma math per pixel instead takes hundreds of milliseconds on large
    # images (two np.power calls over every element).
    values = np.arange(max_val_dtype + 1, dtype=np.float32) / max_val_dtype
    # Linearize (remove gamma compression), scale in "linear light" (gamma 1),
    # then re-apply the gamma compression and denormalize
    adjusted = np.power(np.power(values, gamma) * factor, 1.0 / gamma) * max_val_dtype
    np.clip(adjusted, 0, max_val_dtype, out=adjusted)
    lut = adjusted.astype(image_data.dtype)

    # Update the original array in-place
    if has_alpha:
        # Fancy indexing instead of cv2.LUT because the color channels are a
        # non-contiguous view here
        image_data[:, :, :-1] = lut[color_data]
    elif image_data.dtype == np.uint8 and image_data.flags.c_contiguous:
        # cv2.LUT is a SIMD gather, considerably faster than numpy indexing
        cv2.LUT(image_data, lut, dst=image_data)
    else:
        image_data[:] = lut[image_data]

def convert_16bit_to_8bit(image_16bit: np.ndarray) -> np.ndarray:
    """
    Converts a 16-bit image (uint16) to an 8-bit image (uint8) by scaling.

    Args:
        image_16bit (np.ndarray): The input 16-bit image data (dtype must be uint16).
    Returns:
        np.ndarray: The converted 8-bit image data (dtype is uint8).
    Raises:
        ValueError: If the input image is None.
        TypeError: If the input image is not of dtype uint16.
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
