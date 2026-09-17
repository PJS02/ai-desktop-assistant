import sys
from PyQt6.QtWidgets import QApplication
from dotenv import load_dotenv
from character.character_widget import CharacterWidget
from character.resolution_settings import ResolutionSettingsDialog
from character.config_manager import load_config, save_config


load_dotenv()

def main():
    app = QApplication(sys.argv)
    
    # 저장된 설정 불러오기
    saved_width, saved_height, saved_personality = load_config()
    print(f"[설정] 저장된 해상도: {saved_width} × {saved_height}px")
    print(f"[설정] 저장된 성격: {saved_personality}")
    
    # 설정 다이얼로그 띄우기 (저장된 값으로 초기화)
    settings_dialog = ResolutionSettingsDialog(saved_width, saved_height, saved_personality)
    if settings_dialog.exec() == ResolutionSettingsDialog.DialogCode.Accepted:
        width, height = settings_dialog.get_resolution()
        personality = settings_dialog.get_personality()
        print(f"[설정] 선택된 해상도: {width} × {height}px")
        print(f"[설정] 선택된 성격: {personality}")
        save_config(width, height, personality)  # 설정 저장
    else:
        # 취소 버튼 클릭 시 저장된 설정 사용
        width, height = saved_width, saved_height
        personality = saved_personality
        print(f"[설정] 저장된 해상도 사용: {width} × {height}px")
        print(f"[설정] 저장된 성격 사용: {personality}")
    
    # 캐릭터 위젯에 해상도 전달
    character = CharacterWidget(screen_width=width, screen_height=height, personality_preset=personality)
    character.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()