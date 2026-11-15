"""Bootloader PRISMA: núcleo C (prisma_boot.h) com flash simulada e o gravador Python, de ponta a ponta."""
from pathlib import Path
import shutil
import struct
import subprocess

import pytest

from prisma.core.bootloader import (
    CMD_BOOT_CRC, CMD_BOOT_ERASE, CMD_BOOT_INFO, CMD_BOOT_RUN, CMD_BOOT_WRITE, REPLY_FLASH, REPLY_IMAGE,
    REPLY_RANGE, BootClient, BootError, BootInfo, FlashImage, StreamTransport, build_image, crc32, image_crc,
    parse_srec,
)

ROOT = Path(__file__).resolve().parents[1]
APP, LIMIT, PAGE = 0x20000, 0x40000 - 0x400, 0x400
HOLE = (0x203FE, 0x20410)

# Placa simulada: MCF51EM256 com a aplicação no bloco 2 (0x20000..0x3FFFF).
# argv: arquivo da flash (persiste entre "resets"), modo ("ok" ou "lose": não
# responde a cada 5º comando, mas executa). Termina no RUN ou no fim da entrada.
HARNESS = r"""
#include <stdio.h>
#include <string.h>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif
#define PRISMA_CMD_MAX_PAYLOAD 140U
#include "prisma_frame_stream.h"
#include "prisma_command.h"
#include "prisma_boot.h"

#define BASE 0x20000UL
#define SIZE 0x20000UL
static unsigned char flash[SIZE];
static unsigned long programmed_hole;

static unsigned char erase_page(unsigned long a)
{
    if (a < BASE || a + 0x400UL > BASE + SIZE || (a & 0x3FFUL) != 0UL) { return 0x10U; }
    memset(&flash[a - BASE], 0xFF, 0x400U);
    return 0U;
}
static unsigned char program(unsigned long a, const unsigned char *d, unsigned short n)
{
    unsigned short i;
    if ((a & 3UL) != 0UL || (n & 3U) != 0U || a < BASE || a + n > BASE + SIZE) { return 0x10U; }
    for (i = 0U; i < n; ++i) {
        if (a + i >= 0x203FEUL && a + i < 0x20410UL && d[i] != flash[a + i - BASE]) { ++programmed_hole; }
        flash[a + i - BASE] &= d[i];          /* flash só zera bits */
    }
    return 0U;
}
static const unsigned char *memory(unsigned long a) { return &flash[a - BASE]; }
static void put(unsigned char v) { fputc(v, stdout); }
static void discard(unsigned char v) { (void)v; }

int main(int argc, char **argv)
{
    static const prisma_boot_hal hal = {0x20000UL, 0x40000UL, 0x203FEUL, 0x20410UL, 0x400U,
                                        erase_page, program, memory};
    prisma_boot boot;
    prisma_cmd_parser p;
    FILE *f;
    int c;
    unsigned long commands = 0UL;
    int lose = argc > 2 && strcmp(argv[2], "lose") == 0;

#ifdef _WIN32
    _setmode(0, _O_BINARY);
    _setmode(1, _O_BINARY);
#endif
    memset(flash, 0xFF, sizeof flash);
    flash[0x3FE] = 0x5A;                      /* NV2FTRIM e NV2OPT: devem sobreviver ao apagamento */
    flash[0x40F] = 0x02;
    f = fopen(argv[1], "rb");
    if (f != NULL) { fread(flash, 1, SIZE, f); fclose(f); }
    prisma_boot_init(&boot, &hal);
    prisma_cmd_init(&p);
    while ((c = getchar()) != EOF) {
        if (prisma_cmd_feed(&p, (unsigned char)c)) {
            unsigned char action;
            ++commands;
            /* "lose": executa mas a resposta se perde no caminho. */
            action = prisma_boot_handle(&boot, &p, lose && commands % 5UL == 0UL ? discard : put);
            fflush(stdout);
            if (action == PRISMA_BOOT_RUN_APP) { break; }
        }
    }
    f = fopen(argv[1], "wb");
    fwrite(flash, 1, SIZE, f);
    fclose(f);
    fprintf(stderr, "hole=%lu\n", programmed_hole);
    return 0;
}
"""


@pytest.fixture(scope="module")
def simulator(tmp_path_factory):
    if not shutil.which("gcc"):
        pytest.skip("GCC não instalado")
    folder = tmp_path_factory.mktemp("boot")
    source = folder / "boot.c"
    source.write_text(HARNESS)
    executable = folder / "boot"
    subprocess.run(["gcc", "-std=c89", "-pedantic", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
                    "-Wno-long-long", "-Ifirmware/include", str(source), "-o", str(executable)],
                   cwd=ROOT, check=True, capture_output=True)
    return executable


