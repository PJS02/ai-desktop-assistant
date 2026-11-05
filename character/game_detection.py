"""Share the established process-keyword activity categories with animation."""
from dataclasses import dataclass
from pathlib import PureWindowsPath
import os
from .game_rules import load_game_rules


def activity_category(process, rules=None):
    process = PureWindowsPath(str(process)).name.lower()
    rules = load_game_rules() if rules is None else rules
    excluded = process in rules['excluded_processes']
    if not excluded and process in rules['included_processes']:
        return 'game'
    if any(token in process for token in ('chrome', 'firefox', 'edge')):
        return 'web'
    if any(token in process for token in ('vscode', 'code')):
        return 'development'
    if not excluded and any(token in process for token in rules['keywords']):
        return 'game'
    if any(token in process for token in ('discord', 'slack', 'telegram')):
        return 'communication'
    return 'work'


@dataclass(frozen=True)
class GameActivity:
    process: str
    title: str = ''


def active_game_activity():
    if os.name != 'nt':
        return None
    import psutil
    import win32gui
    import win32process
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd or not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
            return None
        pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        process = psutil.Process(pid).name()
        if activity_category(process) != 'game':
            return None
        return GameActivity(process, win32gui.GetWindowText(hwnd))
    except (OSError, psutil.Error, win32gui.error):
        return None


def game_context_instruction():
    return ('현재 활동은 설정의 게임 목록 또는 프로세스 키워드로 게임 활동으로 분류되었습니다. '
            '정확한 게임 이름과 플레이 상황은 확인하지 않았습니다. '
            '평소 성격과 말투를 유지하면서 관심이나 응원을 가끔 자연스럽게 표현하세요. '
            '억지로 훈수나 관람 대사를 넣지 마세요. 게임 화면을 본 것처럼 적, 체력, 승패, 공격을 언급하지 마세요. '
            '상황별 제안은 조건형으로 표현하고 모르는 공략이나 조작법을 지어내지 마세요.')
