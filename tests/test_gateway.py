"""Núcleo do gateway ESP32-S3 (gateway/esp32s3/lib/prisma_link), compilado no PC com g++.

- O separador de quadros e o resumo 0x02 dão o mesmo que o decodificador Python.
- O cliente do bootloader grava a placa simulada (núcleo real de prisma_boot.h) nos
  mesmos cenários do gravador do PC: placa na aplicação, respostas perdidas e
  quadros da aplicação misturados com as respostas.
"""
from pathlib import Path
import math
import shutil
import subprocess

import pytest

from prisma.core.bootloader import BootInfo, build_image, image_crc, parse_srec
from prisma.core.protocol import MeterSummary, encode_burst, encode_frame, encode_summary
from test_bootloader import HOLE, LIMIT, PAGE, APP, app_srec, srec_line

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "gateway/esp32s3/lib/prisma_link"
INFO = BootInfo(1, False, PAGE, APP, LIMIT, 128, 0, *HOLE)


@pytest.fixture(scope="module")
def check(tmp_path_factory):
    if not (shutil.which("gcc") and shutil.which("g++")):
        pytest.skip("GCC/G++ não instalados")
    folder = tmp_path_factory.mktemp("gateway")
    sim = folder / "board_sim.o"
    subprocess.run(["gcc", "-std=c89", "-pedantic", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
                    "-Wno-long-long", "-Ifirmware/include", "-Itests/gateway", "-c", "tests/gateway/board_sim.c",
                    "-o", str(sim)], cwd=ROOT, check=True, capture_output=True)
    executable = folder / "gateway_check"
    build = subprocess.run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", f"-I{LIB}", "-Itests/gateway",
                            "tests/gateway/gateway_check.cpp", str(LIB / "prisma_link.cpp"),
                            str(LIB / "prisma_ota.cpp"), str(sim), "-o", str(executable)],
                           cwd=ROOT, capture_output=True, text=True)
    assert build.returncode == 0, build.stderr

    def run(*args, env=None) -> list[str]:
        result = subprocess.run([str(executable), *map(str, args)], capture_output=True, encoding="utf-8", env=env,
                                timeout=60)
        assert result.returncode == 0, result.stderr
        return result.stdout.splitlines()
    return run


def fields(line: str) -> dict[str, str]:
    return dict(item.split("=", 1) for item in line.split()[1:] if "=" in item)


def window(n=2000, fs=1995.487, freq=60.0, currents=True, seq=3) -> MeterSummary:
    """Somas de uma janela senoidal com offset, como o firmware acumula."""
    channels = 6 if currents else 3
    rows = []
    for t in range(n):
        angle = 2 * math.pi * freq * t / fs
        v = [round(32000 + 20000 * math.sin(angle - k * 2.0944)) for k in range(3)]
        i = [round(32768 + 8000 * math.sin(angle - k * 2.0944 - 0.45)) for k in range(3)]
        rows.append((v + i)[:channels])
    sums = tuple(sum(r[c] for r in rows) for c in range(channels))
    sumsq = tuple(sum(r[c] ** 2 for r in rows) for c in range(channels))
    sumvi = tuple(sum(r[p] * r[p + 3] for r in rows) for p in range(3)) if currents else None
    names = ("va", "vb", "vc", "ia", "ib", "ic")[:channels]
    period = round((n - 40) * 256)  # 1º cruzamento a 40 amostras do início da janela
    cycles = 1 + round((n - 40) * freq / fs)
    return MeterSummary(seq, fs, n, names, sums, sumsq, sumvi, cycles, period)


