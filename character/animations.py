import math
from PyQt6.QtCore import QTimer, pyqtSignal, QObject, QPoint

class IdleAnimator(QObject):
    """가만히 있을 때 자연스러운 호흡/좌우 흔들림"""
    
    position_changed = pyqtSignal(QPoint)  # 새로운 위치
    
    def __init__(self, base_pos):
        super().__init__()
        self.base_pos = base_pos
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_animation)
        self.elapsed_time = 0
        self.is_active = False
        
    def start(self):
        """애니메이션 시작"""
        self.is_active = True
        self.timer.start(16)  # 60fps
        
    def stop(self):
        """애니메이션 중지"""
        self.is_active = False
        self.timer.stop()
        self.elapsed_time = 0
        
    def update_animation(self):
        """매 프레임마다 위치 업데이트"""
        self.elapsed_time += 0.016
        
        # 호흡 효과 (위아래)
        y_offset = math.sin(self.elapsed_time * 2) * 5
        
        # 좌우 흔들림
        x_offset = math.cos(self.elapsed_time * 1.5) * 3
        
        new_pos = self.base_pos + QPoint(int(x_offset), int(y_offset))
        self.position_changed.emit(new_pos)
    
    def set_base_pos(self, base_pos):
        """기본 위치 업데이트"""
        self.base_pos = base_pos


class BounceAnimator(QObject):
    """클릭할 때 탄력 있게 점프"""
    
    position_changed = pyqtSignal(QPoint)  # 새로운 위치
    finished = pyqtSignal()  # 애니메이션 종료
    
    def __init__(self, base_pos):
        super().__init__()
        self.base_pos = base_pos
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_bounce)
        self.progress = 0
        
    def start(self):
        """바운스 시작"""
        self.progress = 0
        self.timer.start(10)
        
    def update_bounce(self):
        """바운스 애니메이션 업데이트"""
        self.progress += 0.02
        
        if self.progress >= 1.0:
            self.timer.stop()
            # 최종 위치 = 기본 위치
            self.position_changed.emit(self.base_pos)
            self.finished.emit()
            return
        
        # 탄력 효과 계산
        if self.progress < 0.5:
            offset = 50 * math.sin(self.progress * math.pi)
        else:
            offset = 10 * math.sin((1 - self.progress) * math.pi)
        
        # 위로 점프 (음수)
        new_pos = self.base_pos + QPoint(0, -int(offset))
        self.position_changed.emit(new_pos)
    
    def set_base_pos(self, base_pos):
        """기본 위치 업데이트"""
        self.base_pos = base_pos


class AnimationController(QObject):
    """모든 애니메이션을 관리하는 컨트롤러"""
    
    position_changed = pyqtSignal(QPoint)  # 최종 위치
    
    def __init__(self, initial_pos):
        super().__init__()
        self.current_pos = initial_pos
        
        self.idle = IdleAnimator(initial_pos)
        self.idle.position_changed.connect(self.on_position_changed)
        
        self.bounce = BounceAnimator(initial_pos)
        self.bounce.position_changed.connect(self.on_position_changed)
        self.bounce.finished.connect(self.on_bounce_finished)
        
        self.is_idle_active = False
    
    def start_idle(self):
        """아이들 애니메이션 시작"""
        self.bounce.timer.stop()
        self.idle.start()
        self.is_idle_active = True
    
    def start_bounce(self):
        """바운스 애니메이션 시작 (아이들 중지)"""
        self.idle.stop()
        self.bounce.start()
        self.is_idle_active = False
    
    def on_position_changed(self, new_pos):
        """애니메이션에서 위치 변경 신호 받음"""
        self.current_pos = new_pos
        self.position_changed.emit(new_pos)
    
    def on_bounce_finished(self):
        """바운스 끝나면 다시 아이들 시작"""
        self.start_idle()
    
    def update_base_pos(self, base_pos):
        """기본 위치 업데이트 (캐릭터 이동 후)"""
        self.idle.set_base_pos(base_pos)
        self.bounce.set_base_pos(base_pos)
        self.current_pos = base_pos
    
    def stop(self):
        """모든 애니메이션 중지"""
        self.idle.stop()
        self.bounce.timer.stop()