"""Relatório HTML autossuficiente, com origem, condições da análise e gráficos embutidos."""
from __future__ import annotations

import base64
import cmath
import math
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from .measurement import Measurement

PHASE_COLORS = {"A": "#0f9fb8", "B": "#c98a12", "C": "#c0558a"}


def _angle(phasor: complex, reference: complex) -> str:
    if abs(reference) < 1e-12:
        reference = 1
    value = round(math.degrees(cmath.phase(phasor / reference)), 1) + 0.0
    return f"{value:.1f}°"


def write_report(path: Path, result: Measurement, source: str, calibration: str,
                 start_s: float, end_s: float, images: dict[str, bytes] | None = None) -> None:
    """Grava o relatório. `images` mapeia título → PNG (embutido em base64)."""
    reference = result.phasors.get("A", 1)
    rows = "".join(
        f"<tr><td><span class='dot' style='background:{PHASE_COLORS.get(phase, '#888')}'></span>{phase}</td>"
        f"<td>{rms:.3f}</td><td>{abs(result.phasors[phase]):.3f}</td>"
        f"<td>{_angle(result.phasors[phase], reference)}</td></tr>"
        for phase, rms in result.rms.items())
    power_rows = "".join(f"<tr><td>{phase}</td><td>{p.active_w:.3f}</td>"
                         f"<td>{p.reactive_fundamental_var:.3f}</td><td>{p.apparent_va:.3f}</td>"
                         f"<td>{p.power_factor if p.power_factor is not None else 'indisponível'}</td></tr>"
                         for phase, p in result.power.items())
    power_table = (f"<table><tr><th>Fase</th><th>P (W)</th><th>Q1 (var)</th><th>S (VA)</th><th>FP</th></tr>{power_rows}</table>"
                   if power_rows else "<p class='muted'>Sem correntes sincronizadas: potências indisponíveis.</p>")
    harmonic_rows = "".join(f"<tr><td>{h}</td><td>{value:.4f}</td></tr>"
                            for h, value in enumerate(result.harmonic_percent, 1))
    thd = f"{result.thd_percent:.3f} %" if result.thd_percent is not None else "indisponível"
    harmonic_range = f" (h2–h{len(result.harmonic_percent)})" if result.thd_percent is not None else ""
    figures = "".join(
        f"<figure><img alt='{escape(title)}' src='data:image/png;base64,{base64.b64encode(png).decode()}'>"
        f"<figcaption>{escape(title)}</figcaption></figure>"
        for title, png in (images or {}).items())
    generated = datetime.now(timezone.utc).astimezone()
    document = f"""<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PRISMA — relatório de instrumentação</title>
<style>
body{{font:15px/1.5 system-ui,'Segoe UI',sans-serif;max-width:1000px;margin:32px auto;padding:0 20px;color:#18222f}}
header{{border-bottom:2px solid #0f9fb8;padding-bottom:10px;margin-bottom:18px}}
h1{{margin:0;font-size:24px;letter-spacing:.5px}} h2{{font-size:17px;margin-top:28px;color:#0b4f5c}}
.muted{{color:#5d6b7c}} .kpis{{display:flex;flex-wrap:wrap;gap:10px;margin:16px 0}}
.kpi{{border:1px solid #d5dde6;border-radius:10px;padding:10px 14px;min-width:150px}}
.kpi b{{display:block;font-size:20px}} .kpi span{{font-size:12px;color:#5d6b7c}}
table{{border-collapse:collapse;margin:12px 0;min-width:420px}}
td,th{{border-bottom:1px solid #e1e6ec;padding:7px 12px;text-align:left}} th{{background:#f2f5f8}}
.dot{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px}}
figure{{margin:14px 0}} img{{max-width:100%;border:1px solid #d5dde6;border-radius:8px}}
figcaption{{font-size:12px;color:#5d6b7c}}
footer{{margin-top:30px;font-size:12px;color:#5d6b7c;border-top:1px solid #e1e6ec;padding-top:10px}}
@media print{{body{{margin:0}} figure{{break-inside:avoid}}}}
</style>
<header><h1>PRISMA · Relatório de instrumentação</h1>
<div class="muted">Gerado em {generated:%d/%m/%Y %H:%M:%S %Z} · janela {start_s:.6f}–{end_s:.6f} s</div></header>
<p><b>Origem:</b> {escape(source)}<br><b>Calibração:</b> {escape(calibration)}</p>
<div class="kpis">
<div class="kpi"><span>Frequência</span><b>{result.frequency_hz:.3f} Hz</b></div>
<div class="kpi"><span>THD fase A</span><b>{thd}</b><span>{harmonic_range.strip()}</span></div>
<div class="kpi"><span>Janelamento</span><b>{escape(result.window)}</b></div>
</div>
{figures}
<h2>Tensões AC</h2>
<table><tr><th>Fase</th><th>RMS (V)</th><th>Fundamental RMS (V)</th><th>Ângulo (ref. A)</th></tr>{rows}</table>
<h2>Potências AC</h2><p class="muted">P e S incluem distorção; Q1 representa apenas a fundamental.</p>
{power_table}
<h2>Harmônicas da fase A</h2><table><tr><th>Ordem</th><th>% da fundamental</th></tr>{harmonic_rows}</table>
<footer>Estimativas de software. Não constituem certificação metrológica nem comprovam validação da bancada.</footer>
</html>"""
    path.write_text(document, encoding="utf-8")
