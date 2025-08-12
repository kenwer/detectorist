import sys
import os

from PySide6.QtWidgets import QApplication
from modelviewer.model_viewer import ModelViewer

def main():
    app = QApplication(sys.argv)
    window = ModelViewer()
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
