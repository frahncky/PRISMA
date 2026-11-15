"""Atualiza o firmware da DEMOEM pela serial, via bootloader PRISMA (sem PEmicro).

Uso:
    uv run python scripts/atualizar_demoem.py COM3 caminho/para/aplicacao.S19 [--sem-partida]

Se a placa estiver rodando a aplicação, pede a ela para reiniciar no bootloader
(comando 0x04) e espera o INFO do bootloader. Precisa do RX3 ligado
(CH340 TXD → PTC0). A gravação só vale depois do COMMIT (CRC-32 conferido pela
placa); se algo cair no meio, rode de novo.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from prisma.core.bootloader import (  # noqa: E402
    CMD_ENTER_BOOT, BootClient, BootError, SerialTransport, load_image,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("porta")
    parser.add_argument("s19", type=Path)
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--sem-partida", action="store_true", help="não executa a aplicação no fim")
    args = parser.parse_args()

    transport = SerialTransport(args.porta, args.baud)
    client = BootClient(transport, timeout=0.6, retries=2)
    try:
        try:
            info = client.info()
        except BootError:
            print("Bootloader não respondeu; pedindo à aplicação para reiniciar nele…")
            client.retries = 0
            try:
                client.request(CMD_ENTER_BOOT, timeout=0.6)
            except BootError:
                pass  # a placa reinicia sem esperar a resposta chegar
            time.sleep(0.5)
            client.retries = 4
            info = client.info()
        print(f"Bootloader rev {info.revision}: área 0x{info.app_start:X}–0x{info.app_limit - 1:X}, "
              f"página {info.page_size} B, aplicação {'válida' if info.app_valid else 'ausente'}")
        image = load_image(args.s19, info)
        print(f"Imagem {args.s19.name}: {len(image.data)} bytes, CRC-32 0x{image.crc:08X}")

        def progress(stage: str, done: int, total: int) -> None:
            print(f"\r{stage}: {done}/{total}   ", end="", flush=True)

        client.flash(image, info, run=not args.sem_partida, progress=progress)
        print(f"\nConcluído ({client.resends} reenvio(s)).")
        return 0
    except (BootError, ValueError, OSError) as exc:
        print(f"\nFalhou: {exc}", file=sys.stderr)
        return 1
    finally:
        transport.close()


if __name__ == "__main__":
    sys.exit(main())
