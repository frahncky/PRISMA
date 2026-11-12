import csv

from prisma.core.protocol import Sample
from prisma.core.recording import CsvRecorder


def test_csv_preserva_amostras_e_origem(tmp_path):
    path = tmp_path / "sinais.csv"
    recorder = CsvRecorder(path, "DEMONSTRAÇÃO — SINAIS SINTÉTICOS")
    for index in range(4500):
        recorder.write(Sample(index / 2400, 127.5, -60.0, 0.0))
    recorder.flush()
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    recorder.close()
    assert len(rows) == recorder.count == 4500
    assert float(rows[-1]["t_s"]) == 4499 / 2400
    assert rows[0]["va_V"] == "127.5"
    assert rows[0]["vb_V"] == "-60.0"
    assert rows[0]["vc_V"] == "0.0"
    assert rows[0]["origem"] == "DEMONSTRAÇÃO — SINAIS SINTÉTICOS"
