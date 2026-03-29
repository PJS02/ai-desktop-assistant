
import sys
from PyQt6.QtWidgets import QApplication
from dotenv import load_dotenv
from character.character_widget import CharacterWidget

def main():
    load_dotenv()
    app = QApplication(sys.argv)
    character = CharacterWidget()
    character.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
