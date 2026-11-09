import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QWidget

from character.game_detection import activity_category
from character.game_rules import normalize_game_rules, load_game_rules, save_game_rules
from character.settings_controller import SettingsController
from character.settings_dialog import SettingsDialog


class Manager(QObject):
    settings_message = pyqtSignal(dict)
    process_started = pyqtSignal()


class GameRulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        workspace = Path.cwd().resolve()
        (workspace/'build').mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=workspace/'build')
        assert Path(self.directory.name).resolve().is_relative_to(workspace)
        self.path = Path(self.directory.name)/'config.json'
        self.path_patch = patch('character.config_manager.CONFIG_FILE', self.path)
        self.path_patch.start()

    def tearDown(self):
        self.path_patch.stop()
        self.directory.cleanup()

    def test_save_preserves_other_settings_and_applies_without_restart(self):
        self.path.write_text(json.dumps({'personality': 'keep', 'character_options': {'size_percent': 134}}))
        assert activity_category('CustomTitle.exe') == 'work'
        saved = save_game_rules({'included_processes': [r'C:\Games\CustomTitle.EXE', 'customtitle.exe']})
        assert saved['included_processes'] == ['customtitle.exe']
        assert activity_category('CustomTitle.exe') == 'game'
        assert load_game_rules() == saved
        config = json.loads(self.path.read_text())
        assert config['personality'] == 'keep' and config['character_options']['size_percent'] == 134
        save_game_rules({'included_processes': []})
        assert activity_category('CustomTitle.exe') == 'work'

    def test_exclusion_priority_and_exact_process_matching(self):
        rules = normalize_game_rules({'included_processes': ['MyGame.exe', 'chrome.exe'],
                                      'excluded_processes': ['MyGame.exe']})
        assert activity_category('MyGame.exe', rules) == 'work'
        assert activity_category('chrome.exe', rules) == 'game'
        assert activity_category('chromehelper.exe', rules) == 'web'
        rules = normalize_game_rules({'keywords': [], 'included_processes': ['custom.exe']})
        assert activity_category('steam.exe', rules) == 'work'
        assert activity_category('custom.exe', rules) == 'game'
        assert activity_category('customhelper.exe', rules) == 'work'

    def test_invalid_rules_do_not_overwrite_saved_config(self):
        self.path.write_text('{broken-json', encoding='utf-8')
        with self.assertRaises(ValueError):
            save_game_rules({})
        assert self.path.read_text() == '{broken-json'
        assert load_game_rules() == normalize_game_rules()
        for entry in ('*.exe', 'bad\nname.exe'):
            with self.assertRaises(ValueError):
                normalize_game_rules({'included_processes': [entry]})

    def make_dialog(self):
        local = {'character': {'width': 1920, 'height': 1080, 'personality': '(Default)'},
                 'voice': {'enabled': False, 'voice_id': 'F1'},
                 'ai': {'api_key': '', 'model': ''}, 'game_rules': load_game_rules()}
        models = Mock(last_result={}, active_engine=None)
        models.store.installed.return_value = False
        models.store.published.return_value = False
        with patch('character.settings_dialog.running_process_names', return_value=['customtitle.exe', 'steam.exe']):
            return SettingsDialog(local, model_manager=models)

    def test_editor_add_apply_reload_and_remove(self):
        d = self.make_dialog()
        h = QWidget()
        h.game_spectator = Mock()
        manager = Manager()
        controller = SettingsController(h, manager)
        controller.dialog = d
        d.apply_requested.connect(controller.apply)
        try:
            d.game_running_processes.setCurrentIndex(d.game_running_processes.findData('customtitle.exe'))
            d._add_running_game()
            d._add_running_game()
            assert d.game_processes.toPlainText().splitlines() == ['customtitle.exe']
            assert not self.path.exists()
            d.submit(False)
            assert activity_category('customtitle.exe') == 'game'
            assert not d.pending
            h.game_spectator.poll.assert_called_once()
            assert 'game_rules' not in d.changes()['local']
            reopened = self.make_dialog()
            assert reopened.game_processes.toPlainText() == 'customtitle.exe'
            reopened.close()
            d.game_processes.clear()
            d.submit(False)
            assert activity_category('customtitle.exe') == 'work'
        finally:
            d.close()
            h.deleteLater()

    def test_invalid_editor_input_stays_open_and_unsaved(self):
        d = self.make_dialog()
        callback = Mock()
        d.apply_requested.connect(callback)
        try:
            d.game_processes.setPlainText('*.exe')
            d.submit(False)
            assert not d.pending
            assert d.tabs.currentWidget() == d.game_rules_tab
            assert d.status.text()
            callback.assert_not_called()
            assert not self.path.exists()
        finally:
            d.close()


if __name__ == '__main__':
    unittest.main()
