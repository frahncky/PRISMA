from pathlib import Path
import math
import shutil
import subprocess

import numpy as np
import pytest

from prisma.core.calibration import Calibration, delays_from_resistive_load
from prisma.core.measurement import analyze
from prisma.core.protocol import (BURST_SPACING_S, SampleBlock, Sample, StreamDecoder, crc16_ccitt,
                                  encode_burst, parse_message)

ROOT = Path(__file__).resolve().parents[1]


def test_crc16_ccitt_false_vetor_padrao():
    assert crc16_ccitt(b"123456789") == 0x29B1


def test_quadro_binario_tres_canais():
    frame = encode_burst(3, 1995.487, [(0, 1, 65535), (10, 11, 12)], timeout_mask=2)
    [block] = StreamDecoder().feed(frame)
    assert isinstance(block, SampleBlock)
    assert block.channels == ("va", "vb", "vc") and block.timeout_mask == 2
    assert block.fs_hz == pytest.approx(1995.487)
    assert block.samples[0].vc == 65535.0 and block.samples[1].va == 10.0
    assert block.samples[0].t == 3 * BURST_SPACING_S and block.samples[0].ia is None
    assert block.wire_bytes == len(frame)


def test_quadro_binario_seis_canais_com_sinal():
    frame = encode_burst(0, 2000, [(-1, 2, 3, -4, 5, -6)] * 2, signed=True)
    [block] = StreamDecoder().feed(frame)
    assert block.channels == ("va", "vb", "vc", "ia", "ib", "ic")
    assert block.samples[1] == Sample(0.0005, -1.0, 2.0, 3.0, -4.0, 5.0, -6.0)


def test_binario_e_json_misturados_fragmentados_e_crc_corrompido():
    good = encode_burst(1, 2000, [(1, 2, 3)] * 4)
    bad = bytearray(good)
    bad[12] ^= 0xFF
    stream = (b'{"type":"sample","t":0,"va":1,"vb":2,"vc":3}\n' + bytes(bad)
              + b'{"type":"status","leds":{"run":true}}\n' + good)
    decoder = StreamDecoder()
    items = []
    for i in range(0, len(stream), 7):  # fragmentos pequenos, cortando quadros ao meio
        items.extend(decoder.feed(stream[i:i + 7]))
    kinds = [type(x).__name__ for x in items]
    assert kinds[0] == "Sample" and kinds[-1] == "SampleBlock"
    assert "HardwareStatus" in kinds and decoder.crc_errors == 1 and decoder.frames == 1


def test_linha_gigante_e_descartada_sem_perder_proximo_quadro():
    decoder = StreamDecoder(max_line=100)
    items = decoder.feed(b"X" * 500) + decoder.feed(encode_burst(0, 2000, [(1, 2, 3)] * 2))
    assert isinstance(items[0], ValueError) and "100" in str(items[0])
    assert isinstance(items[-1], SampleBlock)


@pytest.mark.parametrize("mask_byte, n", [(0x05, 2), (0x07, 1)])
def test_rajada_binaria_invalida(mask_byte, n):
    import struct
    from prisma.core.protocol import BURST_HEADER, FRAME_BURST, encode_frame
    payload = BURST_HEADER.pack(0, 2_000_000, n, mask_byte, 0) + b"\x00" * (2 * 3 * n)
    [item] = StreamDecoder().feed(encode_frame(FRAME_BURST, payload))
    assert isinstance(item, ValueError)
    assert struct  # usado no pack acima


