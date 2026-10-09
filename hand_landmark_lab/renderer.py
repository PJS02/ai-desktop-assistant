"""Compatibility imports for the standalone landmark experiment."""
from pathlib import Path
import sys

# Keep direct execution of the lab working without installing the project.
_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from hand_overlay.renderer import (
    CONNECTIONS, TIPS, PALM, DesktopHandWindow, LandmarkWindow,
    desktop_geometry, draw_hand, fit_rect, palm_center, screen_point,
)
