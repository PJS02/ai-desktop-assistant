# 해상도 설정 다이얼로그
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
    QLabel, QSpinBox, QComboBox, QGroupBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont


class ResolutionSettingsDialog(QDialog):
    """해상도 설정 다이얼로그"""
    
    # 미리 정의된 해상도 프리셋
    PRESETS = {
        "1440p (2560x1440)": (2560, 1440),
        "1080p (1920x1080)": (1920, 1080),
        "720p (1280x720)": (1280, 720),
        "사용자 정의": None  # 커스텀
    }
    
    resolution_selected = pyqtSignal(int, int)  # width, height 신호
    
    def __init__(self, current_width=None, current_height=None):
        super().__init__()
        self.selected_width = current_width or 1920
        self.selected_height = current_height or 1080
        self.setup_ui()
    
    def setup_ui(self):
        """UI 설정"""
        self.setWindowTitle("화면 해상도 설정")
        self.setModal(True)
        self.setMinimumWidth(400)
        
        layout = QVBoxLayout()
        
        # 타이틀
        title = QLabel("캐릭터 활동 범위 설정")
        title_font = QFont()
        title_font.setPointSize(12)
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
        
        # ========== 미리보기 ==========
        self.preview_label = QLabel(f"선택: {self.selected_width} × {self.selected_height}px")
        preview_font = QFont()
        preview_font.setPointSize(10)
        self.preview_label.setFont(preview_font)
        self.preview_label.setStyleSheet("color: #0078d4; font-weight: bold;")
        layout.addWidget(self.preview_label)
        
        # 스핀박스 변경 감지
        self.width_spinbox.valueChanged.connect(self.update_preview)
        self.height_spinbox.valueChanged.connect(self.update_preview)
        
        # ========== 버튼 ==========
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        confirm_btn = QPushButton("확인")
        confirm_btn.clicked.connect(self.confirm)
        button_layout.addWidget(confirm_btn)
        
        cancel_btn = QPushButton("취소")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addStretch()
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
        
        # 초기 프리셋 선택
        self.update_from_current_resolution()
    
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
        self.accept()
    
    def get_resolution(self):
        """선택된 해상도 반환"""
        return self.selected_width, self.selected_height
