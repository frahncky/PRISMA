"""Núcleo de medição contínua do firmware (prisma_meter.h) compilado no PC com gcc."""
from pathlib import Path
import math
import shutil
import subprocess

import pytest

from prisma.core.protocol import (
    FLAG_NO_SYNC, FLAG_OVERRUN, MeterSummary, StreamDecoder, encode_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FS = 1995.487
F = 51.85

HARNESS = r"""
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "prisma_frame_stream.h"
#include "prisma_meter.h"

static FILE *out;
static void put(unsigned char value) { fputc(value, out); }

int main(int argc, char **argv)
{
    const double fs = 1995.487, f = 51.85, pi = 3.14159265358979;
    const char *mode = argv[2];
    double seconds = atof(argv[3]);
    unsigned long total = (unsigned long)(seconds * fs), i;
    unsigned char channels = (unsigned char)(strcmp(mode, "sine6") == 0 ? 6U : 3U);
    unsigned long fs_whole = 1995UL;
    prisma_meter m;
    unsigned short x[6];
    unsigned char k;

    (void)argc;
    out = fopen(argv[1], "wb");
    prisma_meter_init(&m, channels, fs_whole, fs_whole + fs_whole / 4UL, 256U);
    for (i = 0UL; i < total; ++i) {
        double t = (double)i / fs;
        for (k = 0U; k < 3U; ++k) {
            double phase = 2.0 * pi * f * t - k * 2.0 * pi / 3.0;
            if (strcmp(mode, "dc") == 0) {
                x[k] = (unsigned short)(12345 + (i % 3U));
            } else {
                x[k] = (unsigned short)floor(30000.0 + 20000.0 * sin(phase) + 0.5);
            }
            x[k + 3U] = (unsigned short)floor(32768.0 + 8000.0 * sin(phase - acos(0.9)) + 0.5);
        }
        prisma_meter_sample(&m, x, (unsigned char)(i == 5000UL ? 0x02U : 0x00U));
        if (m.ready_flag != 0U) {
            /* "overrun": o laço principal só lê a cada 2,5 s e perde janelas. */
            if (strcmp(mode, "overrun") != 0 || i % 4989UL < 1200UL) {
                prisma_meter_window w = m.ready;
                m.ready_flag = 0U;
                prisma_meter_send(&w, channels, put, 1995487UL);
            }
        }
    }
    fclose(out);
    return 0;
}
"""


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    if not shutil.which("gcc"):
        pytest.skip("GCC não instalado")
    folder = tmp_path_factory.mktemp("meter")
    source = folder / "harness.c"
    source.write_text(HARNESS)
    executable = folder / "harness"
    subprocess.run(["gcc", "-std=c89", "-pedantic", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
                    "-Wno-long-long", "-Ifirmware/include", str(source), "-lm", "-o", str(executable)],
                   cwd=ROOT, check=True, capture_output=True)

    def run(mode: str, seconds: float = 6.0) -> list[MeterSummary]:
        output = folder / f"{mode}.bin"
        subprocess.run([str(executable), str(output), mode, str(seconds)], check=True)
        items = StreamDecoder().feed(output.read_bytes())
        assert not [item for item in items if isinstance(item, Exception)]
        return items
    return run


def test_janelas_de_ciclos_inteiros_dao_frequencia_e_rms(harness):
    windows = harness("sine3")
    assert len(windows) >= 4 and [w.seq for w in windows] == list(range(len(windows)))
    for w in windows:
        assert w.synced and w.channels == ("va", "vb", "vc")
        assert w.frequency_hz == pytest.approx(F, abs=5e-4)
        assert FS <= w.n + 1 and w.n < FS + FS / F + 2  # ~1 s, fechando no ciclo seguinte
        assert w.cycles * FS / F == pytest.approx(w.n, abs=1.5)  # janela = ciclos inteiros
        # A borda da janela fica a até ±½ amostra do cruzamento exato: com ~2000
        # amostras isso dá ±0,03 % no RMS e alguns contagens na média de B e C.
        for index in range(3):
            assert w.ac_rms(index) == pytest.approx(20000 / math.sqrt(2), rel=5e-4)
            assert w.mean(index) == pytest.approx(30000, abs=15)
    assert windows[2].timeout_mask == 0x02  # a amostra 5000 marcou timeout no ADC2


def test_potencia_com_seis_canais(harness):
    windows = harness("sine6")
    assert windows and all(w.sumvi is not None for w in windows)
    for w in windows:
        for phase in range(3):
            assert w.ac_rms(phase + 3) == pytest.approx(8000 / math.sqrt(2), rel=5e-4)
            expected = 20000 * 8000 / 2 * 0.9
            assert w.active(phase) == pytest.approx(expected, rel=1e-3)


def test_sinal_dc_fecha_por_tempo_sem_frequencia(harness):
    windows = harness("dc", 5.0)
    assert len(windows) >= 3
    for w in windows:
        assert w.flags & FLAG_NO_SYNC and w.frequency_hz is None and w.cycles == 0
        assert w.n == 1995 + 1995 // 4
        assert w.mean(0) == pytest.approx(12346, abs=0.01)  # 12345 + média de (0, 1, 2)
        assert w.ac_rms(0) < 1


def test_janela_nao_lida_a_tempo_vira_lacuna_marcada(harness):
    windows = harness("overrun", 10.0)
    seqs = [w.seq for w in windows]
    assert seqs != list(range(seqs[0], seqs[0] + len(seqs)))  # houve janela perdida
    after_gap = [b for a, b in zip(windows, windows[1:]) if b.seq != a.seq + 1]
    assert after_gap and all(w.flags & FLAG_OVERRUN for w in after_gap)


def test_resumo_python_ida_e_volta():
    summary = MeterSummary(7, 1995.487, 2000, ("va", "vb", "vc", "ia", "ib", "ic"),
                           (1, 2, 3, 4, 5, 6), (10, 20, 30, 40, 50, 2**63), (7, 8, 9), 104, 1024000, FLAG_OVERRUN)
    (decoded,) = StreamDecoder().feed(encode_summary(summary))
    assert decoded == summary and decoded.overrun


def _summary(seq, seconds=1.0, currents=True, phi=math.acos(0.9)):
    """Resumo como o firmware mandaria, a partir de amostras sintéticas (contagens)."""
    import numpy as np
    from prisma.core.protocol import MeterSummary

    cycles = round(seconds * F)
    n = round(cycles * FS / F)
    t = np.arange(n) / FS
    rows = [np.round(30000 + 20000 * np.sin(2 * np.pi * F * t - k * 2 * np.pi / 3)).astype(np.int64) for k in range(3)]
    if currents:
        rows += [np.round(32768 + 8000 * np.sin(2 * np.pi * F * t - k * 2 * np.pi / 3 - phi)).astype(np.int64)
                 for k in range(3)]
    k = len(rows)
    return MeterSummary(seq, FS, n, ("va", "vb", "vc", "ia", "ib", "ic")[:k],
                        tuple(int(r.sum()) for r in rows), tuple(int((r * r).sum()) for r in rows),
                        tuple(int((rows[p] * rows[p + 3]).sum()) for p in range(3)) if currents else None,
                        cycles, round((cycles - 1) / F * FS * 256))


@pytest.fixture
def window(app, tmp_path):
    from PySide6.QtCore import QSettings
    from prisma.ui.main_window import MainWindow

    widget = MainWindow()
    widget.timer.stop()
    widget.settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)
    clock = [1000.0]
    widget._clock = lambda: clock[0]
    widget.test_clock = clock
    yield widget
    widget.close()


