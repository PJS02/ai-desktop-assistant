# 해상도 및 성격 설정 다이얼로그
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
    QLabel, QSpinBox, QComboBox, QGroupBox, QTabWidget, QWidget
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont


class ResolutionSettingsDialog(QDialog):
    """해상도 및 성격 설정 다이얼로그"""
    
    # 미리 정의된 해상도 프리셋
    PRESETS = {
        "1440p (2560x1440)": (2560, 1440),
        "1080p (1920x1080)": (1920, 1080),
        "720p (1280x720)": (1280, 720),
        "사용자 정의": None  # 커스텀
    }
    
    resolution_selected = pyqtSignal(int, int)  # width, height 신호
    personality_selected = pyqtSignal(str)      # 성격 프리셋 이름 신호
    
    def __init__(self, current_width=None, current_height=None, current_personality=None):
        super().__init__()
        self.selected_width = current_width or 1920
        self.selected_height = current_height or 1080
        self.selected_personality = current_personality or "Russell (기본)"
        self.setup_ui()
    
    def setup_ui(self):
        """UI 설정"""
        self.setWindowTitle("캐릭터 설정")
        self.setModal(True)
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)
        
        # 탭 위젯 생성
        tab_widget = QTabWidget()
        
        # 탭 1: 해상도 설정
        resolution_tab = QWidget()
        resolution_layout = self._create_resolution_tab_layout()
        resolution_tab.setLayout(resolution_layout)
        tab_widget.addTab(resolution_tab, "해상도")
        
        # 탭 2: 성격 설정
        personality_tab = QWidget()
        personality_layout = self._create_personality_tab_layout()
        personality_tab.setLayout(personality_layout)
        tab_widget.addTab(personality_tab, "성격")
        
        # 메인 레이아웃
        layout = QVBoxLayout()
        layout.addWidget(tab_widget)
        
        # ========== 버튼 ==========
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        confirm_btn = QPushButton("확인")
        confirm_btn.clicked.connect(self.confirm)
        button_layout.addWidget(confirm_btn)
        
        cancel_btn = QPushButton("취소")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
        
        # 초기 설정
        self.update_from_current_resolution()
    
    def _create_resolution_tab_layout(self) -> QVBoxLayout:
        """해상도 설정 탭 레이아웃 생성"""
        layout = QVBoxLayout()
        
        # 타이틀
        title = QLabel("캐릭터 활동 범위 설정")
        title_font = QFont()
        title_font.setPointSize(11)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)
        
        # 설명
        desc = QLabel("캐릭터와 배경이 표시될 화면 범위를 선택하세요:")
        layout.addWidget(desc)
        
        # ========== 프리셋 선택 그룹 ==========
        preset_group = QGroupBox("미리 정의된 해상도")
        preset_layout = QVBoxLayout()
        
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(self.PRESETS.keys())
        self.preset_combo.currentTextChanged.connect(self.on_preset_changed)
        preset_layout.addWidget(QLabel("프리셋:"))
        preset_layout.addWidget(self.preset_combo)
        
        preset_group.setLayout(preset_layout)
        layout.addWidget(preset_group)
        
        # ========== 커스텀 설정 그룹 ==========
        custom_group = QGroupBox("사용자 정의 해상도")
        custom_layout = QVBoxLayout()
        
        # 너비
        width_layout = QHBoxLayout()
        width_layout.addWidget(QLabel("너비 (px):"))
        self.width_spinbox = QSpinBox()
        self.width_spinbox.setMinimum(640)
        self.width_spinbox.setMaximum(7680)
        self.width_spinbox.setValue(self.selected_width)
        self.width_spinbox.setSingleStep(10)
        width_layout.addWidget(self.width_spinbox)
        width_layout.addStretch()
        custom_layout.addLayout(width_layout)
        
        # 높이
        height_layout = QHBoxLayout()
        height_layout.addWidget(QLabel("높이 (px):"))
        self.height_spinbox = QSpinBox()
        self.height_spinbox.setMinimum(480)
        self.height_spinbox.setMaximum(4320)
        self.height_spinbox.setValue(self.selected_height)
        self.height_spinbox.setSingleStep(10)
        height_layout.addWidget(self.height_spinbox)
        height_layout.addStretch()
        custom_layout.addLayout(height_layout)
        
        custom_group.setLayout(custom_layout)
        layout.addWidget(custom_group)
        
        # 스핀박스 변경 감지
        self.width_spinbox.valueChanged.connect(self.update_preview)
        self.height_spinbox.valueChanged.connect(self.update_preview)
        
        # ========== 미리보기 ==========
        self.preview_label = QLabel(f"선택: {self.selected_width} × {self.selected_height}px")
        preview_font = QFont()
        preview_font.setPointSize(10)
        self.preview_label.setFont(preview_font)
        self.preview_label.setStyleSheet("color: #0078d4; font-weight: bold;")
        layout.addWidget(self.preview_label)
        
        layout.addStretch()
        return layout
    
    def _create_personality_tab_layout(self) -> QVBoxLayout:
        """성격 설정 탭 레이아웃 생성"""
        layout = QVBoxLayout()
        
        # 타이틀
        title = QLabel("캐릭터 성격 선택")
        title_font = QFont()
        title_font.setPointSize(11)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)
        
        # 설명
        desc = QLabel("Russell의 Big Five 성격 중 하나를 선택하세요:")
        layout.addWidget(desc)
        
        # 성격 프리셋 (personality_system.py에서 가져올 것)
        from character.personality_system import PersonalitySystem
        
        preset_group = QGroupBox("성격 프리셋")
        preset_layout = QVBoxLayout()
        
        self.personality_combo = QComboBox()
        personality_names = list(PersonalitySystem.PERSONALITY_PRESETS.keys())
        self.personality_combo.addItems(personality_names)
        self.personality_combo.setCurrentText(self.selected_personality)
        self.personality_combo.currentTextChanged.connect(self.on_personality_changed)
        
        preset_layout.addWidget(QLabel("프리셋:"))
        preset_layout.addWidget(self.personality_combo)
        preset_group.setLayout(preset_layout)
        layout.addWidget(preset_group)
        
        # ========== 성격 설명 ==========
        desc_group = QGroupBox("성격 설명")
        desc_layout = QVBoxLayout()
        
        self.personality_desc_label = QLabel()
        self.personality_desc_label.setWordWrap(True)
        desc_layout.addWidget(self.personality_desc_label)
        desc_group.setLayout(desc_layout)
        layout.addWidget(desc_group)
        
        # ========== Big Five 세부사항 ==========
        detail_group = QGroupBox("Big Five 특성")
        detail_layout = QVBoxLayout()
        
        self.personality_detail_label = QLabel()
        self.personality_detail_label.setWordWrap(True)
        detail_font = QFont()
        detail_font.setPointSize(9)
        self.personality_detail_label.setFont(detail_font)
        detail_layout.addWidget(self.personality_detail_label)
        detail_group.setLayout(detail_layout)
        layout.addWidget(detail_group)
        
        layout.addStretch()
        
        # 초기 설명 표시
        self.on_personality_changed(self.selected_personality)
        
        return layout
    
    def on_personality_changed(self, preset_name: str):
        """성격 선택 변경"""
        from character.personality_system import PersonalitySystem
        
        if preset_name not in PersonalitySystem.PERSONALITY_PRESETS:
            preset_name = "Russell (기본)"
        
        preset = PersonalitySystem.PERSONALITY_PRESETS[preset_name]
        
        # 설명 업데이트
        self.personality_desc_label.setText(preset.get("description", ""))
        
        # Big Five 세부사항 업데이트
        detail_text = (
            f"개방성(Openness): {preset['openness']:+.1f}\n"
            f"성실성(Conscientiousness): {preset['conscientiousness']:+.1f}\n"
            f"외향성(Extraversion): {preset['extraversion']:+.1f}\n"
            f"친화성(Agreeableness): {preset['agreeableness']:+.1f}\n"
            f"신경증(Neuroticism): {preset['neuroticism']:+.1f}"
        )
        self.personality_detail_label.setText(detail_text)
        
        self.selected_personality = preset_name
    
    def update_from_current_resolution(self):
        """현재 해상도에 맞는 프리셋 선택"""
        for preset_name, (w, h) in self.PRESETS.items():
            if preset_name != "사용자 정의" and w == self.selected_width and h == self.selected_height:
                self.preset_combo.setCurrentText(preset_name)
                return
        self.preset_combo.setCurrentText("사용자 정의")
    
    def on_preset_changed(self, preset_name):
        """프리셋 선택 변경"""
        resolution = self.PRESETS.get(preset_name)
        if resolution:  # 사용자 정의가 아님
            width, height = resolution
            self.width_spinbox.blockSignals(True)
            self.height_spinbox.blockSignals(True)
            
            self.width_spinbox.setValue(width)
            self.height_spinbox.setValue(height)
            
            self.width_spinbox.blockSignals(False)
            self.height_spinbox.blockSignals(False)
            
            self.update_preview()
    
    def update_preview(self):
        """미리보기 업데이트"""
        width = self.width_spinbox.value()
        height = self.height_spinbox.value()
        self.preview_label.setText(f"선택: {width} × {height}px")
        self.selected_width = width
        self.selected_height = height
    
    def confirm(self):
        """확인 버튼 클릭"""
        self.selected_width = self.width_spinbox.value()
        self.selected_height = self.height_spinbox.value()
        self.resolution_selected.emit(self.selected_width, self.selected_height)
        self.personality_selected.emit(self.selected_personality)
        self.accept()
    
    def get_resolution(self):
        """선택된 해상도 반환"""
        return self.selected_width, self.selected_height
    
    def get_personality(self):
        """선택된 성격 반환"""
        return self.selected_personality
