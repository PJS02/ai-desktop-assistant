# 캐릭터 대화 시스템
from PyQt6.QtCore import QTimer, pyqtSignal, QObject, QThread
from .dialogue_widget import DialogueBubble, DialogueNarrationBox, DialogueInputWidget
from typing import Optional, List
import threading
import json


class DialogueSystem(QObject):
    """캐릭터 대화 관리 시스템"""
    
    dialogue_started = pyqtSignal(str)  # 대화 시작
    dialogue_ended = pyqtSignal()       # 대화 종료
    
    def __init__(self, character_widget):
        """
        Args:
            character_widget: CharacterWidget 인스턴스
        """
        super().__init__()
        
        self.character_widget = character_widget
        self.current_dialogue: Optional[DialogueBubble] = None
        self.current_narration: Optional[DialogueNarrationBox] = None
        self.current_input_widget: Optional[DialogueInputWidget] = None
        
        # 대화 큐
        self.dialogue_queue: List[dict] = []
        self.is_processing_queue = False
        
        # 큐 처리 타이머
        self.queue_timer = QTimer()
        self.queue_timer.timeout.connect(self._process_next_dialogue)
        
        # Gemini 설정
        self.gemini_config = {}
        self._load_gemini_config()
        
        # 요청 제한 (수동 대화용)
        self.last_request_time = 0  # 마지막 수동 요청 시간
        self.request_cooldown = 10  # 수동 요청 사이 최소 10초 (자동 감지와 분리)
        self.is_ai_responding = False  # AI 응답 중인지
    
    def _load_gemini_config(self):
        """Gemini 설정 파일 로드"""
        from pathlib import Path
        try:
            config_path = Path(__file__).resolve().parent.parent / "context" / "gemini_config.json"
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    self.gemini_config = json.load(f)
                print("[대화 시스템] Gemini 설정 로드 완료")
        except Exception as e:
            print(f"[경고] Gemini 설정 로드 실패: {e}")
    
    def show_dialogue(self, text: str, duration: int = 5000, 
                     use_narration: bool = False, character_name: str = "어시스턴트"):
        """
        대화 표시
        
        Args:
            text: 대화 텍스트
            duration: 표시 시간 (밀리초)
            use_narration: True면 하단 나레이션 박스 사용, False면 말풍선 사용
            character_name: 캐릭터 이름 (나레이션 사용 시)
        """
        if use_narration:
            self._show_narration(text, character_name, duration)
        else:
            self._show_bubble(text, duration)
    
    def _show_bubble(self, text: str, duration: int):
        """말풍선 대화 표시"""
        # 이전 말풍선 종료
        if self.current_dialogue:
            self.current_dialogue.close()
        
        # 새 말풍선 생성
        bubble = DialogueBubble(text, duration)
        bubble.dialogue_closed.connect(self._on_dialogue_closed)
        
        # 캐릭터 위에 배치
        char_x = self.character_widget.x()
        char_y = self.character_widget.y()
        char_width = self.character_widget.width()
        
        bubble.set_position_below_character(char_x, char_y, char_width)
        bubble.show()
        
        self.current_dialogue = bubble
        self.dialogue_started.emit(text)
    
    def _show_narration(self, text: str, character_name: str, duration: int):
        """하단 나레이션 박스 표시"""
        # 이전 나레이션 종료
        if self.current_narration:
            self.current_narration.close()
        
        # 새 나레이션 생성
        narration = DialogueNarrationBox(text, character_name, duration)
        narration.closed.connect(self._on_narration_closed)
        narration.show()
        
        self.current_narration = narration
        self.dialogue_started.emit(text)
    
    def queue_dialogue(self, text: str, duration: int = 5000,
                       use_narration: bool = False, 
                       character_name: str = "어시스턴트",
                       delay_ms: int = 0):
        """
        대화를 큐에 추가 (순차적 표시)
        
        Args:
            text: 대화 텍스트
            duration: 표시 시간
            use_narration: 나레이션 박스 사용 여부
            character_name: 캐릭터 이름
            delay_ms: 표시 전 지연시간
        """
        self.dialogue_queue.append({
            'text': text,
            'duration': duration,
            'use_narration': use_narration,
            'character_name': character_name,
            'delay': delay_ms
        })
        
        # 큐 처리 시작 (아직 진행 중이 아니면)
        if not self.is_processing_queue:
            self._process_next_dialogue()
    
    def _process_next_dialogue(self):
        """큐에서 다음 대화 처리"""
        self.queue_timer.stop()
        
        if not self.dialogue_queue:
            self.is_processing_queue = False
            self.dialogue_ended.emit()
            return
        
        self.is_processing_queue = True
        
        # 첫 번째 항목 추출
        dialogue_item = self.dialogue_queue.pop(0)
        
        # 지연시간이 있으면 타이머 설정
        if dialogue_item['delay'] > 0:
            self.queue_timer.setSingleShot(True)
            self.queue_timer.timeout.connect(
                lambda: self._show_dialogue_from_queue(dialogue_item)
            )
            self.queue_timer.start(dialogue_item['delay'])
        else:
            self._show_dialogue_from_queue(dialogue_item)
    
    def _show_dialogue_from_queue(self, dialogue_item: dict):
        """큐 항목에서 대화 표시"""
        self.show_dialogue(
            text=dialogue_item['text'],
            duration=dialogue_item['duration'],
            use_narration=dialogue_item['use_narration'],
            character_name=dialogue_item['character_name']
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
    
    def clear_queue(self):
        """대화 큐 비우기"""
        self.dialogue_queue.clear()
        self.queue_timer.stop()
        self.is_processing_queue = False
    
    def close_current_dialogue(self):
        """현재 표시 중인 대화 종료"""
        if self.current_dialogue:
            self.current_dialogue.close()
        if self.current_narration:
            self.current_narration.close()
    
    def update_dialogue_position(self):
        """캐릭터 위치 변화에 따라 현재 대화의 위치 업데이트"""
        if self.current_dialogue:
            self.current_dialogue.update_position_with_character(
                self.character_widget.x(),
                self.character_widget.y(),
                self.character_widget.width()
            )
    
    def is_dialogue_active(self) -> bool:
        """현재 대화 표시 중인지 확인"""
        return (self.current_dialogue is not None or 
                self.current_narration is not None or
                len(self.dialogue_queue) > 0)
    # ===== AI 대화 시스템 ======
    
    def ask_ai(self, user_input: str):
        """
        사용자 입력을 AI에 보내고 응답 받기 (비동기, 요청 제한 포함 - 수동 대화)
        
        Args:
            user_input: 사용자 입력 텍스트
        """
        import time
        
        # 이전 응답 중인지 확인
        if self.is_ai_responding:
            self.show_dialogue("AI가 아직 생각 중입니다... 잠시만 기다려주세요.", duration=3000)
            return
        
        # 요청 제한 확인 (쿨다운) - 수동 대화용으로 자동 감지와 분리됨
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time
        
        if time_since_last_request < self.request_cooldown:
            remaining = int(self.request_cooldown - time_since_last_request)
            self.show_dialogue(f"조금만 기다려주세요... ({remaining}초)", duration=3000)
            return
        
        # 사용자 대화를 먼저 표시
        self.show_dialogue(f"[사용자]: {user_input}", duration=3000)
        
        # AI 응답을 별도 스레드에서 받기
        self.is_ai_responding = True
        self.last_request_time = time.time()
        
        def get_ai_response():
            try:
                from context.active_window_classifier import call_gemini
                
                if not self.gemini_config:
                    self._load_gemini_config()
                
                # AI에 질문 보내기
                prompt = f"사용자가 말했습니다: {user_input}\n\n이 사용자에게 친절하고 간단하게 응답해주세요. 응답은 한두 문장으로 간단하게 해주세요."
                print(f"[API 요청] Gemini 호출 중... (수동 대화)")
                response = call_gemini(prompt, self.gemini_config)
                print(f"[응답] {response[:100] if response else '(없음)'}")
                
                # 에러 처리 및 응답 변환
                response_text = self._process_gemini_response(response)
                
                # 응답 표시 (메인 스레드에서 실행되도록 신호 사용)
                self.character_widget.show_ai_response.emit(response_text)
                
            except Exception as e:
                error_msg = f"AI 응답 오류: {str(e)}"
                print(f"[오류] {error_msg}")
                self.character_widget.show_ai_response.emit("미안해요, 지금은 대답할 수 없어요... 😔")
            finally:
                self.is_ai_responding = False
        
        # 스레드에서 실행
        thread = threading.Thread(target=get_ai_response, daemon=True)
        thread.start()
    
    def show_ai_response(self, response_text: str):
        """AI 응답 표시"""
        self.show_dialogue(response_text, duration=5000)
    
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
    
    def _process_gemini_response(self, response: str) -> str:
        """Gemini 응답 처리 - 에러 또는 정상 응답을 대사로 변환"""
        if not response:
            return "뭔가 반응이 없네요... 😔"
        
        # 에러 감지 및 변환
        if "429" in response or "Too Many Requests" in response:
            return "너무 많은 요청이 들어왔어요. 잠시 후에 다시 말씀해주세요! 😅"
        elif "401" in response or "Unauthorized" in response:
            return "API 키가 잘못된 것 같아요... 설정을 확인해주시겠어요?"
        elif "403" in response or "Forbidden" in response:
            return "접근 권한이 없네요... 설정을 다시 확인해주세요."
        elif "500" in response or "Internal Server Error" in response:
            return "AI 서버에 문제가 생겼어요... 잠시 후에 다시 시도해주세요."
        elif "[gemini error]" in response.lower():
            # 일반적인 Gemini 에러
            return f"AI가 응답하는데 문제가 생겼어요. ({response[:20]}...)"
        else:
            # 정상 응답 - JSON 파싱 시도
            try:
                response_json = json.loads(response)
                if isinstance(response_json, dict):
                    # JSON 형식이면 'text' 또는 'response' 또는 'dialogue' 필드 찾기
                    text = response_json.get('text') or response_json.get('response') or response_json.get('dialogue')
                    if text:
                        return text
                    else:
                        return str(response_json)
                else:
                    return str(response_json)
            except (json.JSONDecodeError, ValueError):
                # JSON이 아니면 그대로 사용
                return response


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
