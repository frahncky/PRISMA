#ifndef PRISMA_COMMAND_H
#define PRISMA_COMMAND_H
/* Comandos PC -> placa pela mesma serial dos quadros v2.
 *
 * Comando (tipo 0x10): A5 5A | 10 | len u16 | id u8, código u8, argumentos | CRC16
 * Resposta (tipo 0x11): A5 5A | 11 | len u16 | id u8, código u8, estado u8, dados | CRC16
 *
 * O id é escolhido pelo PC e volta na resposta, para casar pedido e resposta.
 * Estado: 0 = ok, 1 = código desconhecido, 2 = argumentos inválidos.
 * Um comando com CRC errado é descartado sem resposta: o PC repete por tempo.
 *
 * O parser recebe um byte por vez (fora da interrupção, a partir de um buffer
 * circular enchido pela RX) e só guarda o payload do comando em andamento.
 * C89 sem stdint.h, como prisma_frame_stream.h; testado no PC com gcc em
 * tests/test_board_commands.py.
 *
 *   prisma_cmd_parser p;
 *   prisma_cmd_init(&p);
 *   para cada byte: if (prisma_cmd_feed(&p, b)) { tratar p.payload[1]; prisma_cmd_reply(...); }
 */
/* Sem #include aqui (ver prisma_meter.h): inclua prisma_frame_stream.h antes. */
#ifndef PRISMA_FRAME_STREAM_H
#error "Inclua prisma_frame_stream.h antes de prisma_command.h"
#endif

#define PRISMA_FRAME_COMMAND 0x10U
#define PRISMA_FRAME_REPLY 0x11U
#ifndef PRISMA_CMD_MAX_PAYLOAD
#define PRISMA_CMD_MAX_PAYLOAD 16U       /* id + código + até 14 bytes; o bootloader define 140 (escrita de 128) */
#endif

#define PRISMA_CMD_INFO 0x01U            /* identifica firmware, canais e contadores */
#define PRISMA_CMD_BURST 0x02U           /* u8: uma rajada a cada N janelas (0 = sem rajadas) */
#define PRISMA_CMD_ADC_CAL 0x03U         /* autocalibração de hardware dos três ADCs */

#define PRISMA_REPLY_OK 0x00U
#define PRISMA_REPLY_UNKNOWN 0x01U
#define PRISMA_REPLY_BAD_ARGS 0x02U

#define PRISMA_CMD_SYNC1 0U
#define PRISMA_CMD_SYNC2 1U
#define PRISMA_CMD_TYPE 2U
#define PRISMA_CMD_LEN_L 3U
#define PRISMA_CMD_LEN_H 4U
#define PRISMA_CMD_PAYLOAD 5U
#define PRISMA_CMD_CRC_L 6U
#define PRISMA_CMD_CRC_H 7U

typedef struct {
    unsigned char state;
    unsigned char length;                /* bytes do payload (2..PRISMA_CMD_MAX_PAYLOAD) */
    unsigned char pos;
    unsigned short crc;
    unsigned short received_crc;
    unsigned short errors;               /* cabeçalho inválido ou CRC errado (satura em 65535) */
    unsigned char payload[PRISMA_CMD_MAX_PAYLOAD];
} prisma_cmd_parser;

static unsigned short prisma_crc16_update(unsigned short crc, unsigned char value)
{
    unsigned char bit;
    unsigned int c = (unsigned int)crc ^ ((unsigned int)value << 8);
    for (bit = 0U; bit < 8U; ++bit) {
        c = (c & 0x8000U) ? ((c << 1) ^ 0x1021U) : (c << 1);
    }
    return (unsigned short)(c & 0xFFFFU);
}

static void prisma_cmd_init(prisma_cmd_parser *p)
{
    p->state = PRISMA_CMD_SYNC1;
    p->length = 0U;
    p->pos = 0U;
    p->crc = 0xFFFFU;
    p->received_crc = 0U;
    p->errors = 0U;
}

