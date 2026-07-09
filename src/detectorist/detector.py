import ast
import gzip

import cv2
import numpy as np
import onnxruntime as ort

from .image_object import ImageObject
from .structures import Detection


def _load_model_bytes(model_path: str) -> bytes:
    """Read an ONNX model file, transparently decompressing gzip if needed."""
    if model_path.endswith(".gz"):
        with gzip.open(model_path, 'rb') as f:
            return f.read()
    with open(model_path, 'rb') as f:
        return f.read()


class Detector:
    """
    Object detector using RF-DETR ONNX models.

    RF-DETR models have two or three output tensors:
    - outputs[0]: boxes with shape (1, num_detections, 4) in normalized [cx, cy, w, h] format
    - outputs[1]: class logits with shape (1, num_detections, num_classes)
    - outputs[2]: mask logits with shape (1, num_detections, 126, 126) — segmentation models only

    Boxes are in normalized coordinates [0, 1]. Class outputs are logits requiring sigmoid.
    Uses 1-indexed class IDs (0 is background).
    Does not require NMS (DETR architecture handles duplicate suppression via attention).
    """

    def __init__(self, model_path: str):
        """
        Initializes the Detector by loading the ONNX model.

        Args:
            model_path (str): Path to the ONNX model file.

        Raises:
            OSError: If the model file cannot be loaded.
        """
        try:
            self.session = ort.InferenceSession(_load_model_bytes(model_path))
            onnx_names_str = self.session.get_modelmeta().custom_metadata_map.get('names', '{}')
            self.class_names = ast.literal_eval(onnx_names_str.strip())

        except Exception as e:
            raise OSError(f"Error loading ONNX model from '{model_path}': {e}") from e

        # Get model input details
        self.input_name = self.session.get_inputs()[0].name
        input_shape = self.session.get_inputs()[0].shape
        self.input_height, self.input_width = input_shape[2], input_shape[3]
        self.is_segmentation = len(self.session.get_outputs()) >= 3

    def detect(self, image: ImageObject) -> list[Detection]:
        """
        Detects objects in an image using the RF-DETR ONNX model.

        Returns all detections without confidence filtering, sorted by score descending.
        Confidence filtering is a display-layer concern handled by the caller.

        Args:
            image: The input image (ImageObject instance).

        Returns:
            A list of Detection tuples sorted by score descending. Each box is
            in [x, y, w, h] format (top-left corner + dimensions). mask is a
            uint8 array at model input resolution (0 or 255) for segmentation
            models, or None for detection-only models.
        """
        original_height, original_width = image.height, image.width

        # Preprocess the image data (RF-DETR uses RGB + ImageNet normalization)
        input_image = image.preprocess_for_onnx_detr(self.input_width, self.input_height)

        # Run the model
        outputs = self.session.run(None, {self.input_name: input_image})

        # Process the output from RF-DETR transformer model
        # outputs[0]: boxes with shape (1, num_detections, 4) in normalized [cx, cy, w, h] format
        # outputs[1]: class logits with shape (1, num_detections, num_classes) - need sigmoid
        boxes = outputs[0][0]  # Shape: [num_detections, 4]
        class_logits = outputs[1][0]  # Shape: [num_detections, num_classes]

        if boxes.size == 0:
            return []

        # For segmentation models, compute mask probabilities up front.
        # The mask output shape is [1, num_detections, H, H] where H is 1/4 of the model's
        # input resolution — the mask head taps directly into the stride-4 backbone feature map.
        # The tensor name is an auto-generated node ID, so we access it positionally as outputs[2].
        # Model      | Input     | Detections | Mask resolution
        # -----------|-----------|------------|----------------
        # Nano       | 312×312   | 100        | 78×78
        # Large      | 504×504   | 200        | 126×126
        # 2XLarge    | 768×768   | 300        | 192×192
        mask_logits_all = None
        if self.is_segmentation:
            mask_logits_all = outputs[2][0]  # Shape: [num_detections, H, H] — raw logits, sigmoid applied after resize

        # Apply sigmoid to convert logits to probabilities
        class_scores = 1 / (1 + np.exp(-class_logits))

        # Get the best class and score for each detection
        scores = np.max(class_scores, axis=1)
        class_ids = np.argmax(class_scores, axis=1)

        # Convert boxes from normalized [cx, cy, w, h] to pixel [x, y, w, h] format
        # where (x, y) is the top-left corner
        cx, cy, w, h = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
        x = (cx - w / 2) * original_width
        y = (cy - h / 2) * original_height
        w_scaled = w * original_width
        h_scaled = h * original_height
        boxes_xywh = np.column_stack((x, y, w_scaled, h_scaled)).astype(int).tolist()

        # Build final results.
        # The 'names' metadata is keyed by the class ID argmax produces: RF-DETR detection
        # models are 1-indexed (index 0 is background); segmentation models are 0-indexed
        # (no background class).
        final_results = []
        for i in range(len(boxes_xywh)):
            class_id = class_ids[i]
            class_name = self.class_names.get(class_id, f"Class {class_id}")
            mask = None
            if mask_logits_all is not None:
                # Resize logits to model input resolution, then sigmoid, then threshold.
                # Resizing in logit space (before sigmoid) keeps the boundary transition
                # gradual so bilinear interpolation places the logit=0 isoline smoothly.
                # Staying at model input resolution (not original image size) for efficiency.
                # The display layer scales the overlay.
                logits_resized = cv2.resize(mask_logits_all[i], (self.input_width, self.input_height), interpolation=cv2.INTER_LINEAR)
                with np.errstate(over="ignore"):  # very negative logits cause exp overflow, but 1/(1+inf) = 0.0
                    mask_probs = 1 / (1 + np.exp(-logits_resized))
                mask = (mask_probs >= 0.5).astype(np.uint8) * 255
            final_results.append(Detection(boxes_xywh[i], scores[i], class_name, mask))

        # Sort by score descending for consistent ordering (highest-confidence first)
        final_results.sort(key=lambda d: d.score, reverse=True)

        return final_results
