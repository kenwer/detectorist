import re
import cv2
import numpy as np
import onnxruntime as ort

from .image_object import ImageObject


class Detector:
    """
    Class to detect objects in an image using machine learning.
    """

    @staticmethod
    def _label_class_names_to_dict(onnx_names_str):
        """
        Parses a string of class names (e.g. obtained from an ONNX model) into a dictionary.

        The input string is expected to be in a format like:
        "{0: 'Fish', 1: 'Bee', 2: 'Cat', ...}"

        Args:
            names_str (str): The string containing the class names.

        Returns:
            dict: A dictionary mapping class IDs to class names.
        """
        onnx_names_str = onnx_names_str.strip()
        if onnx_names_str.startswith("{") and onnx_names_str.endswith("}"):
            onnx_names_str = onnx_names_str[1:-1].strip()
        if not onnx_names_str:
            return {}
        entries = {}
        for part in re.split(r',\s*(?=\d+\s*:)', onnx_names_str):
            k, v = part.split(":", 1)
            key = int(k.strip())
            val = v.strip().strip("'\" ")
            entries[key] = val
        return entries

    def __init__(self, model_path: str):
        """
        Initializes the Detector by loading the ONNX model.

        Args:
            model_path (str): Path to the ONNX model file.

        Raises:
            IOError: If the model file cannot be loaded.
        """
        try:
            self.session = ort.InferenceSession(model_path)
            onnx_names_str = self.session.get_modelmeta().custom_metadata_map.get('names')
            self.class_names = self._label_class_names_to_dict(onnx_names_str)

        except Exception as e:
            raise IOError(f"Error loading ONNX model from '{model_path}': {e}") from e

        # Get model input details
        self.input_name = self.session.get_inputs()[0].name
        input_shape = self.session.get_inputs()[0].shape
        self.input_height, self.input_width = input_shape[2], input_shape[3]

    def detect(self, image: ImageObject, confidence_threshold: float = 0.5, nms_threshold: float = 0.45) -> list:
        """
        Detects objects in an image using the ONNX model.

        Args:
            image: The input image (Image object).
            confidence_threshold: The confidence threshold for filtering detections.
            nms_threshold: The Non-Maximum Suppression threshold.

        Returns:
            A list of bounding boxes for the detected objects.
            Each box is in [x, y, w, h] format.
        """
        original_height, original_width, _ = image.image_data.shape

        # Preprocess the image data so we can use it for the onnx model
        input_image = image.preprocess_for_onnx(self.input_width, self.input_height)

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