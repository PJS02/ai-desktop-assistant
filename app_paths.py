"""Location of installed files and writable application data."""
import os
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parent
IS_INSTALLED = (APP_ROOT / '.cloudy-installed').is_file()
BUNDLED_MODELS_DIR = APP_ROOT / 'models'
BUNDLED_TTS_MODELS = BUNDLED_MODELS_DIR / 'tts'
BUNDLED_TTS_RUNTIME = APP_ROOT.parent / 'runtime' / 'tts-python'
LOCAL_APP_DATA = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
USER_DATA_ROOT = LOCAL_APP_DATA / 'Cloudy' if IS_INSTALLED else APP_ROOT
APP_CONFIG_FILE = (USER_DATA_ROOT if IS_INSTALLED else Path.home() / '.ai_desktop_assistant') / 'config.json'
