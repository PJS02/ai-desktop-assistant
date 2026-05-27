# 해상도 설정 저장/불러오기
import json
from pathlib import Path


CONFIG_FILE = Path.home() / ".ai_desktop_assistant" / "config.json"


def load_config():
    """저장된 설정 불러오기"""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # 새로운 형식: resolution.width/height
                if 'resolution' in config:
                    return config['resolution'].get('width', 1920), config['resolution'].get('height', 1080)
                # 이전 형식 호환성: 최상위 width/height
                return config.get('width', 1920), config.get('height', 1080)
        except Exception as e:
            print(f"[설정 읽기 오류] {e}, 기본값 사용")
            return 1920, 1080
    return 1920, 1080


def save_config(width, height):
    """설정 저장"""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    config = {'resolution': {'width': width, 'height': height}}
    
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
        print(f"[설정 저장] {width}x{height}px → {CONFIG_FILE}")
    except Exception as e:
        print(f"[설정 저장 오류] {e}")