def test_resumos_dao_energia_exata_e_frequencia_continua(window):
    from prisma.core.calibration import Calibration

    # Calibração "real": 1 contagem = 0,01 V nas tensões e 0,001 A nas correntes.
    window._set_calibration(Calibration({**{ch: {"gain": 0.01, "offset": 0.0} for ch in ("va", "vb", "vc")},
                                         **{ch: {"gain": 0.001, "offset": 0.0} for ch in ("ia", "ib", "ic")}}, "teste"))
    for seq in range(11):
        window.test_clock[0] += 1.0
        window._on_summary(_summary(seq))
    # P por fase = (200 V/√2)(8 A/√2)·0,9 = 720 W; 3 fases; 10 janelas somadas (a 1ª só sincroniza).
    duration = _summary(0).duration_s
    assert window.energy.active_wh == pytest.approx(3 * 720 * 10 * duration / 3600, rel=2e-3)
    assert window.energy.seconds == pytest.approx(10 * duration)
    assert window.stats.demand_w == pytest.approx(2160, rel=2e-3)
    assert window.frequency_label.text() == f"{F:.3f} Hz" and "contínua" in window.frequency_hint.text()
    assert "Medição contínua" in window.continuous_label.text() and "51.850 Hz" in window.continuous_label.text()

    # Uma análise de rajada não soma energia por cima dos resumos.
    before = window.energy.active_wh
    result = window.stats.trend[-1]
    from prisma.core.measurement import Measurement, Power
    fake = Measurement({"A": 1, "B": 1, "C": 1}, {}, [], 60.0, power={p: Power(1e6, 0, 1e6, 1.0) for p in "ABC"})
    window._show_energy(fake, 123.0)
    assert window.energy.active_wh == before and result is window.stats.trend[-1]


