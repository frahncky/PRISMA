"""Integração dos cálculos com os instrumentos Qt, sem hardware."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

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
