"""Adaptador de firmware CSV: t,va,vb,vc[,ia,ib,ic], sem cabeçalho."""
import csv
from prisma.core.protocol import Sample, _number


def parse_message(line: bytes | str) -> Sample:
    if isinstance(line, bytes):
        line = line.decode('utf-8')
    try:
        rows = list(csv.reader([line.strip()], strict=True))
    except csv.Error as exc:
        raise ValueError("Linha CSV inválida") from exc
    fields = rows[0]
    if len(fields) not in (4, 7):
        raise ValueError('CSV requer t,va,vb,vc e, opcionalmente, ia,ib,ic')
    values = [_number(float(value), name) for name, value in zip(
        ('t', 'va', 'vb', 'vc', 'ia', 'ib', 'ic'), fields)]
    return Sample(*values)
