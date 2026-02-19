import ast
import gzip

import numpy as np
import onnxruntime as ort

from .image_object import ImageObject


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

    RF-DETR models have two output tensors:
    - outputs[0]: boxes with shape (1, num_detections, 4) in normalized [cx, cy, w, h] format
    - outputs[1]: class logits with shape (1, num_detections, num_classes)

    Boxes are in normalized coordinates [0, 1]. Class outputs are logits requiring sigmoid.
    Uses 1-indexed class IDs (0 is background).
    Does not require NMS (DETR architecture handles duplicate suppression via attention).
    """

    @staticmethod
    def create(model_path: str) -> 'Detector':
        """
        Factory method to create a Detector from a model file.

        Args:
            model_path (str): Path to the ONNX model file.

        Returns:
            Detector: A Detector instance.

        Raises:
            OSError: If the model file cannot be loaded.
        """
        try:
            session = ort.InferenceSession(_load_model_bytes(model_path))
        except Exception as e:
            raise OSError(f"Error loading ONNX model from '{model_path}': {e}") from e

        return Detector(model_path, session)

    def __init__(self, model_path: str, session: ort.InferenceSession = None):
        """
        Initializes the Detector by loading the ONNX model.

        Args:
            model_path (str): Path to the ONNX model file.
            session (ort.InferenceSession, optional): Pre-loaded session (used by factory).

        Raises:
            OSError: If the model file cannot be loaded.
        """
        try:
            self.session = session if session else ort.InferenceSession(_load_model_bytes(model_path))
            onnx_names_str = self.session.get_modelmeta().custom_metadata_map.get('names', '{}')
            self.class_names = ast.literal_eval(onnx_names_str.strip())

        except Exception as e:
            raise OSError(f"Error loading ONNX model from '{model_path}': {e}") from e

        # Get model input details
        self.input_name = self.session.get_inputs()[0].name
        input_shape = self.session.get_inputs()[0].shape
        self.input_height, self.input_width = input_shape[2], input_shape[3]

    def detect(self, image: ImageObject) -> list:
        """
        Detects objects in an image using the RF-DETR ONNX model.

        Returns all detections without confidence filtering, sorted by score descending.
        Confidence filtering is a display-layer concern handled by the caller.

        Args:
            image: The input image (ImageObject instance).

        Returns:
            A list of tuples (box, score, class_name) for the detected objects,
            sorted by score descending. Each box is in [x, y, w, h] format
            (top-left corner + dimensions).
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
        # RF-DETR uses 1-indexed class IDs (0 is background). The 'names' metadata is
        # keyed by the class ID the model outputs (1-indexed), so look up directly.
        final_results = []
        for i in range(len(boxes_xywh)):
            class_id = class_ids[i]
            class_name = self.class_names.get(class_id, f"Class {class_id}")
            final_results.append((boxes_xywh[i], scores[i], class_name))

        # Sort by score descending for consistent ordering (highest-confidence first)
        final_results.sort(key=lambda d: d[1], reverse=True)

        return final_results
