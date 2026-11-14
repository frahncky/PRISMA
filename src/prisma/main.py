"""Entrypoint desktop do PRISMA.

Exemplos:
    python -m prisma
    python -m prisma --port COM4 --profile examples/profiles/demoem-ch340.json --connect
    python -m prisma --last --screen 2
"""
import argparse
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from prisma.ui.main_window import MainWindow, app_icon


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="prisma", description="PRISMA · Programar, Medir, Analisar")
    parser.add_argument("--port", help="porta serial a selecionar (ex.: COM4)")
    parser.add_argument("--profile", type=Path, help="perfil de dispositivo JSON")
    parser.add_argument("--connect", action="store_true", help="conectar à serial ao abrir")
    parser.add_argument("--last", action="store_true", help="reusar a última porta e o último perfil e conectar")
    parser.add_argument("--screen", type=int, help="monitor onde abrir (1 = principal)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if sys.platform == "win32":
        # Faz o Windows usar o ícone do PRISMA na barra de tarefas, e não o do Python.
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PRISMA.Studio")
    app = QApplication(sys.argv[:1])
    app.setApplicationName("PRISMA")
    app.setOrganizationName("PRISMA")
    app.setWindowIcon(app_icon())
    window = MainWindow()

    settings = window.settings
    profile = args.profile or (Path(settings.value("last_profile", "")) if settings.value("last_profile") else None)
    if profile and profile.is_file():
        try:
            window.apply_profile(profile)
        except (OSError, ValueError, TypeError, ImportError) as exc:
            window._log(f"Perfil não carregado ({profile}): {exc}")
    port = args.port or settings.value("last_port")
    if port and not window.select_port(port):
        window._log(f"Porta {port} não encontrada.")
        port = None

    screens = app.screens()
    screen_index = args.screen if args.screen is not None else int(settings.value("last_screen", 1))
    if 1 <= screen_index <= len(screens):
        target = screens[screen_index - 1]
        window.setScreen(target)
        window.move(target.availableGeometry().topLeft())
    window.showMaximized()
    if port and (args.connect or args.last):
        window.connect_serial()
    code = app.exec()
    current = window.screen()
    if current in screens:
        settings.setValue("last_screen", screens.index(current) + 1)
    sys.exit(code)


if __name__ == "__main__":
    main()
