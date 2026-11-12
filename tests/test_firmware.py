from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest

from prisma.core.measurement import analyze
from prisma.core.protocol import HardwareStatus, Sample, parse_message

ROOT = Path(__file__).resolve().parents[1]


def test_firmware_c_compila_e_telemetria_chega_ao_analisador(tmp_path):
    if not shutil.which('gcc'):
        pytest.skip('GCC não instalado')
    executable = tmp_path / 'prisma-host'
    subprocess.run(['gcc', '-std=c99', '-Wall', '-Wextra', '-Werror', '-Ifirmware/include',
        'firmware/src/main.c', 'firmware/src/prisma_telemetry.c', 'firmware/ports/host_simulator.c',
        '-lm', '-o', str(executable)], cwd=ROOT, check=True, capture_output=True)
    result = subprocess.run([str(executable)], check=True, capture_output=True, text=True)
    messages = [parse_message(line) for line in result.stdout.splitlines()]
    samples = [s for s in messages if isinstance(s, Sample)]
    statuses = [s for s in messages if isinstance(s, HardwareStatus)]
    assert len(samples) == 5000
    assert len(statuses) == 5
    assert statuses[0].lcd == ['SIMULADOR HOST']
    t = np.array([s.t for s in samples[:500]])
    v = np.array([[s.va, s.vb, s.vc] for s in samples[:500]])
    i = np.array([[s.ia, s.ib, s.ic] for s in samples[:500]])
    measured = analyze(t, v, fundamental_hz=None, currents=i)
    assert measured.frequency_hz == pytest.approx(60, abs=0.02)
    assert measured.rms['A'] == pytest.approx(127, abs=0.01)
    assert measured.power['A'].power_factor == pytest.approx(.9, abs=.001)


def test_encoder_c_limites_de_buffer_e_int32(tmp_path):
    if not shutil.which('gcc'):
        pytest.skip('GCC não instalado')
    source = tmp_path / 'limits.c'
    source.write_text('''#include "prisma_telemetry.h"
#include <stdio.h>
int main(void) {
  char out[512];
  prisma_sample s = {0, INT32_MIN, INT32_MAX, -1, 0, 0, 0, 0};
  prisma_status status = {1, 0, 42, "LCD\\\"\\n"};
  if (prisma_encode_sample(&s, out, 1) != -1) return 1;
  if (prisma_encode_sample(&s, out, sizeof out) < 0) return 2;
  fputs(out, stdout);
  if (prisma_encode_status(&status, out, sizeof out) < 0) return 3;
  fputs(out, stdout);
  return 0;
}
''')
    executable = tmp_path / 'limits'
    subprocess.run(['gcc', '-std=c99', '-Wall', '-Wextra', '-Werror', '-Ifirmware/include',
                    str(source), 'firmware/src/prisma_telemetry.c', '-o', str(executable)],
                   cwd=ROOT, check=True, capture_output=True)
    result = subprocess.run([str(executable)], check=True, text=True, capture_output=True)
    sample, status = map(parse_message, result.stdout.splitlines())
    assert sample.va == -2147483.648
    assert sample.vb == 2147483.647
    assert sample.vc == -.001
    assert status.lcd == ['LCD"\n']
