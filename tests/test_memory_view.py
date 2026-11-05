"""Exercise the settings memory viewer against a temporary SQLite store."""
import sqlite3
import threading
import time
from unittest.mock import Mock, patch

import pytest
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QAbstractItemView

from character.memory_view import MemoryView
from character.personality_system import PersonalitySystem
from character.settings_dialog import SettingsDialog
from character.tts_service import available_voices
from memory.long_term_memory import LongTermMemory
from test_vector_memory import FakeEmbedder


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def memory(tmp_path):
    store = LongTermMemory(tmp_path / 'memory.sqlite3', embedder=FakeEmbedder())
    yield store
    store.close()


def wait_for_page(app, view):
    deadline = time.monotonic() + 5
    while view._loading and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(1)
    assert not view._loading, 'memory page did not finish loading'


def test_list_includes_history_and_originals_without_embedding_or_writes(memory):
    old_id = memory.remember_fact('I like cats', original_text='Remember that I like cats.',
                                  importance=8, memory_type='profile', retention_policy='persistent')
    new_id = memory.remember_fact('I like dogs now', original_text='I prefer dogs now.',
                                  importance=8, superseded_memory_ids=[old_id])
    forgotten_id = memory.remember_fact('A temporary fact', original_text='Temporary original', importance=7)
    memory.forget(forgotten_id)
    before = memory._connection.execute('SELECT * FROM memories ORDER BY id').fetchall()
    memory._embedder = Mock()
    rows = memory.list_memories()
    assert [row['id'] for row in rows] == [forgotten_id, new_id, old_id]
    assert rows[0]['strength'] == 0
    assert rows[2]['superseded_by'] == new_id
    assert rows[2]['original_text'] == 'Remember that I like cats.'
    assert rows[2]['memory_type'] == 'profile'
    assert rows[2]['retention_policy'] == 'persistent'
    assert [row['id'] for row in memory.list_memories(limit=2, offset=1)] == [new_id, old_id]
    assert memory.list_memories(offset=100) == []
    assert 'embedding' not in rows[0]
    memory._embedder.encode.assert_not_called()
    assert memory._connection.execute('SELECT * FROM memories ORDER BY id').fetchall() == before


@pytest.mark.parametrize('limit,offset', [(0, 0), (-1, 0), (True, 0), (1.5, 0),
                                         (100, -1), (100, False), (100, '0')])
def test_list_rejects_invalid_paging(memory, limit, offset):
    with pytest.raises(ValueError):
        memory.list_memories(limit=limit, offset=offset)


def test_view_pages_refreshes_and_displays_full_original(app, memory):
    for index in range(5):
        memory.remember_fact(f'cats {index}\nsecond line', original_text=f'original {index}', importance=8)
    view = MemoryView(memory)
    view.PAGE_SIZE = 2
    view.show()
    wait_for_page(app, view)
    assert view.table.rowCount() == 2
    assert view.table.item(0, 0).text() == 'cats 4 second line'
    assert 'cats 4\nsecond line' in view.details.toPlainText()
    assert 'original 4' in view.details.toPlainText()
    assert '총 5개' in view.status.text()
    assert view.details.isReadOnly()
    assert view.table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
    assert not view.previous_button.isEnabled()
    assert view.next_button.isEnabled()
    view.next_button.click()
    wait_for_page(app, view)
    assert view.table.item(0, 0).text() == 'cats 2 second line'
    view.next_button.click()
    wait_for_page(app, view)
    assert view.table.rowCount() == 1
    assert not view.next_button.isEnabled()
    view.previous_button.click()
    wait_for_page(app, view)
    assert view.table.item(0, 0).text() == 'cats 2 second line'
    memory.remember('latest legacy entry')
    view.refresh_button.click()
    wait_for_page(app, view)
    assert view.table.item(0, 0).text() == 'latest legacy entry'
    assert view.table.item(0, 1).text() == '미평가'
    assert '별도 원문이 없는 기록입니다.' in view.details.toPlainText()
    view.close()


def test_empty_store_and_read_failure_can_be_refreshed(app, memory):
    view = MemoryView(memory)
    view.refresh()
    wait_for_page(app, view)
    assert view.table.rowCount() == 0
    assert view.status.text() == '저장된 장기기억이 없습니다.'
    assert not view.next_button.isEnabled()
    with patch.object(memory, 'list_memories', side_effect=sqlite3.OperationalError('unavailable')):
        view.refresh()
        wait_for_page(app, view)
    assert '불러오지 못했습니다' in view.status.text()
    assert view.refresh_button.isEnabled()
    memory.remember('cats after recovery')
    view.refresh_button.click()
    wait_for_page(app, view)
    assert view.table.item(0, 0).text() == 'cats after recovery'
    view.close()


def test_busy_memory_store_does_not_block_qt_thread(app, memory):
    view = MemoryView(memory)
    threads = []
    original_count = memory.count

    def count():
        threads.append(threading.get_ident())
        return original_count()

    with patch.object(memory, 'count', count), memory._lock:
        view.refresh()
        app.processEvents()
        assert view._loading
        assert not view.refresh_button.isEnabled()
    wait_for_page(app, view)
    assert threads and all(identifier != threading.get_ident() for identifier in threads)
    view.close()


def test_settings_tab_loads_the_supplied_store_without_setting_changes(app, memory):
    memory.remember('사용자는 고양이를 좋아합니다.')
    local = {'character': {'width': 1920, 'height': 1080,
                           'personality': PersonalitySystem.DEFAULT_PRESET},
             'voice': {'enabled': False, 'voice_id': available_voices()[0].id},
             'ai': {'api_key': '', 'model': ''}}
    with patch.object(SettingsDialog, '_refresh_voice_models'):
        dialog = SettingsDialog(local, model_manager=Mock(), long_term_memory=memory)
    assert dialog.tabs.tabText(dialog.tabs.indexOf(dialog.recognition_page)) == '카메라·마이크'
    assert dialog.tabs.tabText(dialog.tabs.indexOf(dialog.dialogue_page)) == '대화·음성'
    assert dialog.tabs.tabText(dialog.tabs.indexOf(dialog.memory_view)) == '장기기억'
    dialog.tabs.setCurrentWidget(dialog.memory_view)
    dialog.show()
    wait_for_page(app, dialog.memory_view)
    assert dialog.memory_view.table.item(0, 0).text() == '사용자는 고양이를 좋아합니다.'
    assert dialog.changes() == {'local': {}, 'remote': {}}
    dialog.close()
