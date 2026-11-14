# 캐릭터 대화 시스템
from PyQt6.QtCore import QDateTime, QTimer, pyqtSignal, pyqtSlot, QObject, Qt
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QToolTip
from .dialogue_widget import DialogueBubble, UserDialogueBubble, DialogueNarrationBox, DialogueInputWidget
from .tts_service import SupertonicTTS
from .config_manager import load_dialogue_style
from .dialogue_styles import normalize_dialogue_style
from .dialogue_options import DEFAULT_DIALOGUE_OPTIONS
from .dialogue_persona import character_voice
from .game_detection import game_context_instruction
from PyQt6.QtCore import QRect
from typing import Optional, List
import threading
import json
import math
import time
import re
from collections import deque
from app_logging import log_event, new_trace_id, register_secret
from ai.gemini_client import DAILY_REQUEST_QUOTA_EXHAUSTED, request_gemini
from memory.short_term_memory import ConversationMemory
from memory.long_term_memory import LongTermMemory
from memory.long_term_memory.dialogue_memory import (
    DIALOGUE_RESPONSE_SCHEMA, DIALOGUE_SYSTEM_INSTRUCTION,
    parse_dialogue_response, apply_dialogue_memory, build_memory_context, validate_memory_references,
)


FLASH_LITE_FALLBACK = {
    'gemini-3.5-flash-lite': 'gemini-3.1-flash-lite',
    'gemini-3.1-flash-lite': 'gemini-3.5-flash-lite',
}
FLASH_LITE_QUOTAS_EXHAUSTED = '[gemini error] Both Flash Lite daily request quotas exhausted'


