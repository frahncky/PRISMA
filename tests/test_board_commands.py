"""Comandos PC → placa: parser C (prisma_command.h) compilado com gcc e o lado Python."""
from pathlib import Path
import shutil
import struct
import subprocess

import pytest

from prisma.core.protocol import (
    CMD_ADC_CAL, CMD_BURST, CMD_INFO, FRAME_COMMAND, INFO_FORMAT, BoardInfo, CommandReply, StreamDecoder,
    adc_cal_text, encode_command, encode_frame, parse_board_info,
)

ROOT = Path(__file__).resolve().parents[1]

# Placa de mentira: responde cada comando válido ecoando os argumentos (código
# 0xEE = desconhecido) e, no fim, um quadro id 0xFF com o contador de erros.
HARNESS = r"""
#include <stdio.h>
#include "prisma_frame_stream.h"
#include "prisma_command.h"

static FILE *out;
static void put(unsigned char value) { fputc(value, out); }

int main(int argc, char **argv)
{
    FILE *in = fopen(argv[1], "rb");
    prisma_cmd_parser p;
    unsigned char tail[2];
    int c;

    (void)argc;
    out = fopen(argv[2], "wb");
    prisma_cmd_init(&p);
    while ((c = fgetc(in)) != EOF) {
        if (prisma_cmd_feed(&p, (unsigned char)c)) {
            if (p.payload[1] == 0xEEU) {
                prisma_cmd_reply(put, &p, PRISMA_REPLY_UNKNOWN, p.payload, 0U);
            } else {
                prisma_cmd_reply(put, &p, PRISMA_REPLY_OK, &p.payload[2], prisma_cmd_args(&p));
            }
        }
    }
    p.payload[0] = 0xFFU;
    p.payload[1] = 0xFFU;
    prisma_le16(tail, p.errors);
    prisma_cmd_reply(put, &p, PRISMA_REPLY_OK, tail, 2U);
    fclose(in);
    fclose(out);
    return 0;
}
"""


@pytest.fixture(scope="module")
def board(tmp_path_factory):
    if not shutil.which("gcc"):
        pytest.skip("GCC não instalado")
    folder = tmp_path_factory.mktemp("command")
    source = folder / "harness.c"
    source.write_text(HARNESS)
    executable = folder / "harness"
    subprocess.run(["gcc", "-std=c89", "-pedantic", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
                    "-Wno-long-long", "-Ifirmware/include", str(source), "-o", str(executable)],
                   cwd=ROOT, check=True, capture_output=True)

    def run(data: bytes) -> tuple[list[CommandReply], int]:
        (folder / "in.bin").write_bytes(data)
        subprocess.run([str(executable), str(folder / "in.bin"), str(folder / "out.bin")], check=True)
        items = StreamDecoder().feed((folder / "out.bin").read_bytes())
        assert not [item for item in items if isinstance(item, Exception)]
        *replies, errors = items
        assert errors.command_id == 0xFF
        return replies, struct.unpack("<H", errors.data)[0]
    return run


def test_comandos_validos_sao_respondidos_com_o_mesmo_id(board):
    replies, errors = board(encode_command(7, CMD_INFO) + encode_command(8, CMD_BURST, b"\x05")
                            + encode_command(9, CMD_ADC_CAL))
    assert [(r.command_id, r.code, r.status, r.data) for r in replies] == [
        (7, CMD_INFO, 0, b""), (8, CMD_BURST, 0, b"\x05"), (9, CMD_ADC_CAL, 0, b"")]
    assert errors == 0


def test_ruido_crc_errado_e_cabecalho_invalido_nao_perdem_o_proximo_comando(board):
    good = encode_command(1, CMD_BURST, b"\x00")
    bad_crc = bytearray(encode_command(2, CMD_INFO))
    bad_crc[-1] ^= 0x40
    too_long = encode_frame(FRAME_COMMAND, bytes(17))      # payload acima de 16 bytes
    too_short = encode_frame(FRAME_COMMAND, b"\x03")       # sem código
    other_type = encode_frame(0x01, b"\x00" * 4)           # quadro que não é comando
    stream = (b"lixo\xa5\xa5" + good + bytes(bad_crc) + too_long + b"\xa5" + good
              + too_short + other_type + encode_command(3, 0xEE))
    replies, errors = board(stream)
    assert [(r.command_id, r.status) for r in replies] == [(1, 0), (1, 0), (3, 1)]
    assert replies[-1].status_text == "comando desconhecido"
    assert errors == 4  # CRC, longo, curto e tipo errado


