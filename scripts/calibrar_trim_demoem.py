"""Ajusta o trim do oscilador interno da DEMOEM usando o PC como referência de tempo.

O intervalo entre rajadas depende só do relógio da placa (timer de amostragem e
baud da SCI). Comparando o período medido pelo PC com o período nominal obtém-se
relógio_real / nominal com ~0,05 % de resolução. Cada passo de TRIM vale ~0,275 %
(TRIM maior = relógio mais lento). O script grava, mede e corrige até |erro| < 0,15 %.

Uso: python scripts/calibrar_trim_demoem.py COM4 [segundos_por_medida]
Requer o firmware em rajada a 115200 baud e um TRIM inicial legível (ver main.c).
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import serial

ROOT = Path(__file__).resolve().parents[1]
MAIN_C = ROOT / "firmware/codewarrior/EM256 Demo/Sources/main.c"
BAUD = 115200                      # deve coincidir com PRISMA_SCI_BAUD
BUS_HZ = 32768 * 1216 / 2          # FEI nominal
FS_HZ = BUS_HZ / 128 / 78          # MTIM1: bus/128, MOD 77
SAMPLES = 500
STEP = 0.00275                     # variação relativa do relógio por passo de TRIM
TOLERANCE = 0.0015


def read_trim() -> int:
    match = re.search(r"#define PRISMA_ICS_TRIM 0x([0-9A-Fa-f]+)U", MAIN_C.read_text(encoding="utf-8"))
    if not match:
        raise RuntimeError("PRISMA_ICS_TRIM não encontrado em main.c")
    return int(match.group(1), 16)


def set_trim(value: int) -> None:
    text = MAIN_C.read_text(encoding="utf-8")
    text = re.sub(r"#define PRISMA_ICS_TRIM 0x[0-9A-Fa-f]+U", f"#define PRISMA_ICS_TRIM 0x{value:02X}U", text)
    MAIN_C.write_text(text, encoding="utf-8")


def flash() -> None:
    result = subprocess.run(["pwsh", "-NoProfile", "-File", str(ROOT / "scripts/gravar_demoem.ps1"), "-Build"],
                            capture_output=True, text=True, timeout=400)
    if result.returncode != 0 or "alvo em execu" not in result.stdout:
        raise RuntimeError("Falha ao gravar:\n" + result.stdout[-1500:] + result.stderr[-1500:])


def clock_ratio(port: str, seconds: float) -> float:
    """relógio real / nominal, pela regressão seq × instante de chegada."""
    arrivals, sizes, pending = [], [], bytearray()
    with serial.Serial(port, BAUD, timeout=0.05) as handle:
        handle.reset_input_buffer()
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            chunk = handle.read(4096)
            now = time.perf_counter()
            for byte in chunk:
                if byte != 10:
                    pending.append(byte)
                    continue
                match = re.match(rb'\{"type":"burst".*?"seq":(\d+)', bytes(pending))
                if match:
                    arrivals.append((int(match.group(1)), now))
                    sizes.append(len(pending) + 1)
                pending.clear()
    if len(arrivals) < 8:
        raise RuntimeError(f"Poucas rajadas legíveis ({len(arrivals)}); confira o baud e o TRIM inicial")
    seqs, times = np.array(arrivals, dtype=float).T
    period = np.polyfit(seqs, times, 1)[0]
    sbr = round(BUS_HZ / 16 / BAUD)
    nominal = SAMPLES / FS_HZ + float(np.median(sizes)) * 10 * 16 * sbr / BUS_HZ
    return nominal / period


def main() -> None:
    port = sys.argv[1] if len(sys.argv) > 1 else "COM4"
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 25.0
    trim = read_trim()
    for _ in range(6):
        ratio = clock_ratio(port, seconds)
        print(f"TRIM=0x{trim:02X}: relógio {ratio:.4f}x do nominal ({(ratio - 1) * 100:+.2f} %)", flush=True)
        if abs(ratio - 1) < TOLERANCE:
            print(f"Concluído: TRIM=0x{trim:02X}", flush=True)
            return
        trim = min(0xFF, max(0x00, trim + round((ratio - 1) / STEP)))
        set_trim(trim)
        flash()
        time.sleep(1.0)
    raise RuntimeError("Não convergiu em 6 iterações")


if __name__ == "__main__":
    main()
