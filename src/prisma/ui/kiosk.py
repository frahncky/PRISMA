"""Modo quiosque: o PRISMA como medidor numa tela dedicada (ex.: 10,1" 1280×800).

``python -m prisma --quiosque --port prisma.local`` abre só o painel touch em
tela cheia, sem dados de demonstração e sem cursor, conecta sozinho, reconecta
(rede e serial), mantém a tela ligada e só sai com toque longo em "Sair",
que leva à janela principal para manutenção.
"""
from __future__ import annotations

import sys

# SetThreadExecutionState (Windows): tela e sistema ligados enquanto o quiosque roda.
_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001
_ES_DISPLAY_REQUIRED = 0x00000002


def keep_display_on(enabled: bool) -> bool:
    """Impede (ou volta a permitir) que a tela apague. True se o sistema aceitou.

    No Windows usa SetThreadExecutionState. No Linux (Raspberry Pi) o apagamento
    da tela é configuração do sistema: ver docs/quiosque.md.
    """
    if sys.platform != "win32":
        return False
    import ctypes
    flags = _ES_CONTINUOUS | (_ES_SYSTEM_REQUIRED | _ES_DISPLAY_REQUIRED if enabled else 0)
    return bool(ctypes.windll.kernel32.SetThreadExecutionState(flags))
