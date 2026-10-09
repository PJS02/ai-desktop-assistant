"""Verify integrated views retain events and details while filters stay explicit."""
from datetime import datetime, timedelta
from collections import deque
import json
import threading
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QPlainTextEdit

from app_logging import LogEvent
from character.log_console import AppLogManager, LogWindow


@pytest.fixture
def view():
    app = QApplication.instance() or QApplication([])
    manager = AppLogManager()
    window = LogWindow(manager)
    yield app, manager, window
    window.shutdown()
    manager._unsubscribe()


def record(event, category='대화·AI', *, message='처리 기록', level='INFO', trace='turn-1', index=0, **data):
    return LogEvent(datetime(2026, 10, 8, 12, 0) + timedelta(milliseconds=index),
                    category, message, event, level, trace, data,
                    session_id='test-session', process_id=123, thread='test-thread')


def represented(window):
    return [entry for index in range(window.output.topLevelItemCount())
            for entry in window.output.topLevelItem(index).data(0, Qt.ItemDataRole.UserRole)]


def test_integrated_preserves_each_stage_and_full_request_response(view):
    app, manager, window = view
    full_prompt = '사용자 대화와 문맥\n' + '전문 내용 ' * 100
    full_response = '{"candidates": [{"text": "긴 응답 원문"}]}'
    stages = [
        record('dialogue.input_accepted', text='오늘은 어땠어?', source='typed'),
        record('dialogue.prompt_built', prompt=full_prompt),
        record('gemini.request', payload={'contents': full_prompt}, model='example-model'),
        record('gemini.attempt_started', attempt=1),
        record('gemini.http_failed', '오류', level='ERROR', source_category='대화·AI', status=429),
        record('gemini.retry_scheduled', level='WARNING', attempt=1, delay_seconds=2),
        record('gemini.attempt_started', attempt=2),
        record('gemini.http_response', body=full_response, status=200),
        record('dialogue.response_normalized', final_text='좋은 하루였어.'),
        record('dialogue.widget_shown', text='좋은 하루였어.', visible=True),
        record('tts.playback_started'),
        record('tts.playback_completed'),
        record('future.new_event', '시스템', message='새로운 기록', new_field='보존할 값'),
    ]
    for entry in stages:
        manager._accept(entry)
    app.processEvents()
    assert represented(window) == stages
    assert not window.fold_repeats.isChecked()
    window.tabs.setCurrentIndex(3)
    assert represented(window) == stages[:-1], 'domain view must include its errors and retries'
    window.subtabs.setCurrentIndex(2)
    window.search_input.setText('전문 내용 전문 내용')
    assert len(represented(window)) == 2
    window.output.setCurrentItem(window._entry_items[id(stages[1])])
    window.show_details()
    assert full_prompt in window.content_details.toPlainText()
    assert json.loads(window.details.toPlainText())['data']['prompt'] == full_prompt
    row = window.output.currentItem()
    row.setExpanded(True)
    app.processEvents()
    editor = window.output.itemWidget(row.child(0), 0)
    assert isinstance(editor, QPlainTextEdit)
    assert full_prompt in editor.toPlainText()
    window.search_input.clear()
    window.output.setCurrentItem(window._entry_items[id(stages[7])])
    assert full_response in window.content_details.toPlainText()


def test_error_warning_projection_keeps_source_domains(view):
    _, manager, window = view
    entries = [record('gemini.failed', '오류', level='ERROR', source_category='대화·AI'),
               record('render.dpi_fallback', '시스템', level='WARNING'),
               record('recognition.process_stderr', '사용자 인식', message='INFO: delegate ready')]
    for entry in entries:
        manager._accept(entry)
    window.tabs.setCurrentIndex(3)
    assert represented(window) == entries[:1]
    window.tabs.setCurrentIndex(5)
    assert represented(window) == entries[:2]
    window.subtabs.setCurrentIndex(1)
    assert represented(window) == entries[:1]
    window.subtabs.setCurrentIndex(2)
    assert represented(window) == entries[1:2]
    window.tabs.setCurrentIndex(1)
    assert represented(window) == entries[2:]


def test_fold_is_optional_and_preserves_individual_occurrences(view):
    app, manager, window = view
    same = [record('stt.status', '사용자 인식', index=index, status='listening') for index in range(3)]
    warning = [record('stt.status', '사용자 인식', level='WARNING', index=index, status='listening') for index in (3, 4)]
    changed = [record('stt.status', '사용자 인식', index=5, status='processing'),
               record('stt.status', '사용자 인식', trace='different-turn', index=6, status='processing')]
    entries = same + warning + changed
    for entry in entries:
        manager._accept(entry)
    assert window.output.topLevelItemCount() == len(entries)
    window.fold_repeats.setChecked(True)
    assert window.output.topLevelItemCount() == 5
    assert represented(window) == entries
    parent = window.output.topLevelItem(0)
    parent.setExpanded(True)
    app.processEvents()
    assert parent.childCount() == 3
    window.show_details()
    for index, entry in enumerate(same):
        assert entry.timestamp.strftime('%H:%M:%S.%f')[:-3] in parent.child(index).text(0)
        window.output.setCurrentItem(parent.child(index))
        assert json.loads(window.details.toPlainText())['timestamp'] == entry.timestamp.isoformat()
    window.fold_repeats.setChecked(False)
    assert window.output.topLevelItemCount() == len(entries)


