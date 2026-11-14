"""Integração dos cálculos com os instrumentos Qt, sem hardware."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QFileDialog

from prisma.core.protocol import Sample
from prisma.ui.main_window import MainWindow


@pytest.fixture
def window(app, tmp_path):
    from PySide6.QtCore import QSettings

    widget = MainWindow()
    widget.timer.stop()
    # Nunca tocar nas configurações reais do usuário.
    widget.settings = QSettings(str(tmp_path / "prisma-test.ini"), QSettings.Format.IniFormat)
    yield widget
    widget.close()


def test_demo_exibe_quinze_harmonicas(window):
    for _ in range(6):
        window._generate_demo_batch()
    window._draw_signals()
    assert "h2–h15" in window.details.text()
    assert "---" not in window.metric_labels["A"].text()
    assert "Demonstração (sintético)" in window.details.text()


@pytest.mark.parametrize("sample_rate, expected", [
    (800, "h2–h6"),
    (200, "THD indisponível"),
    (100, "Análise indisponível"),
])
def test_serial_adapta_analise_a_taxa(window, sample_rate, expected):
    # Desenha o demo primeiro para detectar indicadores antigos em caso de erro.
    for _ in range(6):
        window._generate_demo_batch()
    window._draw_signals()
    window.buffer.clear()
    window._set_mode("AQUISIÇÃO SERIAL REAL — TESTE", real=True)
    for t in np.arange(sample_rate // 2) / sample_rate:
        values = 127 * np.sqrt(2) * np.sin(
            2 * np.pi * 60 * t + np.array([0, -2 * np.pi / 3, 2 * np.pi / 3])
        )
        window.buffer.add(Sample(float(t), *map(float, values)))
    window._draw_signals()
    assert expected in window.details.text()
    if sample_rate == 100:
        assert all(label.text() == "--- V" for label in window.metric_labels.values())


def test_registro_demo_e_troca_de_modo(window, tmp_path, monkeypatch):
    import csv

    path = tmp_path / "demo.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: (str(path), "CSV (*.csv)"))
    window.toggle_recording()
    window._tick()
    assert "120 amostras" in window.record_label.text()
    window.start_demo()
    assert window.recorder is None
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 120
    assert all("SINTÉTICOS" in row["origem"] for row in rows)


def test_registro_serial_ignora_tempo_repetido_e_fecha_na_desconexao(window, tmp_path, monkeypatch):
    import csv

    path = tmp_path / "serial.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: (str(path), "CSV (*.csv)"))
    window._set_mode("AQUISIÇÃO SERIAL REAL — TESTE", real=True)
    window.toggle_recording()
    window._on_sample(Sample(0, 1, 2, 3))
    window._on_sample(Sample(0, 4, 5, 6))
    window._on_sample(Sample(1, 7, 8, 9))
    window._on_disconnected()
    assert window.recorder is None
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert rows[-1]["va_V"] == "7"


def test_falha_de_escrita_encerra_registro_sem_parar_demo(window, tmp_path, monkeypatch):
    path = tmp_path / "falha.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: (str(path), "CSV (*.csv)"))
    window.toggle_recording()

    def disk_full(sample):
        raise OSError("Disco cheio")

    monkeypatch.setattr(window.recorder, "write", disk_full)
    window._tick()
    assert window.recorder is None
    assert window.demo_index == 120
    assert "Disco cheio" in window.console.toPlainText()


def test_ui_sqlite_calibracao_relatorio_e_fasor(window, tmp_path, monkeypatch):
    from prisma.core.calibration import Calibration
    from prisma.core.history import list_sessions

    window._set_calibration(Calibration({'va': {'gain': 2, 'offset': 0}}, 'ganho teste'))
    assert window.last_analysis is None
    path = tmp_path / 'sessoes.sqlite'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a: (str(path), 'SQLite'))
    window.toggle_recording(backend='sqlite')
    for _ in range(6):
        window._tick()
    window.stop_recording()
    assert list_sessions(path)[0][3] == 720
    assert 'ganho teste' in list_sessions(path)[0][2]
    assert 250 < window.last_analysis[0].rms['A'] < 260
    assert float(window.power_view.item(0, 1).text()) == pytest.approx(5, abs=.01)
    window._select_phasor('A')
    window.phasor_reference.setCurrentIndex(1)
    window._draw_signals()
    assert '0.00°' in window.selected_phasor.text()
    report = tmp_path / 'report.html'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a: (str(report), 'HTML'))
    window.export_report()
    assert 'ganho teste' in report.read_text(encoding='utf-8')
    assert 'SINTÉTICOS' in report.read_text(encoding='utf-8')
    window.reset_calibration()
    assert window.metric_labels['A'].text() == '--- V'


def test_ui_build_gravacao_requer_confirmacao_e_artefato_integro(window, tmp_path, monkeypatch):
    import json
    import sys
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QMessageBox

    project = tmp_path / 'project.json'
    project.write_text(json.dumps({'version': 1, 'name': 'HOST TEST', 'target': 'HOST',
        'build': [sys.executable, '-c', 'from pathlib import Path; Path("fw.elf").write_bytes(b"ELF"); Path("fw.map").write_text("MEMORY TEST")'],
        'artifact': 'fw.elf', 'map_file': 'fw.map',
        'flash': [sys.executable, '-c', 'from pathlib import Path; Path("executed").write_text("ok")']}))
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a: (str(project), 'JSON'))
    window.load_project()
    loop = QEventLoop()
    window.runner.done.connect(loop.quit)
    window.build_project()
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    assert window.build_digest is not None
    assert window.btn_flash.isEnabled()
    assert 'MEMORY TEST' in window.map_view.toPlainText()
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.StandardButton.No)
    window.flash_project()
    assert not (tmp_path / 'executed').exists()
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.StandardButton.Yes)
    window.flash_project()
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    assert (tmp_path / 'executed').read_text() == 'ok'
    (tmp_path / 'executed').unlink()
    (tmp_path / 'fw.elf').write_bytes(b'changed')
    errors = []
    monkeypatch.setattr(QMessageBox, 'critical', lambda *args: errors.append(args[-1]))
    window.flash_project()
    assert not (tmp_path / 'executed').exists()
    assert any('Artefato alterado' in text for text in errors)


def test_icone_navegacao_pausa_e_imagem(window, tmp_path):
    from prisma.ui.main_window import ICON_PATH

    assert ICON_PATH.is_file() and not window.windowIcon().isNull()
    for button, widget in window.nav_buttons:
        button.click()
        assert window.tabs.currentWidget() is widget and button.isChecked()
    window.tabs.setCurrentIndex(0)
    window.toggle_pause()
    window.wave.getPlotItem().listDataItems()[0].setData([0, 1], [0, 0])
    window._tick()
    assert window.paused and window.curves["A"].getData()[0].tolist() == [0, 1]
    window.toggle_pause()
    assert not window.paused
    target = tmp_path / "painel.png"
    window.export_snapshot(str(target))
    assert target.stat().st_size > 0


def test_painel_adc_mostra_valores_e_alertas(window):
    from prisma.core.protocol import parse_message

    window._on_hardware_status(parse_message('{"type":"status","message":"ADC RAW",'
        '"adc":{"dadp0_raw":1200},"adc_signed":{"dadp0":1200},"adc_cal_fail_mask":2}'))
    assert window.adc_table.rowCount() == 2
    assert window.adc_table.item(0, 0).text() == "dadp0_raw"
    assert "adc_cal_fail_mask = 2" in window.hardware_summary.text()


def test_rajada_alimenta_osciloscopio_e_reinicia_com_seq_menor(window):
    import numpy as np
    from prisma.core.protocol import Sample, SampleBlock

    def block(seq):
        fs, n = 1995.487, 500
        samples = tuple(Sample(seq * 10.0 + i / fs, *(30000 + 20000 * np.sin(2 * np.pi * 60 * i / fs + k * 2.094)
                        for k in range(3))) for i in range(n))
        return SampleBlock(seq, fs, ("ad4", "ad5", "ad6"), samples)

    window._on_block(block(5))
    window._draw_signals()
    assert abs(window.last_analysis[0].frequency_hz - 60) < 1 if window.frequency_combo.currentIndex() == 2 else window.last_analysis
    window._on_block(block(0))  # firmware reiniciou
    assert window.buffer.arrays(duration_s=1.0)[0].size == 500
    assert "Rajada 0" in window.statusBar().currentMessage()


def test_rajada_sem_calibracao_usa_contagens_e_frequencia_automatica(window):
    import numpy as np
    from prisma.core.protocol import Sample, SampleBlock

    fs = 1995.487
    samples = tuple(Sample(i / fs, *(30000 + 20000 * np.sin(2 * np.pi * 51.85 * i / fs + k * 2.094)
                    for k in range(3))) for i in range(500))
    window.frequency_combo.setCurrentIndex(0)
    window._on_block(SampleBlock(0, fs, ("ad4", "ad5", "ad6"), samples))
    window._draw_signals()
    assert window.frequency_combo.currentIndex() == 2
    assert abs(window.last_analysis[0].frequency_hz - 51.85) < 0.2
    from prisma.ui.main_window import ADC_VREF_V, ADC_FULL_SCALE
    rms_counts = 20000 / np.sqrt(2)
    shown = float(window.metric_labels["A"].text().split()[0])
    assert abs(shown - rms_counts * ADC_VREF_V / ADC_FULL_SCALE) < 0.02
    window.start_demo()
    assert not window.raw_counts


def test_pagina_hardware_mostra_rajada_bruta_e_saturacao(window):
    from prisma.core.protocol import Sample, SampleBlock

    samples = tuple(Sample(i / 2000, float(i * 200 % 65536), 65535.0, 1000.0) for i in range(300))
    window._show_block(SampleBlock(3, 2000.0, ("ad4", "ad5", "ad6"), samples), 3.3, 65535)
    assert window.burst_table.rowCount() == 3
    assert window.burst_table.item(1, 0).text() == "AD5"
    assert window.burst_table.item(1, 6).text() == "300"
    assert window.burst_table.item(2, 4).text() == f"{1000 * 3.3 / 65535:.3f} V"
    assert "Rajada 3" in window.hardware_summary.text()


def test_calibrar_com_multimetro_ajusta_rms_exibido(window, tmp_path):
    from prisma.core.calibration import Calibration

    for _ in range(6):
        window._generate_demo_batch()
    window._draw_signals()
    target = tmp_path / "cal.json"
    window.calibrate_from_reference({"va": 220.0, "vb": 0.0, "vc": 0.0}, str(target))
    assert Calibration.load(target).channels["va"]["gain"] > 1.5
    window.buffer.clear()
    for _ in range(6):
        window._generate_demo_batch()
    window._draw_signals()
    assert abs(window.last_analysis[0].rms["A"] - 220.0) < 1.0
    assert abs(window.last_analysis[0].rms["B"] - 127.0) < 1.0


def test_perfil_e_porta_sao_memorizados(window, tmp_path):
    from pathlib import Path
    from prisma.main import parse_args

    profile = Path(__file__).resolve().parents[1] / "examples/profiles/demoem-ch340.json"
    window.apply_profile(profile)
    assert window.settings.value("last_profile") == str(profile)
    assert "115200" in window.profile_label.text()
    assert not window.select_port("COM_INEXISTENTE")
    args = parse_args(["--port", "COM4", "--profile", str(profile), "--connect", "--screen", "2"])
    assert (args.port, args.connect, args.screen) == ("COM4", True, 2)


def test_editor_localiza_substitui_e_numera_linhas(window):
    window.editor.setPlainText("int a;\nint b;\nfloat c;\n")
    assert window.editor.gutter_width() > 0
    assert window.editor.find_text("int") and window.editor.textCursor().selectedText() == "int"
    assert window.editor.find_text("float")
    assert not window.editor.find_text("double")
    assert window.editor.replace_all("int", "long") == 2
    assert window.editor.toPlainText().count("long") == 2
    panel = window.editor_panel
    panel.open_bar(True)
    assert panel.bar.isVisibleTo(panel) and panel.replace_edit.isVisibleTo(panel)
    panel.close_bar()
    assert not panel.bar.isVisibleTo(panel)


def test_rajadas_usam_fase_a_como_referencia_dos_fasores(window):
    import numpy as np
    from prisma.core.protocol import Sample, SampleBlock

    fs = 1995.487
    for seq, start in ((0, 0.0), (1, 0.0037)):  # blocos começando em instantes diferentes do ciclo
        samples = tuple(Sample(seq * 10.0 + i / fs, *(30000 + 20000 * np.sin(2 * np.pi * 51.85 * (i / fs + start) - k * 2.0944)
                        for k in range(3))) for i in range(500))
        window._on_block(SampleBlock(seq, fs, ("ad4", "ad5", "ad6"), samples))
        window._draw_signals()
        text = window.details.text()
        assert "∠ 0.0°" in text and ("∠ -120.0°" in text or "∠ -119.9°" in text or "∠ -120.1°" in text)
    assert window.phasor_reference.currentIndex() == 1


def test_bloco_sem_sinal_mostra_aviso_e_rms_em_vez_de_apagar(window):
    from prisma.core.protocol import Sample, SampleBlock

    fs = 1995.5
    samples = tuple(Sample(i / fs, 0.0, 0.0, 9000.0 if 100 <= i < 110 else 0.0) for i in range(500))
    window._on_block(SampleBlock(311, fs, ("ad4", "ad5", "ad6"), samples))
    window._draw_signals()
    assert window.frequency_label.text() == "Sem sinal"
    assert "Fases sem sinal: A, B" in window.details.text()
    assert window.metric_labels["A"].text().startswith("0.000")
    assert float(window.metric_labels["C"].text().split()[0]) > 0


def test_osciloscopio_com_disparo_comeca_na_subida(window):
    import numpy as np
    from prisma.core.protocol import Sample, SampleBlock

    fs = 1995.5
    for seq, offset in ((0, 0.0), (1, 0.0071)):
        samples = tuple(Sample(seq * 10.0 + i / fs, 20000 * np.sin(2 * np.pi * 51 * (i / fs + offset)), 0.0, 0.0)
                        for i in range(500))
        window._on_block(SampleBlock(seq, fs, ("ad4", "ad5", "ad6"), samples))
        window._draw_signals()
        x, y = window.curves["A"].getData()
        assert x[0] >= 0 and x[0] < 1 / fs
        assert y[0] > 0 and y[3] > y[0]  # começa subindo, logo após o nível de disparo
    window.trigger_check.setChecked(False)
    window._draw_signals()
    assert window.curves["A"].getData()[0][-1] == 0.0


def test_rajadas_gravadas_com_tempo_real_crescente(window):
    from prisma.core.protocol import Sample, SampleBlock

    window.device_profile = type(window.device_profile)("teste", baudrate=115200)
    block = SampleBlock(0, 2000.0, ("ad4", "ad5", "ad6"), tuple(Sample(i / 2000, 1.0, 2.0, 3.0) for i in range(500)))
    first = window._block_record_times(block, arrival=100.0)
    second = window._block_record_times(block, arrival=100.8)
    assert abs(first[0] + (6150 * 10 / 115200 + 0.25)) < 1e-9  # chegada - transmissão - duração
    assert abs((first[1] - first[0]) - 0.0005) < 1e-12
    assert second[0] > first[-1]
    assert abs((second[0] - first[0]) - 0.8) < 1e-9


def test_relatorio_html_embute_graficos_e_angulos(window, tmp_path):
    for _ in range(6):
        window._generate_demo_batch()
    window._draw_signals()
    target = tmp_path / "relatorio.html"
    window.export_report(str(target))
    html = target.read_text(encoding="utf-8")
    assert html.count("data:image/png;base64,") == 3
    assert "Ângulo (ref. A)" in html and "0.0°" in html and "-120.0°" in html
