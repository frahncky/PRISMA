#ifndef PRISMA_FRAME_STREAM_H
#define PRISMA_FRAME_STREAM_H
/* Envio em fluxo de um quadro de rajada PRISMA v2, sem buffer de saída.
 *
 * Mesmo formato de prisma_frame.c, mas cada byte vai direto para put_byte e o
 * CRC é calculado durante o envio: útil quando a RAM só comporta a própria
 * rajada. Só usa tipos C89 (sem stdint.h) para compilar no CodeWarrior 6.3.
 *
 *   prisma_stream s;
 *   prisma_stream_begin_burst(&s, put, seq, fs_mhz, n, mask, flags);
 *   para cada valor: prisma_stream_word(&s, valor);
 *   prisma_stream_end(&s);
 */

typedef void (*prisma_put_byte_fn)(unsigned char value);

typedef struct {
    prisma_put_byte_fn put;
    unsigned short crc;
} prisma_stream;

static void prisma_stream_byte(prisma_stream *s, unsigned char value)
{
    unsigned char bit;
    unsigned int crc = (unsigned int)s->crc ^ ((unsigned int)value << 8);
    for (bit = 0U; bit < 8U; ++bit) {
        crc = (crc & 0x8000U) ? ((crc << 1) ^ 0x1021U) : (crc << 1);
    }
    s->crc = (unsigned short)(crc & 0xFFFFU);
    s->put(value);
}

static void prisma_stream_word(prisma_stream *s, unsigned short value)
{
    prisma_stream_byte(s, (unsigned char)(value & 0xFFU));
    prisma_stream_byte(s, (unsigned char)(value >> 8));
}

static void prisma_stream_long(prisma_stream *s, unsigned long value)
{
    prisma_stream_word(s, (unsigned short)(value & 0xFFFFUL));
    prisma_stream_word(s, (unsigned short)((value >> 16) & 0xFFFFUL));
}

/* n de 2 a 4096; mask 0x07 (3 canais) ou 0x3F (6 canais). Sem validação:
 * os parâmetros são constantes do firmware. */
static void prisma_stream_begin_burst(prisma_stream *s, prisma_put_byte_fn put, unsigned long seq,
                                      unsigned long fs_mhz, unsigned short n, unsigned char mask,
                                      unsigned char flags)
{
    unsigned short channels = (unsigned short)(mask == 0x3FU ? 6U : 3U);
    s->put = put;
    put(0xA5U);
    put(0x5AU);
    s->crc = 0xFFFFU;
    prisma_stream_byte(s, 0x01U);
    prisma_stream_word(s, (unsigned short)(12U + 2U * n * channels));
    prisma_stream_long(s, seq);
    prisma_stream_long(s, fs_mhz);
    prisma_stream_word(s, n);
    prisma_stream_byte(s, mask);
    prisma_stream_byte(s, flags);
}

static void prisma_stream_end(prisma_stream *s)
{
    unsigned short crc = s->crc;
    s->put((unsigned char)(crc & 0xFFU));
    s->put((unsigned char)(crc >> 8));
}
#endif
