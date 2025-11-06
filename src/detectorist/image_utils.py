import os

import cv2
import numpy as np

# Files with these extensions will be treated as HEIF files (using pillow_heif)
HEIF_EXTENSIONS = ('.heic', '.heics', '.heif', '.heifs', '.hif')

# Files with these extensions will be treated as RAW files (using rawpy)
RAW_EXTENSIONS = ('.arw', '.nef', '.cwr', '.cr2', '.cr3', '.orf', '.pef' )

# All supported image file extensions
IMG_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.bmp') + HEIF_EXTENSIONS + RAW_EXTENSIONS


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
    # The exposure compensation is in stops, so we use 2^ev
    factor = np.float32(2.0**exposure_compensation)

    # If exposure compensation is zero, do nothing.
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
            print(f"Warning: Cannot determine bits per channel for dtype {image_data.dtype}.\nReturning original image data.")
            return

    if bpc not in [8, 10, 12, 16]:
        print(
            f"Warning: Unsupported bits per channel ({bpc}) for exposure adjustment.\nReturning original image data."
        )
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

    # Use floating point arithmetic to prevent overflow and precision loss (on color data only)
    image_float = color_data.astype(np.float32)

    # Normalize to [0, 1]
    image_norm = image_float / max_val_dtype

    # Linearize the image data (remove gamma compression)
    image_linear = np.power(image_norm, gamma)

    # Apply exposure compensation in linear space as operations on pixel values should be performed in "linear light" (gamma 1).
    adjusted_linear = image_linear * factor

    # Apply gamma correction back to the image
    adjusted_gamma = np.power(adjusted_linear, 1.0 / gamma)

    # Denormalize from [0, 1] back to the original range
    adjusted_image_float = adjusted_gamma * max_val_dtype

    # Clip the values to the valid range of the current NumPy array dtype
    np.clip(adjusted_image_float, 0, max_val_dtype, out=adjusted_image_float)

    # Convert back to the original dtype (e.g., uint8, uint16)
    adjusted_color_data = adjusted_image_float.astype(image_data.dtype)

    # Update the original array in-place
    if has_alpha:
        image_data[:, :, :-1] = adjusted_color_data
    else:
        image_data[:] = adjusted_color_data

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

def save_16bit_image(image_16bit: np.ndarray, output_path: str):
    """
    Save a 16-bit image to the specified path (PNG or TIFF).
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
