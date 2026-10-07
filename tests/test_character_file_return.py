"""Disposable files exercise return counts, filesystem collisions, and failure recovery."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from character import character_widget
from character.character_widget import CharacterWidget


class Timer:
    def __init__(self):
        self.active = False
        self.timeout = SimpleNamespace(connect=lambda callback: setattr(self, 'callback', callback))

    def start(self, interval):
        self.active = True

    def stop(self):
        self.active = False

    def isActive(self):
        return self.active


class ItemHost:
    release_items_to_desktop = CharacterWidget.release_items_to_desktop
    _release_single_item = CharacterWidget._release_single_item

    def __init__(self, paths):
        self.held_items = [str(p) for p in paths]
        self.held_items_icons = {str(p): object() for p in paths}
        self._remaining_items_to_release = []
        self._release_timer = None
        self.mood_system = SimpleNamespace(on_item_dropped=Mock(), get_formatted_mood_log=lambda: '', decide_emotion=lambda: {})
        self.render = Mock()
        self.update_action = Mock()

    def x(self):
        return 0

    def y(self):
        return 0


@pytest.fixture
def item_paths(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    desktop = home / 'Desktop'
    desktop.mkdir(parents=True)
    monkeypatch.setattr(Path, 'home', lambda: home)
    monkeypatch.setattr(character_widget, 'QTimer', Timer)
    return tmp_path / 'held', desktop


def make_files(folder, count):
    folder.mkdir(exist_ok=True)
    paths = [folder / f'item-{i}.txt' for i in range(count)]
    for i, path in enumerate(paths):
        path.write_text(f'payload {i}', encoding='utf8')
    return paths


@pytest.mark.parametrize('count', [1, 2, 3])
def test_returns_every_count_and_finishes_once(item_paths, count):
    held, desktop = item_paths
    paths = make_files(held, count)
    host = ItemHost(paths)
    host.release_items_to_desktop()
    for _ in range(count - 1):
        assert host._release_timer.isActive()
        host._release_timer.callback()
    assert host.held_items == []
    assert host.held_items_icons == {}
    assert host._release_timer is None
    host.mood_system.on_item_dropped.assert_called_once()
    assert [p.read_text(encoding='utf8') for p in sorted(desktop.iterdir())] == [f'payload {i}' for i in range(count)]


def test_folder_return_keeps_existing_desktop_file(item_paths):
    held, desktop = item_paths
    held.mkdir()
    folder = held / 'folder'
    folder.mkdir()
    (folder / 'inside.txt').write_text('nested payload', encoding='utf8')
    (desktop / 'folder').mkdir()
    (desktop / 'folder' / 'original.txt').write_text('preserved', encoding='utf8')
    host = ItemHost([folder])
    host.release_items_to_desktop()
    assert (desktop / 'folder_1' / 'inside.txt').read_text(encoding='utf8') == 'nested payload'
    assert (desktop / 'folder' / 'original.txt').read_text(encoding='utf8') == 'preserved'


def test_repeat_return_request_does_not_skip_interval(item_paths):
    held, desktop = item_paths
    host = ItemHost(make_files(held, 2))
    host.release_items_to_desktop()
    timer = host._release_timer
    host.release_items_to_desktop()
    assert len(list(desktop.iterdir())) == 1
    assert host._release_timer is timer
    timer.callback()
    host.mood_system.on_item_dropped.assert_called_once()


def test_move_failure_keeps_queue_for_retry(item_paths, monkeypatch):
    held, desktop = item_paths
    paths = make_files(held, 2)
    host = ItemHost(paths)
    real_move = character_widget.shutil.move
    monkeypatch.setattr(character_widget.shutil, 'move', Mock(side_effect=PermissionError('test failure')))
    host.release_items_to_desktop()
    assert host._remaining_items_to_release == [str(p) for p in paths]
    assert host.held_items == [str(p) for p in paths]
    assert host._release_timer is None
    assert all(p.is_file() for p in paths)
    host.mood_system.on_item_dropped.assert_not_called()
    monkeypatch.setattr(character_widget.shutil, 'move', real_move)
    host.release_items_to_desktop()
    host._release_timer.callback()
    assert host.held_items == []


def test_new_drop_during_return_remains_held(item_paths):
    held, desktop = item_paths
    paths = make_files(held, 3)
    host = ItemHost(paths[:2])
    host.release_items_to_desktop()
    host.held_items.append(str(paths[2]))
    host.held_items_icons[str(paths[2])] = object()
    host._release_timer.callback()
    assert host.held_items == [str(paths[2])]
    assert paths[2].is_file()
    assert str(paths[2]) in host.held_items_icons
    host.mood_system.on_item_dropped.assert_not_called()