class DialogueSystem(QObject):
    """캐릭터 대화 관리 시스템"""
    
    dialogue_started = pyqtSignal(str)  # 대화 시작
    dialogue_ended = pyqtSignal()       # 대화 종료
    user_input_received = pyqtSignal(str, str)  # text, text/voice
    ai_response_ready = pyqtSignal(object)
    ai_motion_changed = pyqtSignal(str)
    dialogue_model_switched = pyqtSignal(str, str)
    
    def __init__(self, character_widget, *, tts=None, response_provider=None,
                 time_provider=time.monotonic):
        """
        Args:
            character_widget: CharacterWidget 인스턴스
        """
        super().__init__()
        
        self.character_widget = character_widget
        self.current_dialogue: Optional[DialogueBubble] = None
        self.current_user_dialogue: Optional[UserDialogueBubble] = None
        self.current_narration: Optional[DialogueNarrationBox] = None
        self.current_input_widget: Optional[DialogueInputWidget] = None
        self.tts = tts if tts is not None else SupertonicTTS()
        self.bubble_style = load_dialogue_style()
        self._response_provider = response_provider
        self._time_provider = time_provider
        self.last_output_at = -math.inf
        self._closed = False
        self.manual_dialogue_active = False
        self._request_generation = 0
        self._active_input = None
        self._failed_inputs = {}
        self.user_input_epoch = 0
        self.pending_inputs = deque()
        self.conversation_history = []
        self.conversation_memory = ConversationMemory(max_messages=12, max_context_chars=4000)
        self.long_term_memory = LongTermMemory()
        self._speaking = False
        self._tts_busy = False
        self._pending_ai_response = None
        self._response_hold_until = 0.0
        self._input_wait_signature = None
        self._request_traces = {}
        self._input_timer = QTimer(self)
        self._input_timer.setSingleShot(True)
        self._input_timer.timeout.connect(self._process_next_input)
        self.ai_response_ready.connect(
            self._finish_ai_request, Qt.ConnectionType.QueuedConnection)
        if hasattr(self.tts, 'speaking_changed'):
            self.tts.speaking_changed.connect(self._on_tts_speaking_changed)
        if hasattr(self.tts, 'busy_changed'):
            self.tts.busy_changed.connect(self._on_tts_busy_changed)
        if hasattr(self.tts, 'sync_bubble_changed'):
            self.tts.sync_bubble_changed.connect(self._on_sync_bubble_changed)
        
        # 대화 큐
        self.dialogue_queue: List[dict] = []
        self.is_processing_queue = False
        
        # 큐 처리 타이머
        self.queue_timer = QTimer(self)
        self.queue_timer.setSingleShot(True)
        self._pending_dialogue = None
        self.queue_timer.timeout.connect(self._show_pending_dialogue)
        
        # Gemini 설정
        self.gemini_config = {}
        self._load_gemini_config()
        
        # 요청 제한 (수동 대화용)
        self.last_request_time = None  # monotonic request start; None allows the first request
        self.request_cooldown = DEFAULT_DIALOGUE_OPTIONS['request_cooldown']
        self.is_ai_responding = False  # AI 응답 중인지
    
    def _load_gemini_config(self):
        """Gemini 설정 파일 로드"""
        from .ai_settings import load_ai_settings
        try:
            self.gemini_config = load_ai_settings()
            register_secret(self.gemini_config.get('api_key', ''))
            print("[대화 시스템] Gemini 설정 로드 완료")
        except Exception as e:
            print(f"[경고] Gemini 설정 로드 실패: {e}")
    
    def show_dialogue(self, text: str, duration: int = 5000, 
                     use_narration: bool = False, character_name: str = "어시스턴트",
                     *, log_context=None):
        """
        대화 표시
        
        Args:
            text: 대화 텍스트
            duration: 표시 시간 (밀리초)
            use_narration: True면 하단 나레이션 박스 사용, False면 말풍선 사용
            character_name: 캐릭터 이름 (나레이션 사용 시)
        """
        if self._closed:
            log_event('dialogue.display_discarded', '종료 후 대사 표시 생략', category='대화·AI',
                      trace_id=(log_context or {}).get('trace_id'), reason='shutdown', text=text)
            return
        context = dict(log_context or {})
        context.setdefault('trace_id', new_trace_id('display'))
        log_event('dialogue.display_requested', '대사 표시 요청', category='대화·AI',
                  trace_id=context['trace_id'], text=text, duration_ms=duration,
                  display_type='narration' if use_narration else 'bubble')
        if use_narration:
            self._show_narration(text, character_name, duration, log_context=context)
        else:
            self._show_bubble(text, duration, log_context=context)
    
    def show_user_dialogue(self, text: str, duration: int = 3000, *, log_context=None):
        if not self._closed:
            self._show_bubble(text, duration, log_context=log_context, user=True)

    def show_manual_dialogue(self, user_text='', character_text=''):
        """Display authored bubbles without AI, speech or conversation history."""
        user_text, character_text = user_text.strip(), character_text.strip()
        if (not (user_text or character_text)
                or self.is_conversation_busy(include_hold=False, include_manual=False)):
            return False
        self.clear_queue(reason='manual_display_priority')
        self.manual_dialogue_active = True
        context = {'trace_id': new_trace_id('manual-display'), 'source': 'manual_display'}
        if character_text:
            self.show_dialogue(character_text, duration=0, log_context=context)
        if user_text:
            self.show_user_dialogue(user_text, duration=0, log_context=context)
        if self.current_user_dialogue is not None:
            self.current_user_dialogue.raise_()
        return True

    def speak_manual_dialogue(self, user_text='', character_text=''):
        """Read the authored character bubble using the existing voice/playback."""
        character_text = character_text.strip()
        if not character_text or not self.tts.enabled:
            return False
        if not self.show_manual_dialogue(user_text, character_text):
            return False
        context = dict(self.current_dialogue._log_context)
        context['source'] = 'manual_speech'
        log_event('dialogue.manual_speech_requested', '직접 입력한 캐릭터 대사 읽기',
                  category='대화·AI', trace_id=context['trace_id'], text=character_text)
        if callable(getattr(type(self.tts), 'speak_with_context', None)):
            self.tts.speak_with_context(character_text, context)
        else:
            self.tts.speak(character_text)
        return True

    def _show_bubble(self, text: str, duration: int, *, log_context=None, user=False):
        """말풍선 대화 표시"""
        slot = 'current_user_dialogue' if user else 'current_dialogue'
        display_type = 'user_bubble' if user else 'bubble'
        # 이전 말풍선 종료
        previous = getattr(self, slot)
        if previous:
            setattr(self, slot, None)
            log_event('dialogue.widget_replaced', '이전 말풍선 교체', category='대화·AI',
                      trace_id=getattr(previous, '_log_context', {}).get('trace_id'),
                      replacement_trace_id=(log_context or {}).get('trace_id'),
                      previous_text=previous.text, text=text, display_type=display_type)
            previous._log_close_reason = 'replaced'
            previous.close()
        
        # Owned tool windows stay above the character when Windows raises it.
        bubble = (UserDialogueBubble(text, duration, parent=self.character_widget) if user
                  else DialogueBubble(text, duration, parent=self.character_widget,
                                      style=self.bubble_style))
        bubble._log_context = dict(log_context or {})
        bubble.dialogue_closed.connect(lambda: self._on_bubble_closed(bubble))
        
        setattr(self, slot, bubble)
        self.update_dialogue_position()
        bubble.show()
        log_event('dialogue.widget_shown', '말풍선 위젯 표시', category='대화·AI',
                  trace_id=bubble._log_context.get('trace_id'), text=text,
                  display_type=display_type, visible=bubble.isVisible(), duration_ms=duration)
        
        if not user:
            self.last_output_at = self._time_provider()
            self.dialogue_started.emit(text)

    def set_bubble_style(self, style):
        self.bubble_style = normalize_dialogue_style(style, strict=True)
        if self.current_dialogue:
            self.current_dialogue.set_style(self.bubble_style)
            self.update_dialogue_position()

    def _on_bubble_closed(self, bubble):
        if not getattr(bubble, '_log_closed_recorded', False):
            bubble._log_closed_recorded = True
            log_event('dialogue.widget_closed', '말풍선 닫힘', category='대화·AI',
                      trace_id=getattr(bubble, '_log_context', {}).get('trace_id'),
                      reason=getattr(bubble, '_log_close_reason', 'closed'), text=bubble.text,
                      display_type='user_bubble' if isinstance(bubble, UserDialogueBubble) else 'bubble')
        if self.current_user_dialogue is bubble:
            self.current_user_dialogue = None
        elif self.current_dialogue is bubble:
            self._on_dialogue_closed()
        bubble.deleteLater()
    
    def _show_narration(self, text: str, character_name: str, duration: int, *, log_context=None):
        """하단 나레이션 박스 표시"""
        self.last_output_at = self._time_provider()
        # 이전 나레이션 종료
        if self.current_narration:
            previous, self.current_narration = self.current_narration, None
            log_event('dialogue.widget_replaced', '이전 내레이션 교체', category='대화·AI',
                      trace_id=getattr(previous, '_log_context', {}).get('trace_id'),
                      replacement_trace_id=(log_context or {}).get('trace_id'),
                      previous_text=previous.text, text=text, display_type='narration')
            previous._log_close_reason = 'replaced'
            previous.close()
        
        # 새 나레이션 생성
        narration = DialogueNarrationBox(text, character_name, duration)
        narration._log_context = dict(log_context or {})
        narration.closed.connect(lambda: self._on_narration_widget_closed(narration))
        narration.show()
        
        self.current_narration = narration
        log_event('dialogue.widget_shown', '내레이션 위젯 표시', category='대화·AI',
                  trace_id=narration._log_context.get('trace_id'), text=text,
                  display_type='narration', visible=narration.isVisible(), duration_ms=duration)
        self.dialogue_started.emit(text)

    def _on_narration_widget_closed(self, narration):
        if not getattr(narration, '_log_closed_recorded', False):
            narration._log_closed_recorded = True
            log_event('dialogue.widget_closed', '내레이션 닫힘', category='대화·AI',
                      trace_id=getattr(narration, '_log_context', {}).get('trace_id'),
                      reason=getattr(narration, '_log_close_reason', 'closed'), text=narration.text,
                      display_type='narration')
        if self.current_narration is narration:
            self._on_narration_closed()
        narration.deleteLater()
    
    def queue_dialogue(self, text: str, duration: int = 5000,
                       use_narration: bool = False, 
                       character_name: str = "어시스턴트",
                       delay_ms: int = 0, *, log_context=None):
        """
        대화를 큐에 추가 (순차적 표시)
        
        Args:
            text: 대화 텍스트
            duration: 표시 시간
            use_narration: 나레이션 박스 사용 여부
            character_name: 캐릭터 이름
            delay_ms: 표시 전 지연시간
        """
        if self._closed:
            return
        context = dict(log_context or {})
        context.setdefault('trace_id', new_trace_id('script'))
        self.dialogue_queue.append({
            'text': text,
            'duration': duration,
            'use_narration': use_narration,
            'character_name': character_name,
            'delay': delay_ms,
            'log_context': context
        })
        log_event('dialogue.script_queued', '대사 표시 대기열 추가', category='대화·AI',
                  trace_id=context['trace_id'], text=text, queue_size=len(self.dialogue_queue),
                  delay_ms=delay_ms)
        
        # 큐 처리 시작 (아직 진행 중이 아니면)
        if not self.is_processing_queue:
            self._process_next_dialogue()
    
    def _process_next_dialogue(self):
        """큐에서 다음 대화 처리"""
        self.queue_timer.stop()
        
        if self._closed or not self.dialogue_queue:
            self.is_processing_queue = False
            self.dialogue_ended.emit()
            return
        
        self.is_processing_queue = True
        
        # 첫 번째 항목 추출
        dialogue_item = self.dialogue_queue.pop(0)
        
        # 지연시간이 있으면 타이머 설정
        if dialogue_item['delay'] > 0:
            self._pending_dialogue = dialogue_item
            self.queue_timer.start(dialogue_item['delay'])
        else:
            self._show_dialogue_from_queue(dialogue_item)

    def _show_pending_dialogue(self):
        item, self._pending_dialogue = self._pending_dialogue, None
        if item is not None and not self._closed:
            self._show_dialogue_from_queue(item)
    
    def _show_dialogue_from_queue(self, dialogue_item: dict):
        """큐 항목에서 대화 표시"""
        self.show_dialogue(
            text=dialogue_item['text'],
            duration=dialogue_item['duration'],
            use_narration=dialogue_item['use_narration'],
            character_name=dialogue_item['character_name'],
            log_context=dialogue_item.get('log_context')
        )
    
    def _on_dialogue_closed(self):
        """말풍선 종료 이벤트"""
        self.current_dialogue = None
        
        # 큐가 있으면 다음 처리
        if self.dialogue_queue:
            self._process_next_dialogue()
        else:
            self.is_processing_queue = False
            self.dialogue_ended.emit()
    
    def _on_narration_closed(self):
        """나레이션 종료 이벤트"""
        self.current_narration = None
        
        # 큐가 있으면 다음 처리
        if self.dialogue_queue:
            self._process_next_dialogue()
        else:
            self.is_processing_queue = False
            self.dialogue_ended.emit()
    
    def clear_queue(self, reason='cleared'):
        """대화 큐 비우기"""
        items = list(self.dialogue_queue)
        if self._pending_dialogue is not None:
            items.append(self._pending_dialogue)
        for item in items:
            log_event('dialogue.script_cancelled', '대기 대사 취소', category='대화·AI',
                      trace_id=item.get('log_context', {}).get('trace_id'),
                      reason=reason, text=item['text'])
        self.dialogue_queue.clear()
        self.queue_timer.stop()
        self._pending_dialogue = None
        self.is_processing_queue = False
    
    def close_current_dialogue(self, reason='closed'):
        """현재 표시 중인 대화 종료"""
        self.manual_dialogue_active = False
        if self.current_user_dialogue:
            self.current_user_dialogue._log_close_reason = reason
            self.current_user_dialogue.close()
        if self.current_dialogue:
            self.current_dialogue._log_close_reason = reason
            self.current_dialogue.close()
        if self.current_narration:
            self.current_narration._log_close_reason = reason
            self.current_narration.close()
    
    def update_dialogue_position(self):
        """캐릭터 위치 변화에 따라 현재 대화의 위치 업데이트"""
        if self.current_dialogue or self.current_user_dialogue:
            host = self.character_widget
            measure = getattr(host, '_physics_body_rect', None)
            body = measure() if measure else QRect(0, 0, host.width(), host.height())
            game = getattr(host, 'rps_game', None)
            cham = getattr(host, 'cham_game', None)
            if cham is not None and cham.isVisible():
                game = cham
            avoid = game.geometry() if game is not None and game.isVisible() else None
            if self.current_dialogue:
                self.current_dialogue.update_position_with_character(
                    host.x() + body.x(), host.y() + body.y(), body.width(), body.height(), avoid)
            if self.current_user_dialogue:
                user_avoid = avoid
                if self.current_dialogue:
                    user_avoid = self.current_dialogue.geometry().united(avoid) if avoid else self.current_dialogue.geometry()
                self.current_user_dialogue.update_position_with_character(
                    host.x() + body.x(), host.y() + body.y(), body.width(), body.height(), user_avoid)
    
    def is_dialogue_active(self) -> bool:
        """현재 대화 표시 중인지 확인"""
        return (self.current_dialogue is not None or self.current_user_dialogue is not None or
                self.current_narration is not None or
                len(self.dialogue_queue) > 0)
    # ===== AI 대화 시스템 ======
    
    def ask_ai(self, user_input: str):
        """Accept typed dialogue through the same ordered path as final speech."""
        return self._submit_input(user_input, source="text")

    def submit_speech(self, text: str, *, log_context=None):
        """Called only for a new, completed utterance by PerceptionController."""
        return self._submit_input(text, source="voice", log_context=log_context)

    def submit_speech_with_context(self, text: str, context):
        """Optional perception bridge; legacy callbacks still receive only text."""
        return self.submit_speech(text, log_context=context)

    def _submit_input(self, text: str, source: str, *, log_context=None, retry=None) -> bool:
        context = dict(log_context or {})
        trace_id = context.get('trace_id') or new_trace_id('turn')
        register_secret(self.gemini_config.get('api_key', ''))
        if self._closed or not isinstance(text, str) or not text.strip():
            log_event('dialogue.input_rejected', '사용자 입력 거부', category='대화·AI',
                      trace_id=trace_id, source=source, raw_text=text,
                      reason='shutdown' if self._closed else 'invalid_or_empty_input')
            return False
        raw_text = text
        text = text.strip()
        self.manual_dialogue_active = False
        self.user_input_epoch += 1
        # A direct user turn takes priority over a delayed ambient script.
        self.clear_queue(reason='user_input_priority')
        turn_id = len(self.conversation_history)
        chat_id = retry['chat_id'] if retry is not None else turn_id
        retry_of = retry['trace_id'] if retry is not None else None
        turn = {'role': 'user', 'text': text, 'source': source,
                'state': 'queued', 'turn_id': turn_id, 'chat_id': chat_id,
                'trace_id': trace_id, 'log_context': {**context, 'trace_id': trace_id, 'source': source},
                'queued_at': self._time_provider(), 'retry_of': retry_of}
        self.conversation_history.append(turn)
        self.pending_inputs.append(turn)
        self._display_chat_message(turn)
        log_event('dialogue.input_accepted', '사용자 입력 접수', category='대화·AI',
                  trace_id=trace_id, source=source, raw_text=raw_text, text=text,
                  turn_id=turn['turn_id'], queue_size=len(self.pending_inputs),
                  retry_of=retry_of, speech=context if source == 'voice' else None)
        self.user_input_received.emit(text, source)
        self._process_next_input()
        return True

    def _process_next_input(self):
        self._input_timer.stop()
        if self._closed or not self.pending_inputs:
            self._input_wait_signature = None
            return
        reason = ('ai_processing' if self.is_ai_responding else
                  'audio_playback' if self._speaking else
                  'tts_synthesis' if self._tts_busy else None)
        if reason:
            self._log_input_wait(reason)
            return
        now = self._time_provider()
        cooldown_wait = (self.request_cooldown - (now - self.last_request_time)
                         if self.last_request_time is not None else 0.0)
        hold_wait = self._response_hold_until - now
        wait = max(cooldown_wait, hold_wait)
        if wait > 0:
            self._log_input_wait('cooldown' if cooldown_wait >= hold_wait else 'response_hold',
                                 remaining_seconds=round(wait, 3),
                                 cooldown_seconds=max(0, round(cooldown_wait, 3)),
                                 response_hold_seconds=max(0, round(hold_wait, 3)))
            self._input_timer.start(max(1, math.ceil(wait * 1000)))
            return

        self._input_wait_signature = None
        turn = self.pending_inputs.popleft()
        self._active_input = turn
        self.is_ai_responding = True
        self._set_input_state(turn, 'responding')
        self.ai_motion_changed.emit('waiting')
        self.last_request_time = now
        self._request_generation += 1
        generation = self._request_generation
        self._request_traces[generation] = turn['trace_id']
        turn['started_at'] = now
        context = turn['log_context']
        log_event('dialogue.processing_started', '사용자 입력 처리 시작', category='대화·AI',
                  trace_id=turn['trace_id'], turn_id=turn['turn_id'], generation=generation,
                  queue_size=len(self.pending_inputs),
                  queued_seconds=round(now - turn['queued_at'], 3))
        # Keep the question visible through network/TTS preparation, then allow
        # the user to read it alongside the actual answer.
        self.show_user_dialogue(turn['text'], duration=0, log_context=context)
        try:
            # 아직 대기 중인 다음 입력이 현재 요청의 기억에 섞이지 않게 한다.
            self.conversation_memory.add("user", turn['text'])
            recent_context = self.conversation_memory.build_context()
            if not self.gemini_config:
                self._load_gemini_config()
            # Read character state and configuration on the Qt thread; workers only
            # receive plain snapshots and never touch character/UI objects.
            prompt = self._build_user_prompt(turn['text'])
            config = dict(self.gemini_config)
            config['character_voice'] = character_voice(self.character_widget.personality_system)
            register_secret(config.get('api_key', ''))
            completed = sorted(
                (item for item in self.conversation_history
                 if item['state'] == 'completed' and item['source'] != 'automatic'),
                key=lambda item: (item['turn_id'], item['role'] != 'user'))[-12:]
            log_event('dialogue.prompt_built', '직접 대화 프롬프트 전체', category='대화·AI',
                      trace_id=turn['trace_id'], prompt=prompt, model=config.get('model'),
                      history_count=len(completed),
                      history=[{'turn_id': item['turn_id'], 'role': item['role'],
                                'trace_id': item.get('trace_id')} for item in completed])
        except Exception as exc:
            log_event('dialogue.request_preparation_failed', '대화 요청 준비 실패', category='대화·AI',
                      level='ERROR', trace_id=turn['trace_id'], error=str(exc))
            self.ai_response_ready.emit((generation, "미안해요, 지금은 대화할 수 없어요. 다시 시도해 주세요.", True))
            return

        def get_ai_response():
            failed = False
            model_switch = None
            try:
                # E5 로딩·검색·저장은 Qt 스레드를 막지 않도록 이 작업 스레드에서 실행한다.
                candidates = []
                if self.long_term_memory.count():
                    recall_query = f"{turn['text']}\n최근 대화 문맥:\n{recent_context[-1000:]}"
                    candidates = self.long_term_memory.search_candidates(recall_query)
                long_term_context, recalled_memories = build_memory_context(candidates, self.long_term_memory.settings)
                memory_prompt = prompt + f"""

{long_term_context}"""
                raw_response = self._call_ai(memory_prompt, config, log_context=context)
                fallback_model = FLASH_LITE_FALLBACK.get(config.get('model'))
                if (fallback_model and raw_response == DAILY_REQUEST_QUOTA_EXHAUSTED
                        and not self._closed and generation == self._request_generation):
                    raw_response = self._call_ai(
                        memory_prompt, {**config, 'model': fallback_model}, log_context=context)
                    if raw_response == DAILY_REQUEST_QUOTA_EXHAUSTED:
                        raw_response = FLASH_LITE_QUOTAS_EXHAUSTED
                    else:
                        model_switch = (config.get('api_key', ''), config['model'], fallback_model)
                failed = self._is_error_response(raw_response)
                log_event('dialogue.model_text_received', '대화 모델 텍스트 전체', category='대화·AI',
                          level='ERROR' if failed else 'INFO', trace_id=turn['trace_id'],
                          raw_response=raw_response, failed=failed)
                response_text = self._process_gemini_response(raw_response, log_context=context)
                metadata = parse_dialogue_response(raw_response)
                if metadata and not validate_memory_references(metadata, recalled_memories, candidates):
                    failed = True
                    metadata = None
                    response_text = "기억 참조를 확인하지 못했어요. 다시 말씀해 주세요."
                    log_event('dialogue.memory_references_rejected', '제공 범위를 벗어난 기억 참조 거부',
                              category='오류', level='ERROR', trace_id=turn['trace_id'])
                if metadata and not failed and not self._closed and generation == self._request_generation:
                    self.conversation_memory.add("assistant", response_text)
                    try:
                        apply_dialogue_memory(self.long_term_memory, metadata, recalled_memories, turn['text'], candidates=candidates)
                    except Exception as exc:
                        log_event('dialogue.memory_failed', '장기기억 저장 실패', category='오류',
                                  level='ERROR', trace_id=turn['trace_id'], error=str(exc))
            except Exception as exc:
                log_event('dialogue.response_failed', '대화 AI 응답 처리 실패', category='대화·AI',
                          level='ERROR', trace_id=turn['trace_id'], error=str(exc))
                failed = True
                response_text = "미안해요, 지금은 대화할 수 없어요. 다시 시도해 주세요."
            if not self._closed:
                self.ai_response_ready.emit((generation, response_text, failed, model_switch if not failed else None))
            else:
                log_event('dialogue.response_discarded', '종료 후 늦은 응답 폐기', category='대화·AI',
                          trace_id=turn['trace_id'], reason='shutdown', generation=generation,
                          response=response_text)
                self._request_traces.pop(generation, None)

        threading.Thread(target=get_ai_response, daemon=True,
                         name=f"character-dialogue-{generation}").start()

    def _log_input_wait(self, reason, **data):
        turn = self.pending_inputs[0]
        signature = (turn.get('trace_id'), reason, len(self.pending_inputs))
        if signature != self._input_wait_signature:
            self._input_wait_signature = signature
            log_event('dialogue.input_waiting', '사용자 입력 대기', category='대화·AI',
                      trace_id=turn.get('trace_id'), reason=reason,
                      queue_size=len(self.pending_inputs), **data)

    def _build_user_prompt(self, user_input):
        mood = self.character_widget.mood_system
        personality = self.character_widget.personality_system
        history = self.conversation_memory.build_context() or '(이전 대화 없음)'
        spectator = getattr(self.character_widget, 'game_spectator', None)
        game_context = (game_context_instruction(spectator.activity)
                        if spectator and spectator.activity else '')
        return f"""{character_voice(personality)}
{game_context}

캐릭터 성격 (Big Five):
{personality.get_personality_for_prompt()}
성격 지침:
{personality.get_dialogue_tone_hints()}
현재 감정 상태:
{mood.get_emotion_description_for_prompt()}
감정별 말투 지침:
{mood.get_emotion_tone_instructions()} 감정은 어휘와 문장 호흡에만 약하게 반영하세요. 기본 반말·호칭과 설정된 성격을 유지하세요.

이전 대화:
{history}
사용자 입력:
{user_input}

지침을 따르면서 사용자에게 자연스럽고 친근한 대답을 해주세요.
응답은 반드시 아래 JSON 형식만 사용하세요.
{{"text": "사용자에게 보여줄 한두 문장 답변", "importance": 0~10 정수, "emotional_intensity": 0~10 정수,
"used_memory_ids": [], "memory_summary": "사용자 입력의 핵심 기억 또는 빈 문자열", "duplicate_memory_id": 0,
"superseded_memory_ids": [], "relevant_memory_ids": [], "memory_type": "unknown", "retention_policy": "standard"}}

명확한 사용자 정보 수정은 새 사실을 memory_summary에 넣고 대체할 제공 기억의 ID를 superseded_memory_ids에 넣으세요.
같은 대상의 현재 사실을 분명하게 정정한 경우에만 대체하며, 일시적인 감정·다른 시점의 사건·불확실한 추측은 대체하지 마세요.

emotional_intensity는 이 대화가 캐릭터에게 얼마나 감정적인 기억인지 별도로 평가하세요.
캐릭터의 성격과 현재 감정 상태를 고려해 기쁨, 슬픔, 두려움, 애착 등 감정 반응의 강도를 0~10 정수로 표현하세요.
감정이 긍정적인지 부정적인지와 관계없이 강도가 높으면 높은 점수, 평범하고 담담한 정보면 낮은 점수를 부여하세요.
emotional_intensity는 저장 중요도 importance와 별개의 점수입니다.

【 장기기억 중요도 판단 기준 】
사용자 입력을 최근 대화와 검색된 장기기억 문맥에 비추어 아래 기준으로 평가하세요.
1. 미래에 다시 언급될 가능성이 있는가?
2. 사용자의 취향/관계/성향에 관한 정보인가?
3. 중요한 사건인가?
4. 약속이나 계획인가?
5. 새롭게 알게 된 사실인가?
6. 사용자가 명시적으로 기억해달라고 했는가?

기준의 충족 정도와 향후 대화에서의 가치를 종합해 importance를 0~10 정수로 평가하세요.
7점 이상은 장기기억에 저장할 가치가 있는 정보에 부여하세요.
명시적인 기억 요청은 높은 중요도로 평가하세요.
가벼운 인사, 일시적 잡담, 새로운 정보가 없는 반복은 낮게 평가하세요."""

    def _call_ai(self, prompt, config, *, log_context=None):
        if self._response_provider is not None:
            log_event('dialogue.provider_called', '사용자 정의 응답 제공자 호출', category='대화·AI',
                      trace_id=(log_context or {}).get('trace_id'), model=config.get('model'))
            return self._response_provider(prompt, config)
        return request_gemini(prompt, config, response_schema=DIALOGUE_RESPONSE_SCHEMA,
                              system_instruction=DIALOGUE_SYSTEM_INSTRUCTION+'\n\n'+config.get('character_voice', character_voice()),
                              log_context=log_context)

    @staticmethod
    def _is_error_response(response):
        if not response:
            return True
        text = str(response).lower()
        return text.startswith('[gemini error]') or text.startswith(
            ('http error ', 'error: ', 'error ')) and any(
                marker in text for marker in ('429', '401', '403', '500',
                    'too many requests', 'unauthorized', 'forbidden', 'internal server error'))

    def _save_dialogue_model_switch(self, api_key, previous, model, *, trace_id):
        from .ai_settings import load_ai_settings, save_ai_settings

        try:
            config = load_ai_settings()
            if (config.get('api_key'), config.get('model')) != (api_key, previous):
                return  # A newer choice in Settings takes precedence.
            save_ai_settings(api_key, model, trace_id=trace_id)
        except (OSError, ValueError) as exc:
            log_event('dialogue.model_switch_save_failed', '대화용 모델 전환 저장 실패',
                      category='대화·AI', level='ERROR', trace_id=trace_id, error=str(exc))
            return
        self.gemini_config = {**config, 'model': model}
        log_event('dialogue.model_switched', '일일 요청 한도 초과로 대화용 모델 전환',
                  category='대화·AI', trace_id=trace_id, previous_model=previous, model=model)
        self.dialogue_model_switched.emit(previous, model)

    @pyqtSlot(object)
    def _finish_ai_request(self, result):
        generation, response_text, failed, *extra = result
        model_switch = extra[0] if extra else None
        trace_id = self._request_traces.pop(generation, None)
        if self._closed or generation != self._request_generation:
            log_event('dialogue.response_discarded', '만료된 대화 응답 폐기', category='대화·AI',
                      trace_id=trace_id, reason='shutdown' if self._closed else 'generation_mismatch',
                      generation=generation, response=response_text)
            return
        turn = self._active_input
        if turn is None:
            log_event('dialogue.response_discarded', '대상 입력 없는 응답 폐기', category='대화·AI',
                      trace_id=trace_id, reason='no_active_input', generation=generation)
            return
        if model_switch:
            self._save_dialogue_model_switch(*model_switch, trace_id=trace_id)
        turn['state'] = 'failed' if failed else 'completed'
        if failed:
            self._failed_inputs[turn['chat_id']] = turn
        reply_index = len(self.conversation_history)
        self.conversation_history.append({
            'role': 'assistant', 'text': response_text,
            'source': turn['source'], 'state': turn['state'],
            'turn_id': turn['turn_id'], 'chat_id': turn['chat_id'], 'trace_id': turn['trace_id']})
        log_event('dialogue.turn_failed' if failed else 'dialogue.turn_completed',
                  '대화 요청 실패' if failed else '대화 요청 완료', category='대화·AI',
                  level='ERROR' if failed else 'INFO', trace_id=turn['trace_id'],
                  turn_id=turn['turn_id'], response=response_text, state=turn['state'],
                  elapsed_seconds=round(self._time_provider() - turn['started_at'], 3))
        self._active_input = None
        self.is_ai_responding = False
        self._response_hold_until = self._time_provider() + 5.0
        context = {**turn['log_context'], 'chat_reply_index': reply_index}
        self.show_ai_response(response_text, log_context=context, failed=failed)
        self._process_next_input()

    @property
    def _last_failed_input(self):
        return next(reversed(self._failed_inputs.values()), None)

    def retry_last_input(self):
        previous = self._last_failed_input
        return previous is not None and self.retry_input(previous['chat_id'])

    def retry_input(self, chat_id):
        if self._closed:
            return False
        previous = self._failed_inputs.pop(chat_id, None)
        if previous is None:
            return False
        log_event('dialogue.retry_requested', '실패한 대화 재시도 요청', category='대화·AI',
                  trace_id=previous['trace_id'], turn_id=previous['turn_id'])
        return self._submit_input(previous['text'], previous['source'], retry=previous)

    def cancel_input(self, chat_id):
        if self._closed:
            return False
        turn = next((item for item in self.pending_inputs if item['chat_id'] == chat_id), None)
        if turn is None:
            return False
        self.pending_inputs.remove(turn)
        self._set_input_state(turn, 'cancelled')
        log_event('dialogue.turn_cancelled', '사용자 대기 메시지 전송 취소', category='대화·AI',
                  trace_id=turn['trace_id'], turn_id=turn['turn_id'], reason='user_cancelled',
                  phase='queued', queue_size=len(self.pending_inputs))
        self._process_next_input()
        return True

    def _set_input_state(self, turn, state):
        turn['state'] = state
        if self.current_input_widget is not None:
            self.current_input_widget.set_message_state(turn['chat_id'], state)

    def _on_tts_speaking_changed(self, speaking):
        if speaking or self._speaking:
            self.last_output_at = self._time_provider()
        self._speaking = bool(speaking)
        if self._speaking:
            self._flush_ai_response('playback_started')
        for bubble in (self.current_dialogue, self.current_user_dialogue):
            if bubble is not None:
                if self._speaking:
                    bubble.close_timer.stop()
                elif bubble.duration > 0 and not bubble.is_hovering:
                    bubble.close_timer.start(bubble.duration)
        if not self._speaking:
            self._process_next_input()

    def _on_tts_busy_changed(self, busy):
        self._tts_busy = bool(busy)
        if not self._tts_busy:
            self._flush_ai_response('tts_unavailable')
            self._process_next_input()

    def _on_sync_bubble_changed(self, enabled):
        if not enabled:
            self._flush_ai_response('sync_disabled')

    def _flush_ai_response(self, reason):
        pending, self._pending_ai_response = self._pending_ai_response, None
        if pending is None or self._closed:
            return False
        text, context, legacy = pending
        if context.get('game_process') and reason != 'ai_error':
            spectator = getattr(self.character_widget, 'game_spectator', None)
            if spectator is None or not spectator.response_is_current(context):
                log_event('dialogue.automatic_discarded', '음성 대기 중 오래된 게임 반응 폐기',
                          category='대화·AI', trace_id=context.get('trace_id'), reason='stale_game_response')
                if context.get('source') and callable(getattr(type(self.tts), 'stop_clip', None)):
                    self.tts.stop_clip(context['source'])
                return False
        if reason != 'ai_error':
            self.ai_motion_changed.emit('idle')
        # Count the normal reading interval from display, including delayed audio.
        self._response_hold_until = max(self._response_hold_until, self._time_provider() + 5.0)
        if (reply_index := context.get('chat_reply_index')) is not None:
            self._display_chat_message(self.conversation_history[reply_index])
        elif context.get('chat_automatic') and reason != 'ai_error':
            turn_id = len(self.conversation_history)
            turn = {'role': 'assistant', 'text': text, 'source': 'automatic', 'state': 'completed',
                    'turn_id': turn_id, 'chat_id': turn_id, 'trace_id': context['trace_id']}
            self.conversation_history.append(turn)
            self._display_chat_message(turn)
        if legacy and getattr(self.show_dialogue, '__func__', None) is not DialogueSystem.show_dialogue:
            self.show_dialogue(text, duration=5000)
        else:
            self.show_dialogue(text, duration=5000, log_context=context)
        if context.get('game_reaction') and reason != 'ai_error':
            self.character_widget.game_spectator.play_ai_reaction(context)
        if self.current_user_dialogue is not None:
            self.current_user_dialogue.duration = 5000
            if not self._speaking and not self.current_user_dialogue.is_hovering:
                self.current_user_dialogue.close_timer.start(5000)
            self.current_user_dialogue.raise_()
        log_event('dialogue.output_displayed', 'AI 답변 말풍선 표시', category='대화·AI',
                  trace_id=context['trace_id'], reason=reason, text=text)
        return True

    def is_conversation_busy(self, *, include_hold=True, include_manual=True):
        """Reserve the character for admitted user turns and their full output."""
        return bool(self._closed or self.is_ai_responding or self.pending_inputs
                    or self._speaking or self._tts_busy or self._pending_ai_response is not None
                    or (include_hold and self._time_provider() < self._response_hold_until)
                    or (include_manual and self.manual_dialogue_active))

    def show_automatic_response(self, text, expected_input_epoch=None, *, log_context=None, failed=False,
                                allow_during_hold=False):
        """Ambient responses never replace a conversation or a later user turn."""
        if self.is_conversation_busy(include_hold=not allow_during_hold):
            log_event('dialogue.automatic_discarded', '대화 우선으로 자동 대사 폐기', category='대화·AI',
                      trace_id=(log_context or {}).get('trace_id'), reason='conversation_busy', text=text)
            return False
        if expected_input_epoch is not None and expected_input_epoch != self.user_input_epoch:
            log_event('dialogue.automatic_discarded', '새 사용자 입력으로 자동 대사 폐기', category='대화·AI',
                      trace_id=(log_context or {}).get('trace_id'), reason='input_epoch_changed',
                      expected_input_epoch=expected_input_epoch, input_epoch=self.user_input_epoch,
                      text=text)
            return False
        self._response_hold_until = self._time_provider() + 5.0
        automatic = (log_context or {}).get('source') != 'manual_generation'
        self.show_ai_response(text, log_context=log_context, failed=failed, automatic=automatic)
        return True

    def show_ai_response(self, response_text: str, *, log_context=None, failed=False, automatic=False):
        """Display on the Qt thread and use the existing voice/enabled settings."""
        if self._closed:
            return
        context = dict(log_context or {})
        context.setdefault('trace_id', new_trace_id('output'))
        if automatic:
            context['chat_automatic'] = True
        self._pending_ai_response = (response_text, context, log_context is None)
        # Preserve failure status through normalization: friendly error notices
        # belong in the bubble, but must not be synthesized as character speech.
        if failed or self._is_error_response(response_text):
            self.ai_motion_changed.emit('error')
            self._flush_ai_response('ai_error')
            log_event('dialogue.tts_skipped', 'AI 오류 안내 음성 생략', category='대화·AI',
                      trace_id=context['trace_id'], reason='ai_error', text=response_text)
            return
        wait_for_audio = (getattr(self.tts, 'sync_bubble', False) is True
                          and getattr(self.tts, 'enabled', True) is not False)
        if not wait_for_audio:
            if self._flush_ai_response('immediate') is False:
                return
        log_event('dialogue.tts_requested', '대화 음성 출력 요청', category='대화·AI',
                  trace_id=context['trace_id'], text=response_text)
        # Only opt into an explicitly implemented API; Mock/dynamic providers keep speak(text).
        if callable(getattr(type(self.tts), 'speak_with_context', None)):
            self.tts.speak_with_context(response_text, context)
        else:
            self.tts.speak(response_text)
        # Disabled/empty speech can return without a busy-state transition.
        if self._pending_ai_response is not None and not self._tts_busy:
            self._flush_ai_response('tts_unavailable')

    def shutdown(self):
        """Stop UI work; a late network response cannot resurrect a closed app."""
        if self._closed:
            return
        self._closed = True
        self._pending_ai_response = None
        self._request_generation += 1
        self._input_timer.stop()
        for turn in self.pending_inputs:
            turn['state'] = 'cancelled'
            log_event('dialogue.turn_cancelled', '대기 대화 취소', category='대화·AI',
                      trace_id=turn.get('trace_id'), reason='shutdown', phase='queued', text=turn.get('text'))
        self.pending_inputs.clear()
        if self._active_input is not None:
            self._active_input['state'] = 'cancelled'
            log_event('dialogue.turn_cancelled', '처리 중 대화 취소', category='대화·AI',
                      trace_id=self._active_input.get('trace_id'), reason='shutdown', phase='processing',
                      text=self._active_input.get('text'))
        self._active_input = None
        self.is_ai_responding = False
        self.ai_motion_changed.emit('idle')
        self.clear_queue(reason='shutdown')
        self.close_current_dialogue(reason='shutdown')
        if self.current_input_widget:
            self.current_input_widget.close()
            self.current_input_widget = None
        self.tts.close()

    def _display_chat_message(self, turn):
        turn['displayed_at'] = QDateTime.currentDateTime()
        if self.current_input_widget is not None:
            self.current_input_widget.append_message(turn)

    def _speak_chat_message(self, text):
        if self._closed:
            return
        if not getattr(self.tts, 'enabled', True):
            QToolTip.showText(QCursor.pos(), '대화·음성 설정에서 AI 답변 음성으로 읽기를 켜 주세요.',
                              self.current_input_widget)
        elif self._pending_ai_response is not None:
            QToolTip.showText(QCursor.pos(), '새 답변이 표시된 뒤 다시 눌러 주세요.',
                              self.current_input_widget)
        else:
            self.tts.speak(text)

    def open_input_dialog(self):
        """Show the chat and keep the current draft and transcript."""
        if self._closed:
            return
        if self.current_input_widget is None:
            self.current_input_widget = DialogueInputWidget()
            self.current_input_widget.text_submitted.connect(self.ask_ai)
            self.current_input_widget.retry_requested.connect(self.retry_input)
            self.current_input_widget.cancel_requested.connect(self.cancel_input)
            self.current_input_widget.speech_requested.connect(self._speak_chat_message)
            for turn in self.conversation_history:
                if 'displayed_at' in turn:
                    self.current_input_widget.append_message(turn)

        input_widget = self.current_input_widget
        input_widget.showNormal()
        input_widget.raise_()
        input_widget.activateWindow()
        input_widget.input_field.setFocus()
    
    def _process_gemini_response(self, response: str, *, log_context=None) -> str:
        """Gemini 응답 처리 - 에러 또는 정상 응답을 대사로 변환"""
        context = dict(log_context or {})
        context.setdefault('trace_id', new_trace_id('normalize'))

        def normalized(text, mode, **details):
            log_event('dialogue.response_normalized', 'AI 응답을 최종 대사로 가공', category='대화·AI',
                      trace_id=context['trace_id'], raw_response=response,
                      final_text=text, mode=mode, **details)
            return text

        if not response:
            return normalized("뭔가 반응이 없네요... 😔", 'empty_fallback')

        if response == FLASH_LITE_QUOTAS_EXHAUSTED:
            return normalized('두 Flash Lite 모델의 오늘 요청 한도를 모두 사용했어요. 한도가 초기화되면 다시 보내 주세요.',
                              'error_fallback', status=429)

        # Numeric answers (e.g. 500원) are valid conversation, not HTTP errors.
        error = self._is_error_response(response)
        if error and ("429" in response or "Too Many Requests" in response):
            return normalized("너무 많은 요청이 들어왔어요. 잠시 후에 다시 말씀해주세요! 😅", 'error_fallback', status=429)
        elif error and ("401" in response or "Unauthorized" in response):
            return normalized("API 키가 잘못된 것 같아요... 설정을 확인해주시겠어요?", 'error_fallback', status=401)
        elif error and ("403" in response or "Forbidden" in response):
            return normalized("접근 권한이 없네요... 설정을 다시 확인해주세요.", 'error_fallback', status=403)
        elif error and ("503" in response or "Service Unavailable" in response):
            return normalized('지금 AI 서버가 붐비고 있어. 잠시 후 채팅창의 다시 보내기 버튼을 눌러줘.',
                              'error_fallback', status=503)
        elif error and ("500" in response or "502" in response or "504" in response or "Internal Server Error" in response):
            return normalized("AI 서버에 문제가 생겼어요... 잠시 후에 다시 시도해주세요.", 'error_fallback', status=500)
        elif error:
            # 일반적인 Gemini 에러
            return normalized(f"AI가 응답하는데 문제가 생겼어요. ({response[:20]}...)", 'error_fallback')
        else:
            # 정상 응답 - JSON 파싱 시도
            try:
                candidate = response.strip()
                # Only decode fenced JSON. Prose containing literal backticks is
                # returned intact if this candidate does not parse successfully.
                prefix = re.match(r'\A```(?:json)?[ \t]*(?:\r?\n|(?=[{\[]))',
                                  candidate, re.IGNORECASE)
                if prefix:
                    candidate = candidate[prefix.end():].strip()
                if candidate.startswith(('{', '[')):
                    candidate = re.sub(r'\s*```\s*\Z', '', candidate).strip()
                response_json = json.loads(candidate)
                if isinstance(response_json, dict):
                    # JSON 형식이면 'text' 또는 'response' 또는 'dialogue' 필드 찾기
                    text = response_json.get('text') or response_json.get('response') or response_json.get('dialogue')
                    if text:
                        field = next(key for key in ('text', 'response', 'dialogue') if response_json.get(key))
                        return normalized(str(text), 'json_field', selected_field=field, fenced=bool(prefix))
                    else:
                        return normalized(str(response_json), 'json_without_dialogue_field', fenced=bool(prefix))
                else:
                    return normalized(str(response_json), 'json_value', fenced=bool(prefix))
            except (json.JSONDecodeError, ValueError) as exc:
                # JSON이 아니면 그대로 사용
                return normalized(response, 'raw_text', parse_error=str(exc))
    