def test_encoder_c_igual_ao_python(tmp_path):
    if not shutil.which("gcc"):
        pytest.skip("GCC não instalado")
    source = tmp_path / "frame_test.c"
    source.write_text(r'''
#include <stdio.h>
#include "prisma_frame.h"
int main(void) {
    uint16_t v[12] = {0, 1, 65535, 10, 11, 12, 20, 21, 22, 30, 31, 32};
    uint8_t out[PRISMA_BURST_FRAME_BYTES(4, 3)];
    int i, len = prisma_encode_burst_frame(7u, 1995487u, 4u, PRISMA_MASK_VOLTAGES, 1u, v, out, sizeof out);
    if (len != (int)sizeof out) return 1;
    if (prisma_encode_burst_frame(7u, 1995487u, 4u, PRISMA_MASK_VOLTAGES, 1u, v, out, sizeof out - 1) != -1) return 2;
    if (prisma_encode_burst_frame(7u, 1995487u, 4u, 0x05u, 0u, v, out, sizeof out) != -1) return 3;
    for (i = 0; i < len; ++i) printf("%02X", out[i]);
    return 0;
}
''', encoding="utf-8")
    exe = tmp_path / "frame_test"
    subprocess.run(["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-Ifirmware/include",
                    str(source), "firmware/src/prisma_frame.c", "-o", str(exe)],
                   cwd=ROOT, check=True, capture_output=True)
    output = subprocess.run([str(exe)], check=True, capture_output=True, text=True).stdout
    expected = encode_burst(7, 1995.487, [(0, 1, 65535), (10, 11, 12), (20, 21, 22), (30, 31, 32)],
                            timeout_mask=1)
    assert bytes.fromhex(output) == expected


def test_parse_message_json_continua_funcionando():
    assert isinstance(parse_message('{"type":"sample","t":0,"va":1,"vb":2,"vc":3}'), Sample)


# --- calibração de fase -------------------------------------------------------

def _signals(delay_s: float):
    fs, f = 2000.0, 60.0
    t = np.arange(500) / fs
    phases = np.array([0, -2 * np.pi / 3, 2 * np.pi / 3])
    v = 100 * np.sin(2 * np.pi * f * t[:, None] + phases)
    i = 5 * np.sin(2 * np.pi * f * (t[:, None] - delay_s) + phases)  # corrente atrasada pelo sensor
    return t, v, i


def test_atraso_de_carga_resistiva_e_compensacao_restauram_fp_unitario():
    delay = 200e-6  # ≈ 4,3° a 60 Hz
    t, v, i = _signals(delay)
    before = analyze(t, v, fundamental_hz=60.0, currents=i)
    assert before.power["A"].power_factor < 0.998
    delays = delays_from_resistive_load(before.phasors, before.current_phasors, 60.0)
    assert delays["ia"] == pytest.approx(200, abs=1)
    channels = {ch: {"gain": 1.0, "offset": 0.0, "delay_us": d} for ch, d in delays.items()}
    calibration = Calibration(channels, "Fase")
    v2, i2 = calibration.align(t, v, i)
    after = analyze(t[1:-1], v2[1:-1], fundamental_hz=60.0, currents=i2[1:-1])
    for phase in "ABC":
        assert after.power[phase].power_factor == pytest.approx(1.0, abs=1e-4)


def test_carga_nao_resistiva_e_rejeitada():
    t, v, i = _signals(1 / 60 / 4)  # 90°
    result = analyze(t, v, fundamental_hz=60.0, currents=i)
    with pytest.raises(ValueError, match="resistiva"):
        delays_from_resistive_load(result.phasors, result.current_phasors, 60.0)


def test_perfil_antigo_sem_delay_continua_valido_e_chave_extra_rejeitada(tmp_path):
    Calibration({"va": {"gain": 2.0, "offset": 0.0}})
    with pytest.raises(ValueError):
        Calibration({"va": {"gain": 2.0, "offset": 0.0, "fase": 1}})
    cal = Calibration({"ia": {"gain": 1.0, "offset": 0.0, "delay_us": 12.5}}, "x")
    path = tmp_path / "c.json"
    cal.save(path)
    assert Calibration.load(path).delays_s() == {"ia": pytest.approx(12.5e-6)}
    assert math.isfinite(cal.delays_s()["ia"])
