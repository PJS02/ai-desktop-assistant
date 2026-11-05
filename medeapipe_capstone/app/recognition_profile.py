"""Keep the established tracker as default; allow bounded lightweight trials.

CAPSTONE_HOLISTIC_COMPLEXITY=1 selects a trial for one launch. The normal
launcher inherits no change, so unvalidated pose decisions are not made default.
"""
import os

from app_logging import log_event


def holistic_configuration():
    requested = os.environ.get('CAPSTONE_HOLISTIC_COMPLEXITY', '2')
    if requested not in ('1', '2'):
        log_event('recognition.profile.invalid', '유효하지 않은 인식 설정으로 기본 모델 사용',
                  category='사용자 인식', level='WARNING', requested=requested)
        requested = '2'
    return {
        'static_image_mode': False,
        'model_complexity': int(requested),
        'smooth_landmarks': True,
        'enable_segmentation': False,
        'refine_face_landmarks': True,
        'min_detection_confidence': .5,
        'min_tracking_confidence': .5,
    }
