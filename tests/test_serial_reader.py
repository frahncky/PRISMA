from prisma.core.protocol import HardwareStatus
from prisma.core.serial_reader import SerialReader


def test_serial_reconstitui_fragmentos_limita_linhas_e_distingue_status(monkeypatch):
    reader = SerialReader('TEST')
    samples, statuses, logs = [], [], []
    reader.sample_received.connect(samples.append)
    reader.status_received.connect(statuses.append)
    reader.message.connect(logs.append)
    chunks = iter([
        b'{"type":"sam', b'ple","t":0,"va":1,"vb":2,"vc":3}\n',
        b'{"type":"status","leds":{"run":true}}\n',
        b'X' * 17000, b'\n',
        b'not-json\n',
        b'{"type":"sample","t":1,"va":4,"vb":5,"vc":6}\n',
    ])

    class Port:
        in_waiting = 4096

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, count):
            try:
                return next(chunks)
            except StopIteration:
                reader.stop()
                return b''

    monkeypatch.setattr('serial.Serial', lambda *a, **k: Port())
    reader.run()
    assert [s.t for s in samples] == [0, 1]
    assert len(statuses) == 1 and isinstance(statuses[0], HardwareStatus)
    assert any('16384' in log for log in logs)