def test_fold_never_crosses_hidden_records_and_raw_view_remains_raw(view):
    _, manager, window = view
    first = record('dialogue.input_waiting', message='원본 대기 문장', text='같은 문장')
    middle = record('app.started', '시스템', trace=None)
    last = record('dialogue.input_waiting', message='원본 대기 문장', text='같은 문장', index=2)
    for entry in (first, middle, last):
        manager._accept(entry)
    window.tabs.setCurrentIndex(3)
    window.fold_repeats.setChecked(True)
    assert window.output.topLevelItemCount() == 2
    window.subtabs.setCurrentIndex(4)
    assert window.output.topLevelItem(0).text(0) == first.format().replace('\n', ' ↵ ')
    manager._accept(record('dialogue.input_waiting', message=last.message, text='같은 문장', index=3))
    assert window.output.topLevelItemCount() == 2
    assert last.format().replace('\n', ' ↵ ') in window.output.topLevelItem(1).text(0)
    assert len(represented(window)) == 3


def test_compact_default_keeps_all_stages_and_full_payload_available(view):
    app, manager, window = view
    full_body = '입력과 문맥을 보존하는 본문\n' + '숨겨진 전문 확인 ' * 100
    entries = [
        record('dialogue.input_accepted', text='오늘은 어땠어?', source='typed'),
        record('gemini.request', payload={'contents': full_body}, model='example-model', index=1),
        record('gemini.http_failed', '오류', level='ERROR', source_category='대화·AI', status=429, index=2),
        record('gemini.retry_scheduled', level='WARNING', attempt=1, delay_seconds=2, index=3),
        record('gemini.http_response', status=200, body='모델의 실제 응답', index=4),
        record('tts.playback_completed', index=5),
    ]
    for entry in entries:
        manager._accept(entry)
    assert window.output.columnCount() == 1
    assert window.output.isHeaderHidden()
    assert window.controls_panel.isHidden()
    assert window.detail_tabs.isHidden()
    assert not window.controls_button.isChecked()
    assert not window.detail_button.isChecked()
    assert represented(window) == entries
    assert '오늘은 어땠어?' in window.output.topLevelItem(0).text(0)
    assert '[대화·AI]' in window.output.topLevelItem(0).text(0)
    assert '오류' in window.output.topLevelItem(2).text(0)
    assert '경고' in window.output.topLevelItem(3).text(0)
    row = window.output.topLevelItem(1)
    row.setExpanded(True)
    app.processEvents()
    editor = window.output.itemWidget(row.child(0), 0)
    assert isinstance(editor, QPlainTextEdit)
    assert json.dumps({'contents': full_body}, ensure_ascii=False, indent=2) in editor.toPlainText()
    window.output.setCurrentItem(row)
    window.show_details()
    assert json.loads(window.details.toPlainText())['data']['payload']['contents'] == full_body


def test_optional_controls_and_details_preserve_filter_and_selected_record(view):
    app, manager, window = view
    full_prompt = '선택한 요청의 전체 문맥\n필터용 고유 문장'
    selected = record('dialogue.prompt_built', prompt=full_prompt)
    other = record('dialogue.input_accepted', text='다른 입력', index=1)
    for entry in (selected, other):
        manager._accept(entry)
    window.controls_button.setChecked(True)
    assert not window.controls_panel.isHidden()
    window.tabs.setCurrentIndex(3)
    window.subtabs.setCurrentIndex(2)
    window.level_filter.setCurrentIndex(3)
    window.search_input.setText('필터용 고유 문장')
    window.output.setCurrentItem(window._entry_items[id(selected)])
    window.controls_button.setChecked(False)
    assert window.controls_panel.isHidden()
    assert window.current_category() == '대화·AI'
    assert window.current_topic() == '요청·응답 전문'
    assert window.level_filter.currentIndex() == 3
    assert window.search_input.text() == '필터용 고유 문장'
    assert represented(window) == [selected]
    window.show_details()
    assert window.detail_button.isChecked()
    assert not window.detail_tabs.isHidden()
    assert full_prompt in window.content_details.toPlainText()
    newer = record('gemini.request', payload={'contents': '필터용 고유 문장: 다음 요청'}, index=2)
    manager._accept(newer)
    app.processEvents()
    assert represented(window) == [selected, newer]
    assert window._selected_entry() is selected
    assert json.loads(window.details.toPlainText())['data']['prompt'] == full_prompt
    window.detail_button.setChecked(False)
    window.controls_button.setChecked(True)
    window.detail_button.setChecked(True)
    assert window._selected_entry() is selected
    assert json.loads(window.details.toPlainText())['data']['prompt'] == full_prompt
    assert window.current_topic() == '요청·응답 전문'
    assert window.search_input.text() == '필터용 고유 문장'


