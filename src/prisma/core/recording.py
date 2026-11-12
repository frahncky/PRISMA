"""Registro incremental de amostras, independente da janela dos gráficos."""
import csv
from pathlib import Path

from .protocol import Sample


class CsvRecorder:
    def __init__(self, path: Path, source: str) -> None:
        self.path = Path(path)
        self.source = source
        self.count = 0
        self._file = self.path.open("w", encoding="utf-8", newline="")
        try:
            self._writer = csv.writer(self._file)
            self._writer.writerow(["t_s", "va_V", "vb_V", "vc_V", "ia_A", "ib_A", "ic_A", "origem"])
            self._file.flush()
        except OSError:
            self._file.close()
            raise

    def write(self, sample: Sample) -> None:
        self._writer.writerow([sample.t, sample.va, sample.vb, sample.vc,
                               sample.ia, sample.ib, sample.ic, self.source])
        self.count += 1

    def flush(self) -> None:
        self._file.flush()

    def close(self) -> None:
        self._file.close()
