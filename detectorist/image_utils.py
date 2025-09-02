import os
import cv2
import rawpy
import numpy as np
from PIL import Image as PILImage
import pillow_heif

# Ensure the HEIF Pillow plugin is registered
pillow_heif.register_heif_opener()

# Files with these extensions will be treated as HEIF files (using pillow_heif)
HEIF_EXTENSIONS = ('.heic', '.heics', '.heif', '.heifs', '.hif')

# Files with these extensions will be treated as RAW files (using rawpy)
RAW_EXTENSIONS = ('.arw', '.nef', '.cwr', 'cr2', 'cr3', 'orf', 'pef' )

# All supported image file extensions
IMG_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.bmp') + HEIF_EXTENSIONS + RAW_EXTENSIONS

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

def get_exif_orientation(exif):
    """
    Extracts the orientation value from EXIF data.

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

def get_human_readable_exif_orientation(orientation):
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

def crop_heif_image(input_path, output_path, rect, quality=80):
    """
    Crops a HIF image and saves it as a new HIF image. 
    The new image will re-use the exif, xmp, and nclx_profile of the original image to keep as much meta data as possible.

    Args:
        input_path (str): Path to the input HIF file.
        output_path (str): Path to save the cropped HIF file.
        rect (tuple): A tuple of (x, y, width, height) for the crop.
        quality (int): Quality for the output image (1-100), -1 for lossless, default is 80.
    """
    heif = pillow_heif.open_heif(input_path, convert_hdr_to_8bit=False)
    bit_depth = heif.info.get('bit_depth', 8)
    chroma = heif.info.get('chroma', '420')
    nclx_profile = heif.info.get('nclx_profile')
    exif = heif.info.get('exif')
    xmp = heif.info.get('xmp')

    print(f"{input_path} Image\n\tmode: {heif[0].mode}, size: {heif[0].size}, stride: {heif[0].stride}, data length: {len(heif[0].data)}")
    orientation = get_exif_orientation(exif)
    orientation_text = get_human_readable_exif_orientation(orientation)
    print(f"  EXIF orientation: {orientation} ({orientation_text})")

    # pillow-heif appears to rotate the image data based on EXIF orientation automatically.
    # See: https://pillow-heif.readthedocs.io/en/latest/workaround-orientation.html#q-so-is-there-a-decision
    # Get a numpy array view of the (rotated) image data using the __array_interface__
    rotated_np_array = np.asarray(heif[0])

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

    # Create a new HeifImage from the cropped numpy array using pillow_heif.from_bytes()
    mode = heif[0].mode
    size = (unrotated_np.shape[1], unrotated_np.shape[0])
    data = unrotated_np.tobytes()

    #print(f"Creating new HEIF image with\n\tmode: {mode}, size: {size}, data length: {len(data)}")    
    new_heif_image = pillow_heif.from_bytes(mode=mode, size=size, data=data)
    
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
    new_heif_image.save(output_path, format="HEIF", quality=quality, bit_depth=bit_depth, chroma=chroma, nclx_profile=nclx_profile, exif=updated_exif, xmp=xmp)
    #print(f"Cropped image to {w}x{h} at ({x},{y}) and saved to {output_path}")

def crop_raw_image(input_path, output_path, rect, output_bps=16):
    """
    Crops a RAW image and saves it as a lossless 16 bit PNG or TIFF image. 

    Args:
        input_path (str): Path to the input RAW file.
        output_path (str): Path to save the cropped file (file extension will be replaced).
        rect (tuple): A tuple of (x, y, width, height) for the crop.
        output_bps (int): 16 or 8 bit output, default is 16.
    """
    file_extension = os.path.splitext(output_path)[1]
    if file_extension.lower() not in ('.png', '.tiff'):
        raise ValueError(f"Output file extension must be .png or .tiff for saving 16-bit images, but got: {file_extension}")

    np_array = load_arw_image(input_path, output_bps=16)

    # Crop the array using numpy slicing
    x, y, w, h = rect
    cropped_np_array = np_array[y:y+h, x:x+w]

    # TODO: load and save the exif data to the cropped image
    # exif = ExifWrapper(input_path)
    # exif.data

    # Save the cropped image as a 16-bit PNG or TIFF file
    save_16bit_image(cropped_np_array, output_path)

def crop_PIL_image(input_path, output_path, rect):
    """
    Crops an image using PIL and saves the cropped image.

    Args:
        input_path (str): Path to the input image file.
        output_path (str): Path to save the cropped image file.
        rect (tuple): A tuple of (x, y, width, height) for the crop.
    """
    pil_image = PILImage.open(input_path)
    x, y, w, h = rect
    cropped_image = pil_image.crop((x, y, x + w, y + h))
    cropped_image.save(output_path)

def crop_image_file(input_path: str, output_dir: str, rect: tuple[int, int, int, int]):
    """
    Crops an image file and saves it to the specified output directory.
    The cropped image will retain the original file name, but for RAW files, the extension will be replaced with .png.
    
    Args:
        input_path (str): Path to the input image file.
        output_dir (str): Directory to save the cropped image file.
        rect (tuple): A tuple of (x, y, width, height) for the crop.
    """
    file_extension = os.path.splitext(input_path)[1].lower()
    # check if the input_path has a file_extension
    if not file_extension:
        raise ValueError(f"Input file has no extension: {input_path}")

    output_path = os.path.join(output_dir, os.path.basename(input_path))

    if file_extension in HEIF_EXTENSIONS:
        print(f"Cropping HEIF image file: {input_path}")
        crop_heif_image(input_path, output_path, rect)
    elif file_extension in RAW_EXTENSIONS:
        print(f"Cropping RAW image file: {input_path}")
        # replace output file extension with .png
        output_path = os.path.splitext(output_path)[0] + '.png'
        crop_raw_image(input_path, output_path, rect)
    else:
        print(f"Cropping image file: {input_path}")
        # for all other (8bit) formats use PIL
        crop_PIL_image(input_path, output_path, rect)