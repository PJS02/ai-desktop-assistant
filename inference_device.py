"""Use the same model device preference in the app and its worker processes."""

from functools import cache
import json
import os

from app_logging import log_event
from app_paths import APP_CONFIG_FILE


DEVICE_CHOICES = (('자동', 'auto'), ('CPU', 'cpu'), ('CUDA', 'cuda'))
DEVICE_ENV = 'CAPSTONE_INFERENCE_DEVICE'


def normalize_inference_device(value, *, strict=False):
    if value in ('auto', 'cpu', 'cuda'):
        return value
    if strict:
        raise ValueError('연산 장치는 자동, CPU, CUDA 중에서 선택해 주세요.')
    return 'auto'


def load_inference_device(path=APP_CONFIG_FILE):
    try:
        config = json.loads(path.read_text(encoding='utf-8'))
        return normalize_inference_device(config.get('inference_device'))
    except (OSError, ValueError, AttributeError):
        return 'auto'


@cache
def active_inference_device():
    inherited = os.environ.get(DEVICE_ENV)
    return normalize_inference_device(inherited) if inherited is not None else load_inference_device()


def configure_inference_process():
    mode = active_inference_device()
    os.environ[DEVICE_ENV] = mode
    if mode == 'cpu':
        os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
    return mode


def torch_device(torch, *, auto_cuda=False):
    requested = active_inference_device()
    if requested == 'cuda' or (requested == 'auto' and auto_cuda):
        if torch.cuda.is_available():
            try:
                # Driver discovery can succeed even when the wheel cannot run kernels on this GPU.
                torch.ones(1, device='cuda:0').item()
                return 'cuda:0'
            except (AssertionError, OSError, RuntimeError) as exc:
                log_event('inference.cuda_unavailable', 'CUDA 초기화 실패로 CPU를 사용합니다.',
                          level='WARNING', error=str(exc))
        elif requested == 'cuda':
            log_event('inference.cuda_unavailable', 'CUDA를 사용할 수 없어 CPU를 사용합니다.',
                      level='WARNING')
    return 'cpu'
