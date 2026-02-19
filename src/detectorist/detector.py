import ast
import gzip
from abc import ABC, abstractmethod

import cv2
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


class Detector(ABC):
    """
    Abstract base class for object detection using ONNX models.
    Subclasses implement specific model architectures (YOLO, DETR, etc.).
    """

    @staticmethod
    def create(model_path: str) -> 'Detector':
        """
        Factory method to create the appropriate Detector subclass based on the model.

        Detects model type by examining the number of outputs:
        - 1 output: YOLO CNN-based model
        - 2 outputs: RF-DETR transformer-based model

        Args:
            model_path (str): Path to the ONNX model file.

        Returns:
            Detector: Appropriate subclass instance (YoloDetector or DetrDetector).

        Raises:
            OSError: If the model file cannot be loaded.
        """
        try:
            session = ort.InferenceSession(_load_model_bytes(model_path))
        except Exception as e:
            raise OSError(f"Error loading ONNX model from '{model_path}': {e}") from e

        num_outputs = len(session.get_outputs())

        if num_outputs == 2:
            return DetrDetector(model_path, session)
        else:
            return YoloDetector(model_path, session)

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

    @abstractmethod
    def detect(self, image: ImageObject, confidence_threshold: float = 0.5, nms_threshold: float = 0.45) -> list:
        """
        Detects objects in an image using the ONNX model.

        Args:
            image: The input image (ImageObject instance).
            confidence_threshold: The confidence threshold for filtering detections.
            nms_threshold: The Non-Maximum Suppression threshold (only used for YOLO).

        Returns:
            A list of tuples (box, score, class_name) for the detected objects.
            Each box is in [x, y, w, h] format (top-left corner + dimensions).
        """
        pass


class YoloDetector(Detector):
    """
    Detector for YOLO CNN-based models.

    YOLO models have a single output tensor with shape (1, 4 + num_classes, num_proposals).
    Boxes are in pixel coordinates (relative to input size) in [cx, cy, w, h] format.
    Requires Non-Maximum Suppression (NMS) to filter overlapping detections.
    """

    def detect(self, image: ImageObject, confidence_threshold: float = 0.5, nms_threshold: float = 0.45) -> list:
        """
        Detects objects using YOLO CNN-based model.

        Args:
            image: The input image (ImageObject instance).
            confidence_threshold: The confidence threshold for filtering detections.
            nms_threshold: The Non-Maximum Suppression threshold.

        Returns:
            A list of tuples (box, score, class_name) for the detected objects.
            Each box is in [x, y, w, h] format (top-left corner + dimensions).
        """
        original_height, original_width = image.height, image.width

        # Preprocess the image data (YOLO uses BGR, no ImageNet normalization)
        input_image = image.preprocess_for_onnx_yolo(self.input_width, self.input_height)

        # Run the model
        outputs = self.session.run(None, {self.input_name: input_image})

        # Process the output from YOLO
        # The output shape is (1, 4 + num_classes, num_proposals)
        # After transposing, we get (num_proposals, 4 + num_classes)
        output = outputs[0][0].transpose()

        if not output.any():
            return []

        # Scale factors
        x_scale = original_width / self.input_width
        y_scale = original_height / self.input_height

        # In YOLO, each proposal is [center_x, center_y, w, h, class1_score, class2_score, ...].
        # The confidence of a detection is the highest class score.
        boxes_yolo = output[:, :4]
        class_scores = output[:, 4:]
        scores = np.max(class_scores, axis=1)
        class_ids = np.argmax(class_scores, axis=1)

        # Convert boxes from YOLO format (center_x, center_y, w, h) to OpenCV's NMS format (x, y, w, h),
        # where (x,y) is the top-left corner, and scale to the original image size.
        x1 = (boxes_yolo[:, 0] - boxes_yolo[:, 2] / 2) * x_scale
        y1 = (boxes_yolo[:, 1] - boxes_yolo[:, 3] / 2) * y_scale
        w_scaled = boxes_yolo[:, 2] * x_scale
        h_scaled = boxes_yolo[:, 3] * y_scale
        boxes_for_nms = np.column_stack((x1, y1, w_scaled, h_scaled)).astype(int).tolist()

        # Apply Non-Maximum Suppression
        # NMSBoxes returns indices of the boxes to keep
        indices = cv2.dnn.NMSBoxes(boxes_for_nms, scores.tolist(), score_threshold=confidence_threshold, nms_threshold=nms_threshold)

        final_results = []
        if len(indices) > 0:
            # Flatten in case of nested list
            indices = indices.flatten()
            for i in indices:
                class_id = class_ids[i]
                class_name = self.class_names.get(class_id, f"Class {class_id}")
                final_results.append((boxes_for_nms[i], scores[i], class_name))

        return final_results


class DetrDetector(Detector):
    """
    Detector for RF-DETR transformer-based models.

    RF-DETR models have two output tensors:
    - outputs[0]: boxes with shape (1, num_detections, 4) in normalized [cx, cy, w, h] format
    - outputs[1]: class logits with shape (1, num_detections, num_classes)

    Boxes are in normalized coordinates [0, 1]. Class outputs are logits requiring sigmoid.
    Uses 1-indexed class IDs (0 is background).
    Does not require NMS (DETR architecture handles duplicate suppression via attention).
    """

    def detect(self, image: ImageObject, confidence_threshold: float = 0.5, nms_threshold: float = 0.45) -> list:
        """
        Detects objects using RF-DETR transformer-based model.

        Args:
            image: The input image (ImageObject instance).
            confidence_threshold: The confidence threshold for filtering detections.
            nms_threshold: Unused (RF-DETR doesn't require NMS). Kept for API compatibility.

        Returns:
            A list of tuples (box, score, class_name) for the detected objects.
            Each box is in [x, y, w, h] format (top-left corner + dimensions).
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

        # Filter by confidence threshold
        mask = scores >= confidence_threshold
        boxes = boxes[mask]
        scores = scores[mask]
        class_ids = class_ids[mask]

        if len(boxes) == 0:
            return []

        # Convert boxes from normalized [cx, cy, w, h] to pixel [x, y, w, h] format
        # where (x, y) is the top-left corner
        cx, cy, w, h = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
        x = (cx - w / 2) * original_width
        y = (cy - h / 2) * original_height
        w_scaled = w * original_width
        h_scaled = h * original_height
        boxes_xywh = np.column_stack((x, y, w_scaled, h_scaled)).astype(int).tolist()

        # Build final results
        # RF-DETR uses 1-indexed class IDs (0 is background). The 'names' metadata is
        # keyed by the class ID the model outputs (1-indexed), so look up directly.
        final_results = []
        for i in range(len(boxes_xywh)):
            class_id = class_ids[i]
            class_name = self.class_names.get(class_id, f"Class {class_id}")
            final_results.append((boxes_xywh[i], scores[i], class_name))

        return final_results
