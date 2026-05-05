"""
스프라이트 시트 애니메이션 관리
idle/, angry/, walk/ 폴더의 프레임 이미지들을 순서대로 재생
"""
import glob
from pathlib import Path
from PyQt6.QtCore import QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QPixmap


class SpriteAnimator(QObject):
    """프레임 기반 스프라이트 애니메이션"""
    
    frame_changed = pyqtSignal(QPixmap)  # 새 프레임
    animation_finished = pyqtSignal()  # 애니메이션 종료
    
    def __init__(self, assets_path):
        super().__init__()
        self.assets_path = Path(assets_path)
        self.current_frames = []
        self.current_frame = 0
        self.is_looping = True
        self.is_playing = False
        
        self.timer = QTimer()
        self.timer.timeout.connect(self.next_frame)
        
    def load_animation(self, animation_name):
        """
        애니메이션 폴더에서 모든 프레임 로드 (프레임_000.png 형식)
        예: assets/idle/frame_000.png, frame_001.png, ...
        """
        animation_dir = self.assets_path / animation_name
        
        if not animation_dir.exists():
            print(f"[경고] 애니메이션 폴더 없음: {animation_dir}")
            return False
        
        # frame_000.png, frame_001.png 등을 정렬 순서대로 로드
        frame_files = sorted(animation_dir.glob("frame_*.png"))
        
        if not frame_files:
            print(f"[경고] 프레임 파일 없음: {animation_dir}")
            return False
        
        self.current_frames = [QPixmap(str(f)) for f in frame_files]
        self.current_frame = 0
        
        print(f"[로드됨] {animation_name}: {len(self.current_frames)}개 프레임")
        return True
    
    def play(self, animation_name, fps=10, loop=True):
        """
        애니메이션 재생
        
        Args:
            animation_name: 폴더명 (idle, angry, walk 등)
            fps: 초당 프레임 수 (기본값 10fps)
            loop: 반복 재생 여부
        """
        if not self.load_animation(animation_name):
            return
        
        self.is_looping = loop
        self.current_frame = 0
        self.is_playing = True
        
        # 첫 번째 프레임 표시
        if self.current_frames:
            self.frame_changed.emit(self.current_frames[0])
        
        # 타이머 시작 (fps 기반 interval)
        interval = max(1, 1000 // fps)  # 최소 1ms
        self.timer.start(interval)
    
    def stop(self):
        """애니메이션 중지"""
        self.timer.stop()
        self.is_playing = False
        self.current_frame = 0
    
    def pause(self):
        """애니메이션 일시 정지"""
        self.timer.stop()
    
    def resume(self):
        """애니메이션 재개"""
        if self.is_playing:
            self.timer.start()
    
    def next_frame(self):
        """다음 프레임으로 이동"""
        if not self.current_frames:
            return
        
        # 현재 프레임 표시
        self.frame_changed.emit(self.current_frames[self.current_frame])
        
        # 다음 프레임 준비
        self.current_frame += 1
        
        if self.current_frame >= len(self.current_frames):
            if self.is_looping:
                self.current_frame = 0
            else:
                # 반복 안 하면 마지막 프레임에서 멈추고 종료 신호
                self.timer.stop()
                self.is_playing = False
                self.current_frame = len(self.current_frames) - 1
                self.animation_finished.emit()
