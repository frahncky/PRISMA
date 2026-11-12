"""Integração dos cálculos com os instrumentos Qt, sem hardware."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QFileDialog

from prisma.core.protocol import Sample
from prisma.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app):
    widget = MainWindow()
    widget.timer.stop()
    yield widget
    widget.close()


def test_demo_exibe_quinze_harmonicas(window):
    for _ in range(6):
        window._generate_demo_batch()
    window._draw_signals()
    assert "h2–h15" in window.details.text()
    assert "---" not in window.metric_labels["A"].text()
    assert "DADOS SINTÉTICOS" in window.details.text()


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