def test_separador_e_resumo_conferem_com_o_pc(check, tmp_path):
    six, three = window(), window(currents=False, seq=4)
    stream = (b'{"type":"status","source":"DEMOEM"}\r\n'
              + encode_summary(six)
              + encode_burst(9, 1995.487, [(1, 2, 3, 4, 5, 6)] * 500)  # 6 KB: CRC sem guardar o payload
              + b"lixo antes do quadro" + encode_summary(three)
              + encode_frame(0x11, bytes([5, 0x01, 0]))
              + encode_summary(six)[:-1] + b"\x00"  # CRC errado
              + b"\xa5\x5a\x01\xff\xff" + b"descartado\n"  # tamanho impossível: descarta até a linha
              + b"x" * 700 + b"\n" + b"fim\n")
    data = tmp_path / "stream.bin"
    data.write_bytes(stream)
    lines = check("parse", data)
    assert lines[0] == 'line {"type":"status","source":"DEMOEM"}'
    frames = [line for line in lines if line.startswith("frame")]
    assert frames == ["frame type=2 len=116 stored=1", "frame type=1 len=6012 stored=0",
                      "frame type=2 len=56 stored=1", "frame type=17 len=3 stored=1"]
    assert lines[-2:] == ["line fim", "counters frames=4 crc=1 bad=1 long=1"]

    summaries = [fields(line) for line in lines if line.startswith("summary")]
    for got, ref in zip(summaries, (six, three)):
        assert int(got["seq"]) == ref.seq
        assert float(got["f"]) == pytest.approx(ref.frequency_hz, rel=1e-9)
        assert float(got["dur"]) == pytest.approx(ref.duration_s, rel=1e-9)
        for p in range(3):
            assert float(got[f"v{p}"]) == pytest.approx(ref.ac_rms(p), rel=1e-9)
    for p in range(3):
        assert float(summaries[0][f"i{p}"]) == pytest.approx(six.ac_rms(p + 3), rel=1e-9)
        assert float(summaries[0][f"p{p}"]) == pytest.approx(six.active(p), rel=1e-9)
        assert six.active(p) == pytest.approx(20000 * 8000 / 2 * math.cos(0.45), rel=1e-2)  # janela sem ciclos inteiros
    assert "i0" not in summaries[1] and summaries[0]["calv"] == "0"


def test_ganhos_viram_unidades_fisicas(check, tmp_path):
    import os
    ref = window()
    data = tmp_path / "one.bin"
    data.write_bytes(encode_summary(ref))
    (summary,) = [fields(line) for line in check("parse", data, env={**os.environ, "GAINS": "1"})
                  if line.startswith("summary")]
    gains = [0.5 + 0.25 * c for c in range(6)]
    assert summary["calv"] == "1" and summary["cali"] == "1"
    assert float(summary["v1"]) == pytest.approx(ref.ac_rms(1) * gains[1], rel=1e-9)
    assert float(summary["i2"]) == pytest.approx(ref.ac_rms(5) * gains[5], rel=1e-9)
    assert float(summary["p0"]) == pytest.approx(ref.active(0) * gains[0] * gains[3], rel=1e-9)


def test_s19_monta_a_mesma_imagem_do_pc(check, tmp_path):
    s19 = tmp_path / "app.s19"
    s19.write_text(app_srec(size=5000, seed=4))
    image = build_image(parse_srec(s19.read_text()), INFO)
    got = fields(check("srec", s19)[0])
    assert int(got["start"]) == APP and int(got["end"]) == image.end
    assert int(got["crc"]) == image_crc(image, INFO)

    for text, message in ((srec_line(0x3FF, b"\xa0"), "fora da área"),
                          (srec_line(0x20400, b"\0\0\0\0"), "faixa reservada"),
                          ("S3090002000001020304EE", "checksum"),
                          (srec_line(APP, b"\1\2\3\4") + "\n" + srec_line(APP + 2, b"\5"), "repetido"),
                          ("S0030000FC", "sem dados")):
        s19.write_text(text + "\n")
        (line,) = check("srec", s19)
        assert line.startswith("error") and message in line, line


@pytest.mark.parametrize("mode", ["boot", "app", "lose", "noisy"])
def test_gateway_atualiza_a_placa_simulada(check, tmp_path, mode):
    s19 = tmp_path / "app.s19"
    s19.write_text(app_srec(size=6000, seed=5))
    lines = check("flash", s19, mode)
    assert lines[0] == (f"info rev=1 valid=0 page={PAGE} start={APP} limit={LIMIT} chunk=128 "
                        f"hole={HOLE[0]}-{HOLE[1]}")
    result = fields(lines[1])
    assert lines[1].startswith("ok"), lines
    assert result["running"] == "1" and result["valid"] == "1" and result["match"] == "1"
    assert result["trim"] == "90" and result["opt"] == "2"
    assert lines[1].endswith("last=pronto 1/1")
    if mode == "lose":
        assert int(result["resends"]) >= 5  # respostas perdidas recuperadas sem regravar
    elif mode == "boot":
        assert result["resends"] == "0"


def test_aplicacao_compilada_passa_pelo_gateway(check):
    s19 = ROOT / "firmware/codewarrior/EM256 App/bin/Project.abs.S19"
    if not s19.exists():
        pytest.skip("EM256 App não compilado")
    image = build_image(parse_srec(s19.read_text(encoding="ascii")), INFO)
    got = fields(check("srec", s19)[0])
    assert int(got["end"]) == image.end and int(got["crc"]) == image_crc(image, INFO)
    lines = check("flash", s19, "app")
    assert lines[1].startswith("ok") and fields(lines[1])["valid"] == "1", lines
