"""Adapter for the pretrained EmotiEffNet B2 facial expression model."""

from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import torch


MODEL_NAME = "enet_b2_8"


class EmotiEffNetB2Recognizer:
    def __init__(self, weight_path):
        from emotiefflib import facial_analysis

        self.weight_path = Path(weight_path)
        if not self.weight_path.is_file():
            raise FileNotFoundError(self.weight_path)

        # The library normally downloads weights into the user's home directory.
        # Use the checked-in project model so startup also works offline.
        with patch.object(
            facial_analysis,
            "get_model_path_torch",
            return_value=str(self.weight_path),
        ):
            self.model = facial_analysis.EmotiEffLibRecognizer(
                engine="torch", model_name=MODEL_NAME, device="cpu"
            )

    def predict(self, face_bgr):
        if not isinstance(face_bgr, np.ndarray) or face_bgr.ndim != 3 or face_bgr.shape[2] != 3:
            raise ValueError("face_bgr must be a three-channel image")

        face_rgb = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2RGB)
        with torch.inference_mode():
            labels, probabilities = self.model.predict_emotions(face_rgb, logits=False)
        scores = {
            self.model.idx_to_emotion_class[index]: float(score)
            for index, score in enumerate(probabilities[0])
        }
        label = labels[0]
        return {
            "label": label,
            "confidence": scores[label],
            "scores": scores,
        }
