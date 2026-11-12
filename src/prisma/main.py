"""Entrypoint desktop do PRISMA."""
import sys
from PySide6.QtWidgets import QApplication
from prisma.ui.main_window import MainWindow

def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("PRISMA")
    app.setOrganizationName("PRISMA")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