/* Descarta o quadro em andamento; um A5 já pode ser o início do próximo. */
static void prisma_cmd_reject(prisma_cmd_parser *p, unsigned char value)
{
    if (p->errors != 0xFFFFU) {
        ++p->errors;
    }
    p->state = (unsigned char)(value == 0xA5U ? PRISMA_CMD_SYNC2 : PRISMA_CMD_SYNC1);
}

/* Devolve 1 quando um comando completo e com CRC válido está em p->payload
 * (p->length bytes: id, código, argumentos). */
static unsigned char prisma_cmd_feed(prisma_cmd_parser *p, unsigned char value)
{
    switch (p->state) {
    case PRISMA_CMD_SYNC1:
        if (value == 0xA5U) {
            p->state = PRISMA_CMD_SYNC2;
        }
        break;
    case PRISMA_CMD_SYNC2:
        p->state = (unsigned char)(value == 0x5AU ? PRISMA_CMD_TYPE
                                   : (value == 0xA5U ? PRISMA_CMD_SYNC2 : PRISMA_CMD_SYNC1));
        break;
    case PRISMA_CMD_TYPE:
        if (value != PRISMA_FRAME_COMMAND) {
            prisma_cmd_reject(p, value);
        } else {
            p->crc = prisma_crc16_update(0xFFFFU, value);
            p->state = PRISMA_CMD_LEN_L;
        }
        break;
    case PRISMA_CMD_LEN_L:
        p->length = value;
        p->crc = prisma_crc16_update(p->crc, value);
        p->state = PRISMA_CMD_LEN_H;
        break;
    case PRISMA_CMD_LEN_H:
        if (value != 0U || p->length < 2U || p->length > PRISMA_CMD_MAX_PAYLOAD) {
            prisma_cmd_reject(p, value);
        } else {
            p->crc = prisma_crc16_update(p->crc, value);
            p->pos = 0U;
            p->state = PRISMA_CMD_PAYLOAD;
        }
        break;
    case PRISMA_CMD_PAYLOAD:
        p->payload[p->pos++] = value;
        p->crc = prisma_crc16_update(p->crc, value);
        if (p->pos >= p->length) {
            p->state = PRISMA_CMD_CRC_L;
        }
        break;
    case PRISMA_CMD_CRC_L:
        p->received_crc = value;
        p->state = PRISMA_CMD_CRC_H;
        break;
    default:
        p->received_crc = (unsigned short)(p->received_crc | ((unsigned short)value << 8));
        p->state = PRISMA_CMD_SYNC1;
        if (p->received_crc == p->crc) {
            return 1U;
        }
        if (p->errors != 0xFFFFU) {
            ++p->errors;
        }
        break;
    }
    return 0U;
}

/* Bytes de argumento do comando recebido. */
static unsigned char prisma_cmd_args(const prisma_cmd_parser *p)
{
    return (unsigned char)(p->length - 2U);
}

static void prisma_cmd_reply(prisma_put_byte_fn put, const prisma_cmd_parser *p, unsigned char status,
                             const unsigned char *data, unsigned char length)
{
    prisma_stream s;
    unsigned char i;
    prisma_stream_begin(&s, put, PRISMA_FRAME_REPLY, (unsigned short)(3U + length));
    prisma_stream_byte(&s, p->payload[0]);
    prisma_stream_byte(&s, p->payload[1]);
    prisma_stream_byte(&s, status);
    for (i = 0U; i < length; ++i) {
        prisma_stream_byte(&s, data[i]);
    }
    prisma_stream_end(&s);
}

/* Little-endian em buffer, para montar os dados da resposta. */
static void prisma_le16(unsigned char *out, unsigned short value)
{
    out[0] = (unsigned char)(value & 0xFFU);
    out[1] = (unsigned char)(value >> 8);
}

static void prisma_le32(unsigned char *out, unsigned long value)
{
    prisma_le16(out, (unsigned short)(value & 0xFFFFUL));
    prisma_le16(out + 2, (unsigned short)((value >> 16) & 0xFFFFUL));
}
#endif
