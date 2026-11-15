/* DEMOEM simulada para os testes do gateway (tests/test_gateway.py).
 *
 * Usa o núcleo real do bootloader (firmware/include/prisma_boot.h) com uma flash
 * em memória. Modos:
 *   boot  - a placa já está no bootloader;
 *   app   - a aplicação roda: responde "código desconhecido" a tudo, menos ao
 *           0x04, que "reinicia" a placa no bootloader;
 *   lose  - bootloader que executa todo 5º comando mas perde a resposta;
 *   noisy - bootloader que manda um resumo, uma linha JSON e uma rajada com CRC
 *           errado antes de cada resposta (como a aplicação no meio do fluxo).
 */
#include <string.h>

#define PRISMA_CMD_MAX_PAYLOAD 140U
#include "prisma_frame_stream.h"
#include "prisma_command.h"
#include "prisma_boot.h"
#include "board_sim.h"

#define BASE 0x20000UL
#define SIZE 0x20000UL
static unsigned char flash[SIZE];
static unsigned long hole_writes;
static unsigned char out[1 << 16];
static unsigned long out_head, out_tail;
static prisma_boot boot;
static prisma_cmd_parser parser;
static int mode, in_app;
static unsigned long commands;

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
        if (a + i >= 0x203FEUL && a + i < 0x20410UL && d[i] != flash[a + i - BASE]) { ++hole_writes; }
        flash[a + i - BASE] &= d[i];
    }
    return 0U;
}
static const unsigned char *memory(unsigned long a) { return &flash[a - BASE]; }
static const prisma_boot_hal hal = {0x20000UL, 0x40000UL, 0x203FEUL, 0x20410UL, 0x400U,
                                    erase_page, program, memory};

static void put(unsigned char v) { out[out_head++ & 0xFFFFUL] = v; }
static void discard(unsigned char v) { (void)v; }

static void noise(void)
{
    static const char json[] = "{\"type\":\"status\",\"source\":\"DEMOEM\"}\r\n";
    prisma_stream s;
    unsigned char i;
    const char *c;
    prisma_stream_begin(&s, put, 0x02U, 20U + 36U);   /* resumo de 3 canais com somas zeradas */
    prisma_stream_long(&s, 7UL);
    prisma_stream_long(&s, 1995487UL);
    prisma_stream_long(&s, 2000UL);
    prisma_stream_byte(&s, 0x07U);
    prisma_stream_byte(&s, 0x08U);
    prisma_stream_word(&s, 0U);
    prisma_stream_long(&s, 0UL);
    for (i = 0U; i < 36U; ++i) { prisma_stream_byte(&s, 0U); }
    prisma_stream_end(&s);
    for (c = json; *c != '\0'; ++c) { put((unsigned char)*c); }
    put(0xA5U); put(0x5AU); put(0x01U); put(4U); put(0U);  /* rajada truncada com CRC errado */
    put(1U); put(2U); put(3U); put(4U); put(0U); put(0U);
}

void sim_start(const char *name)
{
    mode = strcmp(name, "lose") == 0 ? 1 : (strcmp(name, "noisy") == 0 ? 2 : 0);
    in_app = strcmp(name, "app") == 0;
    commands = 0UL;
    out_head = out_tail = 0UL;
    prisma_boot_init(&boot, &hal);
    prisma_cmd_init(&parser);
}

void sim_erase_all(void)
{
    memset(flash, 0xFF, sizeof flash);
    flash[0x3FE] = 0x5A;                      /* NV2FTRIM e NV2OPT: devem sobreviver */
    flash[0x40F] = 0x02;
    hole_writes = 0UL;
}

void sim_feed(unsigned char value)
{
    if (!prisma_cmd_feed(&parser, value)) { return; }
    ++commands;
    if (in_app) {
        if (parser.payload[1] == 0x04U) {
            prisma_cmd_reply(put, &parser, PRISMA_REPLY_OK, 0, 0U);
            in_app = 0;                       /* reinicia no bootloader */
            prisma_boot_init(&boot, &hal);
        } else {
            prisma_cmd_reply(put, &parser, PRISMA_REPLY_UNKNOWN, 0, 0U);
        }
        return;
    }
    if (mode == 2) { noise(); }
    if (prisma_boot_handle(&boot, &parser, mode == 1 && commands % 5UL == 0UL ? discard : put)
        == PRISMA_BOOT_RUN_APP) {
        in_app = 1;
    }
}

int sim_read(void)
{
    if (out_tail == out_head) { return -1; }
    return out[out_tail++ & 0xFFFFUL];
}

int sim_in_app(void) { return in_app; }
int sim_app_valid(void) { prisma_boot_init(&boot, &hal); return boot.app_valid; }
unsigned long sim_hole_writes(void) { return hole_writes; }
unsigned char sim_flash_at(unsigned long offset) { return flash[offset]; }