def test_same_flow_clears_level_filter_and_spans_domains(view):
    _, manager, window = view
    entries = [record('perception.speech.accepted', '사용자 인식'),
               record('gemini.http_failed', '오류', level='ERROR', source_category='대화·AI'),
               record('gemini.retry_scheduled', level='WARNING'),
               record('tts.playback_started'),
               record('app.started', '시스템', trace='another-flow')]
    for entry in entries:
        manager._accept(entry)
    window.tabs.setCurrentIndex(3)
    window.level_filter.setCurrentIndex(3)
    window.output.setCurrentItem(window._entry_items[id(entries[3])])
    window.show_trace()
    assert window.current_category() == '전체'
    assert window.current_topic() == '통합'
    assert window.level_filter.currentIndex() == 0
    assert represented(window) == entries[:-1]


def test_tab_memory_copy_modes_and_clear_while_paused(view, monkeypatch):
    _, manager, window = view
    copied = []
    monkeypatch.setattr(QApplication, 'clipboard', lambda: SimpleNamespace(setText=copied.append))
    entries = [record('dialogue.input_accepted', text='첫 문장'), record('tts.requested', text='두 문장')]
    for entry in entries:
        manager._accept(entry)
    window.tabs.setCurrentIndex(3)
    window.subtabs.setCurrentIndex(3)
    window.tabs.setCurrentIndex(1)
    window.tabs.setCurrentIndex(3)
    assert window.current_topic() == '음성 출력'
    window.subtabs.setCurrentIndex(0)
    window.output.setCurrentItem(window.output.topLevelItem(0))
    window.copy_logs()
    assert len(copied[-1].splitlines()) == 2
    window.copy_logs(selected_only=True)
    assert len(copied[-1].splitlines()) == 1
    window.toggle_pause()
    manager.clear()
    manager._accept(record('dialogue.input_accepted', text='새 문장'))
    assert window.output.topLevelItemCount() == 0
    assert window.details.toPlainText() == ''
    window.toggle_pause()
    assert len(represented(window)) == 1


def test_worker_burst_retention_has_no_stale_or_missing_visible_records(view):
    app, manager, window = view
    entries = [record('runtime.burst', '시스템', index=index, number=index) for index in range(5100)]
    worker = threading.Thread(target=lambda: [manager._accept(entry) for entry in entries])
    worker.start()
    worker.join()
    app.processEvents()
    app.processEvents()
    assert manager.evicted_count == 100
    assert represented(window) == entries[100:]
    assert window._visible_entries == manager.entries()


def test_out_of_order_worker_signals_reconcile_to_capture_order(view):
    app, manager, window = view
    entries = [record('runtime.order', '시스템', index=index, number=index) for index in range(2)]
    manager.blockSignals(True)
    for entry in entries:
        manager._accept(entry)
    manager.blockSignals(False)
    window.on_entry_added(entries[1])
    window.on_entry_added(entries[0])
    app.processEvents()
    assert represented(window) == entries


def test_retention_preserves_expanded_retained_rows_and_partial_fold_groups(view):
    app, manager, window = view
    manager._entries = deque(maxlen=3)
    entries = [record('runtime.keep', '시스템', index=index, number=index) for index in range(4)]
    for entry in entries[:3]:
        manager._accept(entry)
    row = window._entry_items[id(entries[1])]
    row.setExpanded(True)
    manager._accept(entries[3])
    app.processEvents()
    assert represented(window) == entries[1:]
    assert window._entry_items[id(entries[1])] is row
    assert row.isExpanded()
    manager.clear()
    window.fold_repeats.setChecked(True)
    same = [record('stt.status', '사용자 인식', index=index, status='listening') for index in range(3)]
    for entry in same:
        manager._accept(entry)
    folded = window.output.topLevelItem(0)
    folded.setExpanded(True)
    window.output.setCurrentItem(folded.child(2))
    different = record('stt.status', '사용자 인식', index=4, status='processing')
    manager._accept(different)
    app.processEvents()
    assert represented(window) == [*same[1:], different]
    assert folded.isExpanded() and folded.childCount() == 2
    assert window._selected_entry() is same[2]
    manager._accept(record('stt.status', '사용자 인식', index=5, status='processing'))
    assert window._selected_entry() is same[2]
