"""Serve a serial da DEMOEM (ou uma demonstração) na rede, como o gateway ESP32-S3.

Uso:
    uv run python scripts/ponte_tcp.py COM3            # DEMOEM pelo CH340, porta TCP 3333
    uv run python scripts/ponte_tcp.py --demo          # sem placa: resumos e rajadas sintéticos
    uv run python scripts/ponte_tcp.py COM3 --porta 4000 --host 0.0.0.0

No app PRISMA (neste PC ou em outro da rede), escolha "Gateway na rede…" e
informe IP:porta (ex.: 192.168.0.20:3333). Só os comandos de identificar,
rajadas e autocalibração passam da rede para a placa. A atualização de
firmware continua pela serial local (scripts/atualizar_demoem.py).
Sem autenticação nem criptografia: use só em rede local confiável.
"""
import argparse
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from prisma.core.link import DEFAULT_TCP_PORT  # noqa: E402
from prisma.core.netbridge import BridgeServer, demo_stream, paced  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("serial", nargs="?", help="porta da placa (ex.: COM3)")
    parser.add_argument("--demo", action="store_true", help="dados sintéticos de 6 canais, sem placa")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--host", default="0.0.0.0", help="interface (padrão: todas)")
    parser.add_argument("--porta", type=int, default=DEFAULT_TCP_PORT)
    args = parser.parse_args()
    if bool(args.serial) == args.demo:
        parser.error("informe a porta serial ou --demo")

    handle = None
    if args.demo:
        read, write = paced(demo_stream()), None
        source = "demonstração (6 canais, 60 Hz)"
    else:
        import serial
        handle = serial.Serial(args.serial, args.baud, timeout=0.02)
        read = lambda: handle.read(max(1, min(handle.in_waiting, 4096)))  # noqa: E731
        write = handle.write
        source = f"{args.serial} a {args.baud} baud"

    bridge = BridgeServer(args.host, args.porta, read, write)
    names = sorted({info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)})
    print(f"Servindo {source} em TCP {args.porta} ({', '.join(names) or args.host}). Ctrl+C encerra.")
    try:
        bridge.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if handle is not None:
            handle.close()
        print(f"\nEncerrada: {bridge.sent_bytes} bytes enviados, comandos aceitos {bridge.gate.accepted}, "
              f"recusados {bridge.gate.rejected}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
