# 캐릭터 대화 시스템
from PyQt6.QtCore import QTimer, pyqtSignal, pyqtSlot, QObject, Qt
from .dialogue_widget import DialogueBubble, DialogueNarrationBox, DialogueInputWidget
from .tts_service import SupertonicTTS
from .config_manager import load_dialogue_style
from .dialogue_styles import normalize_dialogue_style
from PyQt6.QtCore import QRect
from typing import Optional, List
import threading
import json
import math
import time
import re
from collections import deque
from app_logging import log_event, new_trace_id, register_secret


class DialogueSystem(QObject):
    """캐릭터 대화 관리 시스템"""
    
    dialogue_started = pyqtSignal(str)  # 대화 시작
    dialogue_ended = pyqtSignal()       # 대화 종료
    user_input_received = pyqtSignal(str, str)  # text, text/voice
    ai_response_ready = pyqtSignal(object)
    
    def __init__(self, character_widget, *, tts=None, response_provider=None,
                 time_provider=time.monotonic):
        """
        Args:
            character_widget: CharacterWidget 인스턴스
        """
        super().__init__()
        
        self.character_widget = character_widget
        self.current_dialogue: Optional[DialogueBubble] = None
        self.current_narration: Optional[DialogueNarrationBox] = None
        self.current_input_widget: Optional[DialogueInputWidget] = None
        self.tts = tts if tts is not None else SupertonicTTS()
        self.bubble_style = load_dialogue_style()
        self._response_provider = response_provider
        self._time_provider = time_provider
        self._closed = False
        self._request_generation = 0
        self._active_input = None
        self._last_failed_input = None
        self.user_input_epoch = 0
        self.pending_inputs = deque()
        self.conversation_history = []
        self._speaking = False
        self._tts_busy = False
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
        self.request_cooldown = 10  # 수동 요청 사이 최소 10초 (자동 감지와 분리)
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
    
    def _show_bubble(self, text: str, duration: int, *, log_context=None):
        """말풍선 대화 표시"""
        # 이전 말풍선 종료
        if self.current_dialogue:
            previous, self.current_dialogue = self.current_dialogue, None
            log_event('dialogue.widget_replaced', '이전 말풍선 교체', category='대화·AI',
                      trace_id=getattr(previous, '_log_context', {}).get('trace_id'),
                      replacement_trace_id=(log_context or {}).get('trace_id'),
                      previous_text=previous.text, text=text, display_type='bubble')
            previous._log_close_reason = 'replaced'
            previous.close()
        
        # 새 말풍선 생성
        bubble = DialogueBubble(text, duration, style=self.bubble_style)
        bubble._log_context = dict(log_context or {})
        bubble.dialogue_closed.connect(lambda: self._on_bubble_closed(bubble))
        
        self.current_dialogue = bubble
        self.update_dialogue_position()
        bubble.show()
        log_event('dialogue.widget_shown', '말풍선 위젯 표시', category='대화·AI',
                  trace_id=bubble._log_context.get('trace_id'), text=text,
                  display_type='bubble', visible=bubble.isVisible(), duration_ms=duration)
        
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
                      display_type='bubble')
        if self.current_dialogue is bubble:
            self._on_dialogue_closed()
        bubble.deleteLater()
    
    def _show_narration(self, text: str, character_name: str, duration: int, *, log_context=None):
        """하단 나레이션 박스 표시"""
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
        if self.current_dialogue:
            self.current_dialogue._log_close_reason = reason
            self.current_dialogue.close()
        if self.current_narration:
            self.current_narration._log_close_reason = reason
            self.current_narration.close()
    
    def update_dialogue_position(self):
        """캐릭터 위치 변화에 따라 현재 대화의 위치 업데이트"""
        if self.current_dialogue:
            host = self.character_widget
            measure = getattr(host, '_physics_body_rect', None)
            body = measure() if measure else QRect(0, 0, host.width(), host.height())
            game = getattr(host, 'rps_game', None)
            avoid = game.geometry() if game is not None and game.isVisible() else None
            self.current_dialogue.update_position_with_character(
                host.x() + body.x(), host.y() + body.y(), body.width(), body.height(), avoid)
    
    def is_dialogue_active(self) -> bool:
        """현재 대화 표시 중인지 확인"""
        return (self.current_dialogue is not None or 
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

    def _submit_input(self, text: str, source: str, *, log_context=None, retry_of=None) -> bool:
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
        self.user_input_epoch += 1
        # A direct user turn takes priority over a delayed ambient script.
        self.clear_queue(reason='user_input_priority')
        turn = {'role': 'user', 'text': text, 'source': source,
                'state': 'queued', 'turn_id': len(self.conversation_history),
                'trace_id': trace_id, 'log_context': {**context, 'trace_id': trace_id, 'source': source},
                'queued_at': self._time_provider(), 'retry_of': retry_of}
        self.conversation_history.append(turn)
        self.pending_inputs.append(turn)
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
        turn['state'] = 'responding'
        self.is_ai_responding = True
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
        self.show_dialogue(f"[사용자]: {turn['text']}", duration=3000, log_context=context)
        try:
            if not self.gemini_config:
                self._load_gemini_config()
            # Read character state and configuration on the Qt thread; workers only
            # receive plain snapshots and never touch character/UI objects.
            prompt = self._build_user_prompt(turn['text'])
            config = dict(self.gemini_config)
            register_secret(config.get('api_key', ''))
            completed = sorted(
                (item for item in self.conversation_history if item['state'] == 'completed'),
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
            try:
                raw_response = self._call_ai(prompt, config, log_context=context)
                failed = self._is_error_response(raw_response)
                log_event('dialogue.model_text_received', '대화 모델 텍스트 전체', category='대화·AI',
                          level='ERROR' if failed else 'INFO', trace_id=turn['trace_id'],
                          raw_response=raw_response, failed=failed)
                response_text = self._process_gemini_response(raw_response, log_context=context)
            except Exception as exc:
                log_event('dialogue.response_failed', '대화 AI 응답 처리 실패', category='대화·AI',
                          level='ERROR', trace_id=turn['trace_id'], error=str(exc))
                failed = True
                response_text = "미안해요, 지금은 대화할 수 없어요. 다시 시도해 주세요."
            if not self._closed:
                self.ai_response_ready.emit((generation, response_text, failed))
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
        completed = sorted(
            (item for item in self.conversation_history if item['state'] == 'completed'),
            key=lambda item: (item['turn_id'], item['role'] != 'user'))
        previous = [f"{'사용자' if item['role'] == 'user' else '캐릭터'}: {item['text']}"
                    for item in completed][-12:]
        history = '\n'.join(previous) or '(이전 대화 없음)'
        return f"""당신은 사용자의 데스크톱 어시스턴트 AI 캐릭터입니다.

캐릭터 성격 (Big Five):
{personality.get_personality_for_prompt()}
성격 지침:
{personality.get_dialogue_tone_hints()}
현재 감정 상태:
{mood.get_emotion_description_for_prompt()}
감정별 말투 지침:
{mood.get_emotion_tone_instructions()}

이전 대화:
{history}
사용자 입력:
{user_input}

지침을 따르면서 사용자에게 자연스럽고 친근한 대답을 해주세요.
응답은 한두 문장으로 간단하게 해주세요."""

    def _call_ai(self, prompt, config, *, log_context=None):
        if self._response_provider is not None:
            log_event('dialogue.provider_called', '사용자 정의 응답 제공자 호출', category='대화·AI',
                      trace_id=(log_context or {}).get('trace_id'), model=config.get('model'))
            return self._response_provider(prompt, config)
        from context.active_window_classifier import call_gemini
        return call_gemini(prompt, config, log_context=log_context)

    @staticmethod
    def _is_error_response(response):
        if not response:
            return True
        text = str(response).lower()
        return text.startswith('[gemini error]') or text.startswith(
            ('http error ', 'error: ', 'error ')) and any(
                marker in text for marker in ('429', '401', '403', '500',
                    'too many requests', 'unauthorized', 'forbidden', 'internal server error'))

    @pyqtSlot(object)
    def _finish_ai_request(self, result):
        generation, response_text, failed = result
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
        turn['state'] = 'failed' if failed else 'completed'
        self._last_failed_input = dict(turn) if failed else None
        self.conversation_history.append({
            'role': 'assistant', 'text': response_text,
            'source': turn['source'], 'state': turn['state'],
            'turn_id': turn['turn_id'], 'trace_id': turn['trace_id']})
        log_event('dialogue.turn_failed' if failed else 'dialogue.turn_completed',
                  '대화 요청 실패' if failed else '대화 요청 완료', category='대화·AI',
                  level='ERROR' if failed else 'INFO', trace_id=turn['trace_id'],
                  turn_id=turn['turn_id'], response=response_text, state=turn['state'],
                  elapsed_seconds=round(self._time_provider() - turn['started_at'], 3))
        self._active_input = None
        self.is_ai_responding = False
        self._response_hold_until = self._time_provider() + 5.0
        self.show_ai_response(response_text, log_context=turn['log_context'])
        self._process_next_input()

    def retry_last_input(self):
        """A failed user turn remains in history and can be resubmitted explicitly."""
        if self._last_failed_input is None or self._closed:
            return False
        previous = self._last_failed_input
        self._last_failed_input = None
        log_event('dialogue.retry_requested', '실패한 대화 재시도 요청', category='대화·AI',
                  trace_id=previous['trace_id'], turn_id=previous['turn_id'])
        return self._submit_input(previous['text'], previous['source'],
                                  retry_of=previous['trace_id'])

    def _on_tts_speaking_changed(self, speaking):
        self._speaking = bool(speaking)
        if not self._speaking:
            self._process_next_input()

    def _on_tts_busy_changed(self, busy):
        self._tts_busy = bool(busy)
        if not self._tts_busy:
            self._process_next_input()

    def is_conversation_busy(self):
        """Reserve the character for admitted user turns and their full output."""
        return bool(self._closed or self.is_ai_responding or self.pending_inputs
                    or self._speaking or self._tts_busy
                    or self._time_provider() < self._response_hold_until)

    def show_automatic_response(self, text, expected_input_epoch=None, *, log_context=None):
        """Ambient responses never replace a conversation or a later user turn."""
        if self.is_conversation_busy():
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
        self.show_ai_response(text, log_context=log_context)
        return True

    def show_ai_response(self, response_text: str, *, log_context=None):
        """Display on the Qt thread and use the existing voice/enabled settings."""
        if self._closed:
            return
        context = dict(log_context or {})
        context.setdefault('trace_id', new_trace_id('output'))
        if log_context is None and getattr(self.show_dialogue, '__func__', None) is not DialogueSystem.show_dialogue:
            self.show_dialogue(response_text, duration=5000)
        else:
            self.show_dialogue(response_text, duration=5000, log_context=context)
        log_event('dialogue.tts_requested', '대화 음성 출력 요청', category='대화·AI',
                  trace_id=context['trace_id'], text=response_text)
        # Only opt into an explicitly implemented API; Mock/dynamic providers keep speak(text).
        if callable(getattr(type(self.tts), 'speak_with_context', None)):
            self.tts.speak_with_context(response_text, context)
        else:
            self.tts.speak(response_text)

    def shutdown(self):
        """Stop UI work; a late network response cannot resurrect a closed app."""
        if self._closed:
            return
        self._closed = True
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
        self.clear_queue(reason='shutdown')
        self.close_current_dialogue(reason='shutdown')
        if self.current_input_widget:
            self.current_input_widget.close()
            self.current_input_widget = None
        self.tts.close()

    def open_input_dialog(self):
        """대화 입력 창 열기"""
        # 이전 입력창이 있으면 닫기
        if self.current_input_widget:
            self.current_input_widget.close()
        
        # 새 입력창 생성
        input_widget = DialogueInputWidget()
        input_widget.text_submitted.connect(self.ask_ai)
        
        # 캐릭터 아래에 배치
        char_x = self.character_widget.x()
        char_y = self.character_widget.y()
        char_width = self.character_widget.width()
        input_widget.set_position_below_character(char_x, char_y, char_width)
        
        input_widget.show()
        self.current_input_widget = input_widget
    
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
        
        # Numeric answers (e.g. 500원) are valid conversation, not HTTP errors.
        error = self._is_error_response(response)
        if error and ("429" in response or "Too Many Requests" in response):
            return normalized("너무 많은 요청이 들어왔어요. 잠시 후에 다시 말씀해주세요! 😅", 'error_fallback', status=429)
        elif error and ("401" in response or "Unauthorized" in response):
            return normalized("API 키가 잘못된 것 같아요... 설정을 확인해주시겠어요?", 'error_fallback', status=401)
        elif error and ("403" in response or "Forbidden" in response):
            return normalized("접근 권한이 없네요... 설정을 다시 확인해주세요.", 'error_fallback', status=403)
        elif error and ("500" in response or "Internal Server Error" in response):
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
