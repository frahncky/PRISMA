import csv
import json
import sqlite3

import numpy as np
import pytest

from prisma.core.calibration import Calibration
from prisma.core.devices import DeviceProfile
from prisma.core.history import SqliteRecorder, export_session, list_sessions
from prisma.core.measurement import SignalBuffer, analyze, estimate_frequency
from prisma.core.protocol import HardwareStatus, Sample, parse_message, parse_sample
from prisma.core.reports import write_report


def signals(frequency=60, seconds=1, rate=4000, current_angle=0.4):
    t = np.arange(int(seconds * rate)) / rate
    angles = 2 * np.pi * frequency * t[:, None] + np.array([0, -2*np.pi/3, 2*np.pi/3])
    v = 127 * np.sqrt(2) * np.sin(angles)
    i = 5 * np.sqrt(2) * np.sin(angles - current_angle)
    return t, v, i


@pytest.mark.parametrize("frequency", [45, 50, 59.5, 60, 65])
def test_frequencia_dinamica_e_janela_hann(frequency):
    t, v, _ = signals(frequency, seconds=0.25)
    assert estimate_frequency(t, v[:, 0] + 80) == pytest.approx(frequency, abs=0.02)
    result = analyze(t, v + 80, fundamental_hz=None, window="hann")
    assert result.frequency_hz == pytest.approx(frequency, abs=0.02)
    assert abs(result.phasors['A']) == pytest.approx(127, abs=0.03)
    assert result.thd_percent < 0.03


def test_ajuste_separa_harmonicas_em_janela_nao_coerente():
    t, v, _ = signals(59.3, seconds=0.237)
    v[:, 0] += 127 * np.sqrt(2) * 0.08 * np.sin(2*np.pi*59.3*3*t)
    result = analyze(t, v + 50, 59.3, window="hann")
    assert result.harmonic_percent[2] == pytest.approx(8, abs=0.001)
    assert result.thd_percent == pytest.approx(8, abs=0.001)


@pytest.mark.parametrize("angle", [0, 0.4, -0.4, np.pi])
def test_potencia_ac_com_sinal_de_q_e_fp(angle):
    t, v, i = signals(current_angle=angle)
    result = analyze(t, v, currents=i)
    for p in result.power.values():
        assert p.active_w == pytest.approx(635 * np.cos(angle), abs=1e-8)
        assert p.reactive_fundamental_var == pytest.approx(635 * np.sin(angle), abs=1e-8)
        assert p.apparent_va == pytest.approx(635, abs=1e-8)
        assert p.power_factor == pytest.approx(np.cos(angle), abs=1e-8)
    assert result.current_rms['A'] == pytest.approx(5)


def test_potencia_ausente_sem_correntes_e_fp_indefinido_sem_carga():
    t, v, i = signals()
    assert not analyze(t, v).power
    assert analyze(t, v, currents=i*0).power['A'].power_factor is None
    assert analyze(t, v*0).thd_percent is None
    with pytest.raises(ValueError, match="Correntes"):
        analyze(t, v, currents=i[:-1])
    with pytest.raises(ValueError, match="Sinal insuficiente"):
        estimate_frequency(t, np.zeros(len(t)))


def test_calibracao_valida_e_preserva_canal_ausente(tmp_path):
    path = tmp_path / 'cal.json'
    path.write_text(json.dumps({'version': 1, 'name': 'bancada', 'channels': {
        'va': {'gain': 2, 'offset': -1}, 'ia': {'gain': 3, 'offset': 0}}}))
    c = Calibration.load(path)
    assert c.apply(Sample(1, 3, 4, 5)) == Sample(1, 5, 4, 5)
    assert c.apply(Sample(1, 3, 4, 5, 2, 3, 4)).ia == 6
    for invalid in ({'va': {'gain': 0, 'offset': 0}}, {'va': {'gain': True, 'offset': 0}},
                    {'va': {'gain': 1, 'offset': float('nan')}}, {'inexistente': {}}):
        with pytest.raises(ValueError):
            Calibration(invalid)


def test_sqlite_sessoes_filtro_exportacao_e_persistencia(tmp_path):
    path = tmp_path / 'historico.sqlite'
    for source in ('DEMO', 'SERIAL COM4'):
        recorder = SqliteRecorder(path, source, '{"name":"teste"}')
        for index in range(5000):
            recorder.write(Sample(index / 1000, 127, -60, 0, 5, -2, 0))
        recorder.flush()
        recorder.close()
    sessions = list_sessions(path)
    assert len(sessions) == 2
    assert sessions[0][2:4] == ('SERIAL COM4', 5000)
    assert sessions[0][4] is not None
    output = tmp_path / 'sessao.csv'
    assert export_session(path, sessions[0][0], output, 1, 1.002) == 3
    rows = list(csv.DictReader(output.open(encoding='utf-8')))
    assert rows[0]['ia_A'] == '5.0'
    assert rows[0]['origem'] == 'SERIAL COM4'
    with pytest.raises(ValueError):
        export_session(path, sessions[0][0], path)
    with pytest.raises(ValueError):
        export_session(path, 999, output)
    db = sqlite3.connect(path)
    assert db.execute('SELECT calibration_json FROM sessions LIMIT 1').fetchone()[0] == '{"name":"teste"}'
    db.close()


def test_status_e_correntes_opcionais_retrocompativeis():
    sample = parse_sample('{"type":"sample","t":0,"va":1,"vb":2,"vc":3,"ia":4,"ib":5,"ic":6}')
    assert sample.ia == 4
    with pytest.raises(KeyError):
        parse_sample('{"type":"sample","t":0,"va":1,"vb":2,"vc":3,"ia":4}')
    status = parse_message('{"type":"status","leds":{"run":true},"gpio":{"in":false},"adc":{"a":12},"lcd":["PRISMA"]}')
    assert isinstance(status, HardwareStatus)
    assert status.leds['run'] is True
    assert status.adc['a'] == 12
    with pytest.raises(ValueError):
        parse_message('{"type":"status","leds":{"run":1}}')
    with pytest.raises(ValueError):
        parse_message('{"type":"status","lcd":"errado"}')
    buffer = SignalBuffer()
    buffer.add(sample)
    assert buffer.currents().shape == (1, 3)
    buffer.add(Sample(1, 1, 2, 3))
    assert buffer.currents() is None


def test_perfil_dispositivo_e_relatorio_sem_html_injetado(tmp_path):
    path = tmp_path / 'perfil.json'
    path.write_text(json.dumps({'version': 1, 'name': 'ESP32', 'baudrate': 230400}))
    assert DeviceProfile.load(path).baudrate == 230400
    path.write_text(json.dumps({'version': 1, 'name': 'ESP32', 'baudrate': True}))
    with pytest.raises(ValueError):
        DeviceProfile.load(path)
    t, v, i = signals(seconds=0.25)
    report = tmp_path / 'relatorio.html'
    write_report(report, analyze(t, v, currents=i), '<script>origem</script>', 'identidade', 0, .25)
    html = report.read_text(encoding='utf-8')
    assert '<script>' not in html
    assert '&lt;script&gt;' in html
    assert 'Q1' in html and '635.000' in html
