"""Local Korean person-name recognition plugged into Microsoft Presidio."""

import math
import re

from presidio_analyzer import EntityRecognizer, RecognizerResult


MODEL_ID = "Leo97/KoELECTRA-small-v3-modu-ner"
PERSON_MIN_SCORE = 0.70
_pipeline = None


def _get_pipeline():
    global _pipeline
    if _pipeline is None:
        from transformers import AutoModelForTokenClassification, AutoTokenizer, pipeline

        tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, use_fast=True, trust_remote_code=False)
        tokenizer.model_max_length = min(tokenizer.model_max_length, 512)
        model = AutoModelForTokenClassification.from_pretrained(
            MODEL_ID, use_safetensors=True, trust_remote_code=False,
        )
        _pipeline = pipeline("token-classification", model=model, tokenizer=tokenizer,
                             aggregation_strategy="simple", stride=64, device=-1)
    return _pipeline


class KoreanPersonRecognizer(EntityRecognizer):
    def __init__(self):
        super().__init__(supported_entities=["PERSON"], supported_language="ko")

    def load(self):
        # The shared screenshot lock protects lazy model loading and inference.
        pass

    def analyze(self, text, entities, nlp_artifacts=None):
        if "PERSON" not in entities or not re.search(r"[가-힣A-Za-z]", text):
            return []
        results = []
        for item in _get_pipeline()(text):
            if item["entity_group"] != "PS":
                continue
            start, end, score = int(item["start"]), int(item["end"]), float(item["score"])
            if not 0 <= start < end <= len(text) or not math.isfinite(score) or not 0 <= score <= 1:
                raise ValueError("invalid Korean NER result")
            if score >= PERSON_MIN_SCORE and len(re.findall(r"[가-힣A-Za-z]", text[start:end])) >= 2:
                results.append(RecognizerResult(entity_type="PERSON", start=start, end=end, score=score))
        return results
