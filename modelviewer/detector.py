import cv2
import numpy as np
import onnxruntime as ort

from .image import Image


class Detector:
    """
    Class to detect fish in an image using a YOLO ONNX model.
    """

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
        except Exception as e:
            raise IOError(f"Error loading ONNX model from '{model_path}': {e}") from e

        # Get model input details
        self.input_name = self.session.get_inputs()[0].name
        input_shape = self.session.get_inputs()[0].shape
        self.input_height, self.input_width = input_shape[2], input_shape[3]

    def detect(self, image: Image, confidence_threshold: float = 0.5, nms_threshold: float = 0.45) -> list:
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
                final_results.append((boxes_for_nms[i], scores[i], class_ids[i]))

        return final_results