def test_info_decodifica_campos_da_placa():
    data = INFO_FORMAT.pack(1, 3, 6, 1, 1995487, 500, 0xFF, 2, 1, 1234)
    info = parse_board_info(CommandReply(4, CMD_INFO, 0, data))
    assert info == BoardInfo(1, 3, 6, 1, 1995.487, 500, 0xFF, 2, 1, 1234)
    assert info.adc_cal_text == "não executada" and not info.adc_calibrated
    assert adc_cal_text(0) == "ok" and adc_cal_text(0b101) == "falhou no ADC1, ADC3"
    with pytest.raises(ValueError):
        parse_board_info(CommandReply(4, CMD_INFO, 2, b""))


def test_comando_python_rejeita_argumentos_grandes():
    with pytest.raises(ValueError):
        encode_command(1, CMD_BURST, bytes(15))
    assert encode_command(0x12, CMD_BURST, b"\x02")[:7] == b"\xa5\x5a\x10\x03\x00\x12\x02"


def test_serial_escreve_comandos_enfileirados(monkeypatch):
    from prisma.core.serial_reader import SerialReader

    reader = SerialReader("TEST")
    written, replies = [], []
    reader.reply_received.connect(replies.append)
    reader.send(encode_command(5, CMD_INFO))
    answer = encode_frame(0x11, bytes((5, CMD_INFO, 0)) + INFO_FORMAT.pack(1, 3, 3, 1, 1995487, 500, 0, 0, 0, 9))
    chunks = iter([answer])

    class Port:
        in_waiting = 4096

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def write(self, data):
            written.append(data)

        def read(self, count):
            try:
                return next(chunks)
            except StopIteration:
                reader.stop()
                return b""

    monkeypatch.setattr("serial.Serial", lambda *a, **k: Port())
    reader.run()
    assert written == [encode_command(5, CMD_INFO)]
    assert len(replies) == 1 and parse_board_info(replies[0]).windows == 9


@pytest.fixture
def window(app, tmp_path):
    from PySide6.QtCore import QSettings
    from prisma.ui.main_window import MainWindow

    widget = MainWindow()
    widget.timer.stop()
    widget.settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)
    yield widget
    widget.reader = None
    widget.close()


class FakeReader:
    def __init__(self):
        self.sent = []

    def isRunning(self):
        return True

    def send(self, data):
        self.sent.append(data)


def test_painel_envia_comandos_e_mostra_respostas(window):
    window.reader = FakeReader()
    assert window.send_board_command(CMD_INFO)
    command_id = window.reader.sent[-1][5]  # A5 5A | tipo | len u16 | id | código
    info = INFO_FORMAT.pack(1, 3, 6, 5, 1995487, 500, 0xFF, 0, 0, 42)
    window._on_command_reply(CommandReply(command_id, CMD_INFO, 0, info))
    assert "rev 3" in window.board_label.text() and "6 canais" in window.board_label.text()
    assert window.burst_combo.currentData() == 5 and window.board_info.windows == 42

    window.burst_combo.setCurrentIndex(window.burst_combo.findData(0))
    window.burst_combo.activated.emit(window.burst_combo.currentIndex())
    sent = window.reader.sent[-1]
    assert sent[5:8] == bytes((sent[5], CMD_BURST, 0))
    window._on_command_reply(CommandReply(sent[5], CMD_BURST, 0, b"\x00"))
    assert "rajadas desligadas" in window.board_label.text()

    window.send_board_command(CMD_ADC_CAL)
    cal_id = window.reader.sent[-1][5]
    window._on_command_reply(CommandReply(cal_id, CMD_ADC_CAL, 0, b"\x02"))
    assert "falhou no ADC2" in window.board_label.text()
    # Resposta repetida ou de pedido desconhecido é ignorada.
    window._on_command_reply(CommandReply(cal_id, CMD_ADC_CAL, 0, b"\x00"))
    assert "falhou no ADC2" in window.board_label.text()


def test_sem_resposta_avisa_o_fio_da_rx(window):
    window.reader = FakeReader()
    window.send_board_command(CMD_BURST, b"\x01")
    window._command_timeout(window._command_id, False)
    assert "PTC0/RX3" in window.board_label.text()
    window.reader = None
    assert not window.send_board_command(CMD_INFO)
    assert "conecte a serial" in window.board_label.text()


def test_primeiro_resumo_identifica_a_placa_uma_vez(window):
    from prisma.core.protocol import MeterSummary

    window.reader = FakeReader()
    summary = MeterSummary(0, 1995.487, 2000, ("va", "vb", "vc"), (60_000_000,) * 3,
                           (1_900_000_000_000,) * 3, None, 52, 2_000_000)
    from dataclasses import replace

    window._on_summary(summary)
    window._on_summary(replace(summary, seq=1))
    assert [frame[6] for frame in window.reader.sent] == [CMD_INFO]
