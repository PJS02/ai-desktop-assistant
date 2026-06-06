# 해상도 설정 저장/불러오기
import json
from pathlib import Path


CONFIG_FILE = Path.home() / ".ai_desktop_assistant" / "config.json"


def load_config():
    """저장된 설정 불러오기 (해상도, 성격)"""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # 새로운 형식: resolution.width/height
                if 'resolution' in config:
                    width = config['resolution'].get('width', 1920)
                    height = config['resolution'].get('height', 1080)
                else:
                    # 이전 형식 호환성: 최상위 width/height
                    width = config.get('width', 1920)
                    height = config.get('height', 1080)
                
                # 성격 불러오기
                personality = config.get('personality', 'Russell (기본)')
                
                return width, height, personality
        except Exception as e:
            print(f"[설정 읽기 오류] {e}, 기본값 사용")
            return 1920, 1080, 'Russell (기본)'
    return 1920, 1080, 'Russell (기본)'


def save_config(width, height, personality='Russell (기본)'):
    """설정 저장 (해상도, 성격)"""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    config = {
        'resolution': {'width': width, 'height': height},
        'personality': personality
    }
    
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        print(f"[설정 저장] {width}x{height}px, 성격: {personality} → {CONFIG_FILE}")
    except Exception as e:
        print(f"[설정 저장 오류] {e}")
