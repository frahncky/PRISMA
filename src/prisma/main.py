"""Entrypoint desktop do PRISMA.

Exemplos:
    python -m prisma
    python -m prisma --port COM4 --profile examples/profiles/demoem-ch340.json --connect
    python -m prisma --last --screen 2
    python -m prisma --port prisma.local --connect --painel   # pelo gateway Wi-Fi
    python -m prisma --painel            # painel touch em tela cheia
    python -m prisma --quiosque --port prisma.local   # medidor numa tela dedicada (docs/quiosque.md)
    python -m prisma --ligacao mono                  # experimento monofásico (bi, tri)
"""
import argparse
import json
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from prisma.core.calibration import Calibration
from prisma.ui.main_window import MainWindow, app_icon


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="prisma", description="PRISMA · Programar, Medir, Analisar")
    parser.add_argument("--port", help="porta serial (ex.: COM4) ou gateway na rede (ex.: 192.168.0.20:3333, prisma.local)")
    parser.add_argument("--profile", type=Path, help="perfil de dispositivo JSON")
    parser.add_argument("--connect", action="store_true", help="conectar à serial ao abrir")
    parser.add_argument("--last", action="store_true", help="reusar a última porta e o último perfil e conectar")
    parser.add_argument("--screen", type=int, help="monitor onde abrir (1 = principal)")
    parser.add_argument("--painel", action="store_true", help="abrir o painel touch em tela cheia")
    parser.add_argument("--quiosque", action="store_true",
                        help="tela dedicada: só o painel, conecta e reconecta sozinho, sem demonstração "
                             "(usa --port ou a última porta)")
    parser.add_argument("--cursor", action="store_true", help="no quiosque, mantém o cursor do mouse visível")
    parser.add_argument("--ligacao", choices=("mono", "bi", "tri"),
                        help="ligação do experimento: mono (fase A), bi (A e B) ou tri (A, B e C); fica salva")
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
    saved = settings.value("calibration")
    if saved:
        try:
            window._set_calibration(Calibration.from_dict(json.loads(saved)))
        except (ValueError, TypeError) as exc:
            window._log(f"Calibração salva ignorada: {exc}")
    port = args.port or settings.value("last_port")
    if port and not window.select_port(port):
        if args.quiosque:
            # Na partida a USB pode ainda não ter enumerado: o quiosque espera pela porta.
            window.port_combo.insertItem(0, f"{port} (aguardando)", port)
            window.port_combo.setCurrentIndex(0)
        else:
            window._log(f"Porta {port} não encontrada.")
            port = None

    if args.ligacao:
        window.set_wiring(args.ligacao)
    screens = app.screens()
    target = None
    screen_index = args.screen if args.screen is not None else int(settings.value("last_screen", 1))
    if 1 <= screen_index <= len(screens):
        target = screens[screen_index - 1]
        window.setScreen(target)
        window.move(target.availableGeometry().topLeft())
    if args.quiosque:
        window.enter_kiosk(screen=target, hide_cursor=not args.cursor)
        if port:
            window.connect_serial()
        else:
            window._log("Quiosque sem porta: informe --port (ex.: prisma.local ou COM3).")
    else:
        window.showMaximized()
        if port and (args.connect or args.last):
            window.connect_serial()
        if args.painel:
            window.open_touch_panel(screen=target)
    code = app.exec()
    current = window.screen()
    if current in screens:
        settings.setValue("last_screen", screens.index(current) + 1)
    sys.exit(code)


if __name__ == "__main__":
    main()
