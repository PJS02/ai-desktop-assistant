"""Location of installed files and writable application data."""
import os
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parent
IS_INSTALLED = (APP_ROOT / '.cloudy-installed').is_file()
LOCAL_APP_DATA = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
USER_DATA_ROOT = LOCAL_APP_DATA / 'Cloudy' if IS_INSTALLED else APP_ROOT
