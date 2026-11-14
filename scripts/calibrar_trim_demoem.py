"""Busca o trim do oscilador interno da DEMOEM medindo o baud real da SCI3.

Para cada valor candidato: grava PRISMA_ICS_TRIM em main.c, compila e grava com
scripts/gravar_demoem.ps1 e mede em qual baud a telemetria fica legível.
Uso: python scripts/calibrar_trim_demoem.py COM4 [trim_min] [trim_max]
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

import serial

ROOT = Path(__file__).resolve().parents[1]
MAIN_C = ROOT / "firmware/codewarrior/EM256 Demo/Sources/main.c"
NOMINAL = 19200
HEX = set(b"0123456789ABCDEF")


def set_trim(value: int) -> None:
    text = MAIN_C.read_text(encoding="utf-8")
    text, count = re.subn(r"#define PRISMA_ICS_TRIM 0x[0-9A-Fa-f]+U", f"#define PRISMA_ICS_TRIM 0x{value:02X}U", text)
    if count != 1:
        raise RuntimeError("PRISMA_ICS_TRIM não encontrado em main.c")
    MAIN_C.write_text(text, encoding="utf-8")


def flash() -> None:
    result = subprocess.run(["pwsh", "-NoProfile", "-File", str(ROOT / "scripts/gravar_demoem.ps1"), "-Build"],
                            capture_output=True, text=True, timeout=400)
    if result.returncode != 0 or "alvo em execu" not in result.stdout:
        raise RuntimeError("Falha ao gravar:\n" + result.stdout[-1500:] + result.stderr[-1500:])


def readable(port: str, baud: int, seconds: float = 1.2) -> float:
    with serial.Serial(port, baud, timeout=0.1) as handle:
        handle.reset_input_buffer()
        data = b""
        end = time.time() + seconds
        while time.time() < end:
            data += handle.read(4096)
    return sum(c in HEX for c in data) / len(data) if data else 0.0


def measure(port: str) -> float:
    """Centro da janela de baud com dados hexadecimais legíveis."""
    time.sleep(1.0)
    good = [b for b in range(15000, 24001, 300) if readable(port, b, 0.4) > 0.9]
    if not good:
        raise RuntimeError("Nenhum baud legível entre 15000 e 24000")
    return (min(good) + max(good)) / 2


def main() -> None:
    port = sys.argv[1] if len(sys.argv) > 1 else "COM4"
    low = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0x00
    high = int(sys.argv[3], 0) if len(sys.argv) > 3 else 0xFF
    best = None
    while low <= high:
        trim = (low + high) // 2
        set_trim(trim)
        flash()
        center = measure(port)
        ratio = center / NOMINAL
        print(f"TRIM=0x{trim:02X}: baud real ~{center:.0f} ({ratio:.3f}x)", flush=True)
        if best is None or abs(ratio - 1) < abs(best[1] - 1):
            best = (trim, ratio)
        if abs(ratio - 1) < 0.005:
            break
        if ratio < 1:      # lento: diminuir TRIM
            high = trim - 1
        else:
            low = trim + 1
    trim, ratio = best
    set_trim(trim)
    flash()
    print(f"Escolhido TRIM=0x{trim:02X} ({ratio:.3f}x do nominal); confirmado a 19200: "
          f"{readable(port, NOMINAL, 2.0):.2f} de caracteres válidos", flush=True)


if __name__ == "__main__":
    main()
