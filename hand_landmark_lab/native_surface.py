"""Compatibility imports for the shared owned Win32 hand surface."""
from pathlib import Path
import sys

# Keep direct execution of the lab working without installing the project.
_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from hand_overlay.native_surface import *