def test_resumo_perdido_e_contado_e_sem_cruzamento_nao_da_frequencia(window):
    window._on_summary(_summary(0, currents=False))
    window._on_summary(_summary(3, currents=False))
    assert window.summaries_lost == 2 and "2 janela(s) perdida(s)" in window.continuous_label.text()
    assert window.raw_counts and window._pin_volts()  # sem calibração: volts no pino
    dc = MeterSummary(4, FS, 2493, ("va", "vb", "vc"), (2493 * 100,) * 3, (2493 * 100 * 100,) * 3, None, 0, 0,
                      FLAG_NO_SYNC)
    window._on_summary(dc)
    assert "sem cruzamentos" in window.continuous_label.text()
    window.start_demo()
    assert window.last_summary is None and not window._summary_fresh()


def test_atraso_da_corrente_e_corrigido_na_potencia_do_resumo():
    import numpy as np
    from prisma.core.measurement import summary_measurement

    delay = 40e-6  # a corrente é convertida ~40 µs depois da tensão (firmware de 6 canais)
    cycles = 52
    n = round(cycles * FS / F)
    t = np.arange(n) / FS
    phi = math.acos(0.9)
    v = [np.round(30000 + 20000 * np.sin(2 * np.pi * F * t - k * 2 * np.pi / 3)).astype(np.int64) for k in range(3)]
    i = [np.round(32768 + 8000 * np.sin(2 * np.pi * F * (t + delay) - k * 2 * np.pi / 3 - phi)).astype(np.int64)
         for k in range(3)]
    rows = v + i
    summary = MeterSummary(0, FS, n, ("va", "vb", "vc", "ia", "ib", "ic"), tuple(int(r.sum()) for r in rows),
                           tuple(int((r * r).sum()) for r in rows), tuple(int((v[p] * i[p]).sum()) for p in range(3)),
                           cycles, round((cycles - 1) / F * FS * 256))
    gains = dict.fromkeys(("va", "vb", "vc", "ia", "ib", "ic"), 1.0)
    true_p = 20000 * 8000 / 2 * 0.9
    raw = summary_measurement(summary, gains).power["A"].active_w
    assert abs(raw / true_p - 1) > 1e-3  # sem correção: ~0,55° a mais de FP
    fixed = summary_measurement(summary, gains, delays_s=dict.fromkeys(("ia", "ib", "ic"), -delay)).power
    for phase in "ABC":
        assert fixed[phase].active_w == pytest.approx(true_p, rel=5e-4)
        assert fixed[phase].reactive_fundamental_var == pytest.approx(20000 * 8000 / 2 * math.sin(phi), rel=2e-3)


def test_rajada_de_seis_canais_mostra_correntes_no_pino(window):
    import numpy as np
    from prisma.core.protocol import Sample, SampleBlock

    t = np.arange(500) / FS
    rows = []
    for k in range(500):
        volts = [30000 + 20000 * math.sin(2 * math.pi * F * t[k] - p * 2.0944) for p in range(3)]
        amps = [32768 + 8000 * math.sin(2 * math.pi * F * t[k] - p * 2.0944 - 0.45) for p in range(3)]
        rows.append(Sample(float(t[k]), *map(round, volts), *map(round, amps)))
    window._on_block(SampleBlock(0, FS, ("va", "vb", "vc", "ia", "ib", "ic"), tuple(rows)))
    window._draw_signals()
    assert window.burst_table.rowCount() == 6
    peak_ia = float(window.burst_table.item(3, 4).text().split()[0])
    assert peak_ia == pytest.approx(8000 * 3.3 / 32768, abs=2e-3)  # diferencial: Vref / 32768 por contagem
    assert len(window.raw_curves[5].getData()[0]) == 500
    result = window.last_analysis[0]
    assert result.current_rms["A"] == pytest.approx(8000 / math.sqrt(2) * 3.3 / 32768, rel=0.01)
    assert result.rms["A"] == pytest.approx(20000 / math.sqrt(2) * 3.3 / 65535, rel=0.01)