class QuickDialoguePresets:
    
    # # 인사말
    # GREETING = "안녕하세요!"
    # GREETING_MORNING = "좋은 아침입니다!"
    # GREETING_AFTERNOON = "좋은 오후입니다!"
    # GREETING_EVENING = "좋은 저녁입니다!"
    
    # # 반응
    # ACKNOWLEDGE = "네, 확인했습니다!"
    # BUSY = "지금 바쁜 것 같은데요?"
    # IDLE = "한 일이 없으시네요!"
    
    # # 게임 감지
    # GAME_DETECTED = "게임을 하고 계시네요!"
    # GAME_FOCUSED = "게임에 집중하시는 군요!"
    
    # # 웹 감지
    # WEB_DETECTED = "인터넷을 보고 계시네요!"
    
    # # 작업 감지
    # WORKING = "열심히 일하시는군요!"
    # CODING = "코딩 중이신가요?"
    
    @staticmethod
    def get_greeting():
        """시간대별 인사말 반환"""
        from datetime import datetime
        hour = datetime.now().hour
        
        if 5 <= hour < 12:
            return QuickDialoguePresets.GREETING_MORNING
        elif 12 <= hour < 18:
            return QuickDialoguePresets.GREETING_AFTERNOON
        else:
            return QuickDialoguePresets.GREETING_EVENING