class Board:
    """Uma "energização" da placa simulada; a flash persiste em ``flash_file``."""

    def __init__(self, executable, flash_file, mode="ok"):
        self.process = subprocess.Popen([str(executable), str(flash_file), mode],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.client = BootClient(StreamTransport(self.process.stdout, self.process.stdin), timeout=0.3)

    def off(self) -> str:
        try:
            self.process.stdin.close()
        except OSError:
            pass  # o RUN já encerrou o simulador
        self.process.wait(10)
        return self.process.stderr.read().decode()

    def flash_bytes(self, flash_file) -> bytes:
        return Path(flash_file).read_bytes()


def srec_line(address: int, data: bytes) -> str:
    body = bytes([len(data) + 5]) + address.to_bytes(4, "big") + data
    return f"S3{body.hex().upper()}{(~sum(body)) & 0xFF:02X}"


def app_srec(size: int = 3000, seed: int = 1) -> str:
    """Aplicação de mentira: SP e PC em big-endian (PC dentro da imagem) e código pseudoaleatório."""
    vectors = struct.pack(">II", 0x00804000, APP + 0x410)
    code = bytes((i * 37 + seed * 11) & 0xFF for i in range(size))
    lines = ["S0030000FC"]
    lines += [srec_line(APP, vectors)]
    lines += [srec_line(APP + 0x410 + o, code[o:o + 32]) for o in range(0, len(code), 32)]
    lines += ["S70500000000FA"]
    return "\n".join(lines) + "\n"


INFO = BootInfo(1, False, PAGE, APP, LIMIT, 128, 0, *HOLE)


def test_gravacao_completa_valida_e_sobrevive_ao_reset(simulator, tmp_path):
    flash_file = tmp_path / "flash.bin"
    image = build_image(parse_srec(app_srec()), INFO)
    board = Board(simulator, flash_file)
    info = board.client.info()
    assert info == INFO
    steps = []
    final = board.client.flash(image, info, progress=lambda *s: steps.append(s[0]))
    assert final.app_valid and steps[-1] == "pronto"
    board.off()  # o RUN encerra o simulador
    flash = flash_file.read_bytes()
    assert flash[0x3FE] == 0x5A and flash[0x40F] == 0x02  # trim e opções do bloco 2 preservados no apagamento
    assert flash[0x3FC:0x3FE] == bytes([0xFF, 0xFF]) and flash[0x410:0x414] != bytes([0xFF] * 4)
    assert flash[:len(image.data)][:8] == image.data[:8]
    # Novo "reset": o bootloader reconhece a aplicação pelo descritor e CRC.
    board = Board(simulator, flash_file)
    assert board.client.info().app_valid
    board.off()


def test_atualizacao_interrompida_fica_no_bootloader_e_repete(simulator, tmp_path):
    flash_file = tmp_path / "flash.bin"
    board = Board(simulator, flash_file)
    board.client.flash(build_image(parse_srec(app_srec(seed=1)), INFO), run=False)
    board.off()

    # Segunda versão: apaga e grava só parte, depois "cai a energia".
    new = build_image(parse_srec(app_srec(size=5000, seed=2)), INFO)
    board = Board(simulator, flash_file)
    client = board.client
    client._check(client.request(CMD_BOOT_ERASE, struct.pack("<IH", APP, 8)), "apagar")
    client.write_chunk(APP, new.data[:128])
    board.off()

    board = Board(simulator, flash_file)
    assert not board.client.info().app_valid  # meia imagem nunca roda
    assert board.client.flash(new, run=False).app_valid
    assert board.client.crc(APP, len(new.data)) == image_crc(new, INFO)
    board.off()


def test_respostas_perdidas_sao_recuperadas_sem_regravar(simulator, tmp_path):
    flash_file = tmp_path / "flash.bin"
    image = build_image(parse_srec(app_srec(size=6000, seed=3)), INFO)
    board = Board(simulator, flash_file, mode="lose")
    assert board.client.flash(image, run=False).app_valid
    assert board.client.resends >= 5
    board.off()


def test_bootloader_recusa_o_que_nao_pode_gravar(simulator, tmp_path):
    board = Board(simulator, tmp_path / "flash.bin")
    c = board.client
    ff = b"\x00" * 8
    assert c.request(CMD_BOOT_WRITE, struct.pack("<I", 0x1F000) + ff).status == REPLY_RANGE   # antes da área
    assert c.request(CMD_BOOT_WRITE, struct.pack("<I", LIMIT) + ff).status == REPLY_RANGE    # descritor
    assert c.request(CMD_BOOT_WRITE, struct.pack("<I", 0x203FC) + ff).status == REPLY_RANGE  # faixa reservada
    assert c.request(CMD_BOOT_WRITE, struct.pack("<I", APP + 2) + ff).status == REPLY_RANGE  # desalinhado
    assert c.request(CMD_BOOT_WRITE, struct.pack("<I", APP) + b"\x00" * 6).status == REPLY_RANGE
    assert c.request(CMD_BOOT_ERASE, struct.pack("<IH", LIMIT, 1)).status == REPLY_RANGE
    assert c.request(CMD_BOOT_ERASE, struct.pack("<IH", APP + 4, 1)).status == REPLY_RANGE
    assert c.request(CMD_BOOT_WRITE, struct.pack("<I", APP + 0x800) + ff).ok
    assert c.request(CMD_BOOT_WRITE, struct.pack("<I", APP + 0x800) + ff).status == REPLY_FLASH  # já gravado
    assert c.request(CMD_BOOT_RUN).status == REPLY_IMAGE  # sem aplicação válida não salta
    reply = c.request(0x24, struct.pack("<II", 0x900, 0x12345678))
    assert reply.status == REPLY_IMAGE and len(reply.data) == 4
    assert c.request(CMD_BOOT_CRC, struct.pack("<II", 0x1000, 4)).status == REPLY_RANGE
    assert c.request(CMD_BOOT_INFO).ok
    assert "hole=0" in board.off()


def test_imagem_recusa_dados_fora_da_area_e_na_faixa_reservada():
    with pytest.raises(ValueError, match="fora da área"):
        build_image(parse_srec(srec_line(0x3FF, b"\xa0") + "\n"), INFO)  # trim do bloco 1
    with pytest.raises(ValueError, match="faixa reservada"):
        build_image(parse_srec(srec_line(0x20400, b"\x00\x00\x00\x00") + "\n"), INFO)
    with pytest.raises(ValueError, match="checksum"):
        parse_srec("S3090002000001020304EE\n")
    image = build_image(parse_srec(app_srec(size=100)), INFO)
    assert image.start == APP and len(image.data) % 4 == 0
    assert image_crc(image, INFO) == crc32(image.data[:0x3FE] + image.data[0x410:])


def test_imagem_do_firmware_atual_e_recusada_por_estar_no_bloco_1():
    s19 = ROOT / "firmware/codewarrior/EM256 Demo/bin/Project.abs.S19"
    if not s19.exists():
        pytest.skip("Firmware não compilado")
    with pytest.raises(ValueError, match="fora da área"):
        build_image(parse_srec(s19.read_text(encoding="ascii")), INFO)


def test_sem_placa_o_cliente_desiste_com_erro_claro():
    class Mute:
        def write(self, data):
            pass

        def read(self, timeout):
            return b""

    with pytest.raises(BootError, match="Sem resposta"):
        BootClient(Mute(), timeout=0.05, retries=1).info()
    assert isinstance(FlashImage(APP, b"\xff" * 4).crc, int)


def _built(project: str) -> dict[int, int]:
    s19 = ROOT / f"firmware/codewarrior/{project}/bin/Project.abs.S19"
    if not s19.exists():
        pytest.skip(f"{project} não compilado (scripts/compilar_demoem.ps1 -Projeto '{project}')")
    return parse_srec(s19.read_text(encoding="ascii"))


def test_aplicacao_compilada_cabe_na_area_do_bootloader():
    image = build_image(_built("EM256 App"), INFO)  # recusa bloco 1 e faixa reservada
    sp, pc = struct.unpack_from(">II", image.data)
    assert APP + 0x410 <= pc < image.end  # _startup dentro da imagem
    assert 0x800400 < sp <= 0x803FF0  # pilha na RAM da aplicação, abaixo do pedido de bootloader
    assert image.end <= APP + 0x10000  # limite de 64 KiB da licença do CodeWarrior


def test_bootloader_compilado_fica_no_bloco_1_com_vetores_e_trim():
    memory = _built("EM256 Boot")
    assert max(memory) < 0x20000
    reset_sp = int.from_bytes(bytes(memory[a] for a in range(0, 4)), "big")
    reset_pc = int.from_bytes(bytes(memory[a] for a in range(4, 8)), "big")
    assert 0x800000 < reset_sp < 0x803FF0 and 0x410 <= reset_pc < 0x20000
    assert memory[0x3FF] == 0xA0  # trim do relógio, como no firmware independente
