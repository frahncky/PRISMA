"""Entrypoint desktop do PRISMA."""
import sys
from PySide6.QtWidgets import QApplication
from prisma.ui.main_window import MainWindow, app_icon

def main() -> None:
    if sys.platform == "win32":
        # Faz o Windows usar o ícone do PRISMA na barra de tarefas, e não o do Python.
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PRISMA.Studio")
    app = QApplication(sys.argv)
    app.setApplicationName("PRISMA")
    app.setOrganizationName("PRISMA")
    app.setWindowIcon(app_icon())
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()


