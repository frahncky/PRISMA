"""Dados pela rede: endereços, filtro de comandos, ponte TCP e reconexão do leitor."""
import socket
import threading
import time

import pytest

from prisma.core.link import DEFAULT_TCP_PORT, link_label, network_address, network_url
from prisma.core.netbridge import BridgeServer, CommandGate, demo_stream, demo_window
from prisma.core.protocol import CMD_INFO, MeterSummary, SampleBlock, encode_command, encode_frame
from prisma.core.serial_reader import SerialReader

ENTER_BOOT, BOOT_WRITE = 0x04, 0x22


@pytest.mark.parametrize("text, expected", [
    ("COM3", None), ("com12", None), ("/dev/ttyUSB0", None), ("TEST", None), ("", None),
    ("192.168.0.20", ("192.168.0.20", DEFAULT_TCP_PORT)),
    ("192.168.0.20:4000", ("192.168.0.20", 4000)),
    ("prisma.local", ("prisma.local", DEFAULT_TCP_PORT)),
    ("tcp://gateway:3333", ("gateway", 3333)),
    ("socket://localhost:5000/", ("localhost", 5000)),
    ("tcp://gateway", ("gateway", DEFAULT_TCP_PORT)),
])
def test_enderecos_de_rede_e_portas_seriais(text, expected):
    assert network_address(text) == expected


@pytest.mark.parametrize("text", ["host:abc", ":3333", "tcp://a b:1", "host:70000"])
def test_endereco_invalido_e_recusado(text):
    with pytest.raises(ValueError):
        network_address(text)


def test_rotulos():
    assert network_url("prisma.local") == "tcp://prisma.local:3333"
    assert link_label("tcp://10.0.0.5:3333") == "10.0.0.5:3333 (rede)"
    assert link_label("COM3") == "COM3"


def test_filtro_so_deixa_passar_comandos_inofensivos():
    info = encode_command(1, CMD_INFO)
    burst = encode_command(2, 0x02, bytes([5]))
    boot = encode_command(3, ENTER_BOOT)
    write = encode_command(4, BOOT_WRITE, bytes(12), max_args=138)
    broken = bytearray(encode_command(5, CMD_INFO))
    broken[-1] ^= 0xFF
    gate = CommandGate()
    stream = b"lixo" + info + boot + write + bytes(broken) + encode_frame(0x02, b"x" * 4) + burst
    out = []
    for i in range(0, len(stream), 3):  # fragmentado como no TCP
        out += gate.feed(stream[i:i + 3])
    assert out == [info, burst]
    assert gate.accepted == 2 and gate.rejected >= 4


def test_demonstracao_tem_60_hz_e_seis_canais():
    summary, rows = demo_window(5)
    assert summary.frequency_hz == pytest.approx(60.0, abs=1e-3)
    assert summary.ac_rms(0) == pytest.approx(20000 / 2 ** 0.5, rel=0.01)
    assert summary.active(0) > 0 and len(rows) == 500 and len(rows[0]) == 6


def _run(reader, limit=15.0):
    """Roda o leitor nesta thread (sinais diretos) e para à força depois de ``limit``."""
    guard = threading.Timer(limit, reader.stop)
    guard.start()
    started = time.monotonic()
    reader.run()
    guard.cancel()
    return time.monotonic() - started < limit


def _serve(bridge):
    thread = threading.Thread(target=bridge.serve_forever, daemon=True)
    thread.start()
    return thread


def test_app_recebe_pela_rede_e_comandos_passam_pelo_filtro():
    commands = []
    bridge = BridgeServer("127.0.0.1", 0, _fast(demo_stream()), commands.append, log=lambda _: None)
    _serve(bridge)
    host, port = bridge.address
    reader = SerialReader(f"tcp://{host}:{port}")
    summaries, blocks, logs = [], [], []
    reader.message.connect(logs.append)
    reader.block_received.connect(blocks.append)

    def on_summary(item):
        summaries.append(item)
        if len(summaries) == 1:
            reader.send(encode_command(9, CMD_INFO) + encode_command(10, ENTER_BOOT))
        if len(summaries) >= 3:
            reader.stop()
    reader.summary_received.connect(on_summary)
    finished = _run(reader)
    bridge.stop()
    assert finished, logs
    assert all(isinstance(s, MeterSummary) for s in summaries) and len(summaries) >= 3
    assert blocks and isinstance(blocks[0], SampleBlock) and len(blocks[0].samples) == 500
    assert [s.seq for s in summaries[:3]] == [1, 2, 3]
    deadline = time.monotonic() + 3
    while not commands and time.monotonic() < deadline:
        time.sleep(0.05)
    assert commands == [encode_command(9, CMD_INFO)]  # o 0x04 (bootloader) não passa pela rede
    assert any("conectado" in log for log in logs)


def _fast(stream):
    def read():
        time.sleep(0.01)
        return next(stream)
    return read


def test_leitor_reconecta_quando_o_gateway_cai():
    server = socket.create_server(("127.0.0.1", 0))
    port = server.getsockname()[1]
    frames = demo_stream()
    next(frames)

    def gateway():
        for _ in range(2):  # duas sessões: a primeira cai logo depois de um resumo
            client, _ = server.accept()
            client.sendall(next(frames))
            time.sleep(0.2)
            client.close()
    threading.Thread(target=gateway, daemon=True).start()

    reader = SerialReader(f"127.0.0.1:{port}")
    reader.reconnect_delay = 0.1
    connected, reconnecting, summaries = [], [], []
    reader.connected.connect(lambda: connected.append(1))
    reader.reconnecting.connect(lambda: reconnecting.append(1))

    def on_summary(item):
        summaries.append(item)
        if len(summaries) == 2:
            reader.stop()
    reader.summary_received.connect(on_summary)
    finished = _run(reader, 10)
    server.close()
    assert finished
    assert len(connected) == 2 and reconnecting and [s.seq for s in summaries] == [1, 2]


def test_rede_muda_e_sem_dados_reconecta():
    server = socket.create_server(("127.0.0.1", 0))
    port = server.getsockname()[1]
    accepted = []

    def gateway():
        while len(accepted) < 2:
            client, _ = server.accept()
            accepted.append(client)  # aceita e fica calado (Wi-Fi caiu sem fechar o TCP)
    threading.Thread(target=gateway, daemon=True).start()
    reader = SerialReader(f"127.0.0.1:{port}")
    reader.idle_timeout, reader.reconnect_delay = 0.4, 0.05
    logs = []
    reader.message.connect(logs.append)
    reader.connected.connect(lambda: reader.stop() if len(accepted) >= 2 else None)
    finished = _run(reader, 10)
    server.close()
    assert finished
    assert any("nenhum dado" in log for log in logs)


def test_janela_principal_aceita_gateway_na_lista(app):
    from prisma.ui.main_window import MainWindow
    window = MainWindow()
    try:
        assert window.port_combo.findData(window.NETWORK_ITEM) >= 0
        assert window.select_port("192.168.0.20:3333")
        assert window.port_combo.currentData() == "tcp://192.168.0.20:3333"
        assert "Rede · 192.168.0.20:3333" in window.port_combo.currentText()
        assert not window.select_port("host:abc")
    finally:
        window.close()
