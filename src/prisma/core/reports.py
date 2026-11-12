"""Relatório HTML autossuficiente, com origem e condições da análise."""
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from .measurement import Measurement


def write_report(path: Path, result: Measurement, source: str, calibration: str,
                 start_s: float, end_s: float) -> None:
    rows = "".join(f"<tr><td>{phase}</td><td>{rms:.3f}</td><td>{abs(result.phasors[phase]):.3f}</td></tr>"
                   for phase, rms in result.rms.items())
    power_rows = "".join(f"<tr><td>{phase}</td><td>{p.active_w:.3f}</td>"
                         f"<td>{p.reactive_fundamental_var:.3f}</td><td>{p.apparent_va:.3f}</td>"
                         f"<td>{p.power_factor if p.power_factor is not None else 'indisponível'}</td></tr>"
                         for phase, p in result.power.items())
    harmonic_rows = "".join(f"<tr><td>{h}</td><td>{value:.4f}</td></tr>"
                            for h, value in enumerate(result.harmonic_percent, 1))
    thd = f"{result.thd_percent:.3f}%" if result.thd_percent is not None else "indisponível"
    harmonic_range = f" (h2–h{len(result.harmonic_percent)})" if result.thd_percent is not None else ""
    document = f"""<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<title>PRISMA — relatório de instrumentação</title>
<style>body{{font:16px system-ui;max-width:980px;margin:40px auto;padding:0 20px;color:#182636}}
table{{border-collapse:collapse;margin:20px 0}}td,th{{border:1px solid #bbb;padding:8px;text-align:left}}
@media print{{body{{margin:0}}}}</style>
<h1>PRISMA · Relatório de instrumentação</h1>
<p>Gerado em UTC: {datetime.now(timezone.utc).isoformat()}</p>
<p><b>Origem:</b> {escape(source)}<br><b>Calibração:</b> {escape(calibration)}</p>
<p>Janela temporal: {start_s:.6f}–{end_s:.6f} s · Frequência: {result.frequency_hz:.4f} Hz
· Janelamento: {escape(result.window)} · THD Va: {thd}{harmonic_range}</p>
<h2>Tensões AC</h2><table><tr><th>Fase</th><th>RMS (V)</th><th>Fundamental RMS (V)</th></tr>{rows}</table>
<h2>Potências AC</h2><p>P e S incluem distorção; Q1 representa apenas a fundamental.
Sem corrente sincronizada, as potências ficam indisponíveis.</p>
<table><tr><th>Fase</th><th>P (W)</th><th>Q1 (var)</th><th>S (VA)</th><th>FP</th></tr>{power_rows}</table>
<h2>Harmônicas de Va</h2><table><tr><th>Ordem</th><th>% da fundamental</th></tr>{harmonic_rows}</table>
<p>Estimativas de software. Não constituem certificação metrológica nem comprovam validação da bancada.</p>
</html>"""
    path.write_text(document, encoding="utf-8")
