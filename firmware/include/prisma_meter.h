#ifndef PRISMA_METER_H
#define PRISMA_METER_H
/* Medição contínua PRISMA: somas por janela de ciclos inteiros.
 *
 * Chamado a cada amostra (na interrupção do timer), acumula por canal a soma
 * e a soma dos quadrados das contagens e, com correntes, a soma de v × i por
 * fase. A janela fecha no primeiro cruzamento ascendente da fase A depois de
 * min_samples, então cobre um número inteiro de ciclos; as janelas são
 * contíguas, sem amostra perdida entre elas. Sem cruzamento (sinal DC ou
 * ausente) a janela fecha em max_samples com PRISMA_METER_FLAG_NO_SYNC.
 *
 * O computador calcula RMS, frequência e potência com aritmética exata:
 *   RMS AC² = (n·Σx² − (Σx)²) / n²     P = (n·Σvi − Σv·Σi) / n²
 *   f = (ciclos − 1) × fs / (period_q8 / 256)
 * period_q8 vai do primeiro cruzamento dentro da janela até o que a fecha:
 * os dois usam o mesmo limiar (a média de A só muda quando a janela fecha).
 * Nada de ponto flutuante aqui: o ColdFire V1 não tem FPU.
 *
 * C89 + unsigned long long (CodeWarrior 6.3 e gcc -Wno-long-long).
 *
 *   prisma_meter m;
 *   prisma_meter_init(&m, 3, fs, fs + fs / 4, 256);
 *   na interrupção: prisma_meter_sample(&m, x, flags_do_adc);
 *   no laço: if (m.ready_flag) { copiar m.ready; m.ready_flag = 0; enviar }
 */
/* Sem #include aqui: o IDE do CodeWarrior 6.3 resolve includes relativos ao .c
 * e trava ao varrer um include aninhado que não acha. Inclua antes, como o
 * main.c da DEMOEM: #include ".../prisma_frame_stream.h" */
#ifndef PRISMA_FRAME_STREAM_H
#error "Inclua prisma_frame_stream.h antes de prisma_meter.h"
#endif

#define PRISMA_FRAME_SUMMARY 0x02U
#define PRISMA_METER_FLAG_NO_SYNC 0x08U  /* janela fechada por tempo, sem ciclos */
#define PRISMA_METER_FLAG_OVERRUN 0x10U  /* a janela anterior não foi lida a tempo */
#define PRISMA_SUMMARY_HEADER_BYTES 20U

typedef unsigned long long prisma_u64;

typedef struct {
    unsigned long seq;        /* número da janela (salta se alguma for perdida) */
    unsigned long n;          /* amostras */
    unsigned long sum[6];
    prisma_u64 sumsq[6];
    prisma_u64 sumvi[3];      /* va·ia, vb·ib, vc·ic (só com 6 canais) */
    unsigned long period_q8;  /* do 1º cruzamento interno ao de fechamento, em 1/256 de amostra */
    unsigned short cycles;    /* ciclos inteiros da janela (cruzamentos depois da abertura) */
    unsigned char flags;      /* bits 0-2: timeout ADC; NO_SYNC; OVERRUN */
} prisma_meter_window;

typedef struct {
    prisma_meter_window acc;      /* janela em andamento (só a interrupção mexe) */
    prisma_meter_window ready;    /* última janela fechada, válida com ready_flag */
    volatile unsigned char ready_flag;
    unsigned char channels;       /* 3 (tensões) ou 6 (tensões e correntes) */
    unsigned char armed;          /* A passou abaixo de threshold − hysteresis */
    unsigned char synced;         /* first_q8 marca o início da janela */
    unsigned char carry_flags;
    unsigned short hysteresis;
    unsigned short threshold;     /* média de A na janela anterior */
    unsigned short prev_a;
    unsigned long windows;
    unsigned long min_samples;
    unsigned long max_samples;
    unsigned long clock_q8;       /* tempo da amostra atual × 256 (módulo 2^32) */
    unsigned long inner_q8;       /* primeiro cruzamento depois da abertura */
} prisma_meter;

static void prisma_meter_clear(prisma_meter_window *w)
{
    unsigned char c;
    w->n = 0UL;
    for (c = 0U; c < 6U; ++c) {
        w->sum[c] = 0UL;
        w->sumsq[c] = 0U;
    }
    for (c = 0U; c < 3U; ++c) {
        w->sumvi[c] = 0U;
    }
    w->period_q8 = 0UL;
    w->cycles = 0U;
    w->flags = 0U;
}

static void prisma_meter_init(prisma_meter *m, unsigned char channels, unsigned long min_samples,
                              unsigned long max_samples, unsigned short hysteresis)
{
    prisma_meter_clear(&m->acc);
    prisma_meter_clear(&m->ready);
    m->ready_flag = 0U;
    m->channels = (unsigned char)(channels == 6U ? 6U : 3U);
    m->armed = 0U;
    m->synced = 0U;
    m->carry_flags = 0U;
    m->hysteresis = hysteresis;
    m->threshold = 0x8000U;
    m->prev_a = 0x8000U;
    m->windows = 0UL;
    m->min_samples = min_samples;
    m->max_samples = max_samples;
    m->clock_q8 = 0UL;
    m->inner_q8 = 0UL;
}

/* Fecha a janela em andamento: entrega se a anterior já foi lida. */
static void prisma_meter_publish(prisma_meter *m, unsigned char extra_flags)
{
    m->acc.seq = m->windows++;
    m->acc.flags = (unsigned char)(m->acc.flags | extra_flags | m->carry_flags);
    if (m->ready_flag != 0U) {
        m->carry_flags = PRISMA_METER_FLAG_OVERRUN;  /* esta janela se perde */
    } else {
        m->ready = m->acc;
        m->ready_flag = 1U;
        m->carry_flags = 0U;
    }
    if (m->acc.n != 0UL) {
        m->threshold = (unsigned short)(m->acc.sum[0] / m->acc.n);
    }
    prisma_meter_clear(&m->acc);
}

static void prisma_meter_sample(prisma_meter *m, const unsigned short *x, unsigned char flags)
{
    unsigned char c;
    unsigned short a = x[0];
    unsigned long t_q8 = 0UL;
    unsigned char crossed = 0U;

    /* Cruzamento ascendente de A pela média, com histerese contra ruído. */
    if ((unsigned long)a + m->hysteresis < (unsigned long)m->threshold) {
        m->armed = 1U;
    } else if (m->armed != 0U && a >= m->threshold && m->prev_a < m->threshold) {
        /* Instante entre a amostra anterior e esta, por interpolação linear. */
        t_q8 = m->clock_q8 - 256UL
             + (((unsigned long)(m->threshold - m->prev_a) << 8) / (unsigned long)(a - m->prev_a));
        crossed = 1U;
        m->armed = 0U;
    }

    if (crossed != 0U) {
        if (m->synced == 0U) {
            prisma_meter_clear(&m->acc);  /* descarta o trecho antes do primeiro ciclo */
            m->synced = 1U;
        } else {
            m->acc.cycles = (unsigned short)(m->acc.cycles + 1U);
            if (m->acc.cycles == 1U) {
                m->inner_q8 = t_q8;
            }
            if (m->acc.n >= m->min_samples) {
                m->acc.period_q8 = m->acc.cycles >= 2U ? t_q8 - m->inner_q8 : 0UL;
                prisma_meter_publish(m, 0U);
            }
        }
    } else if (m->acc.n >= m->max_samples) {
        m->acc.cycles = 0U;
        m->acc.period_q8 = 0UL;
        prisma_meter_publish(m, PRISMA_METER_FLAG_NO_SYNC);
        m->synced = 0U;
    }

    /* A amostra logo depois do cruzamento abre a janela nova. */
    for (c = 0U; c < m->channels; ++c) {
        unsigned long v = (unsigned long)x[c];
        m->acc.sum[c] += v;
        m->acc.sumsq[c] += (prisma_u64)(v * v);  /* 65535² cabe em 32 bits */
    }
    if (m->channels == 6U) {
        for (c = 0U; c < 3U; ++c) {
            m->acc.sumvi[c] += (prisma_u64)((unsigned long)x[c] * (unsigned long)x[c + 3U]);
        }
    }
    ++m->acc.n;
    m->acc.flags = (unsigned char)(m->acc.flags | (flags & 0x07U));
    m->prev_a = a;
    m->clock_q8 += 256UL;
}

static void prisma_stream_u64(prisma_stream *s, prisma_u64 value)
{
    prisma_stream_long(s, (unsigned long)(value & 0xFFFFFFFFUL));
    prisma_stream_long(s, (unsigned long)(value >> 32));
}

/* Quadro v2 tipo 0x02, little-endian:
 *   seq u32 | fs_mhz u32 | n u32 | máscara u8 | flags u8 | ciclos u16 | period_q8 u32
 *   por canal: Σx u32, Σx² u64      com 6 canais: Σvi u64 × 3 (fases A, B, C) */
static void prisma_meter_send(const prisma_meter_window *w, unsigned char channels,
                              prisma_put_byte_fn put, unsigned long fs_mhz)
{
    prisma_stream s;
    unsigned char c;
    unsigned short length = (unsigned short)(PRISMA_SUMMARY_HEADER_BYTES + 12U * channels
                                             + (channels == 6U ? 24U : 0U));

    prisma_stream_begin(&s, put, PRISMA_FRAME_SUMMARY, length);
    prisma_stream_long(&s, w->seq);
    prisma_stream_long(&s, fs_mhz);
    prisma_stream_long(&s, w->n);
    prisma_stream_byte(&s, (unsigned char)(channels == 6U ? 0x3FU : 0x07U));
    prisma_stream_byte(&s, w->flags);
    prisma_stream_word(&s, w->cycles);
    prisma_stream_long(&s, w->period_q8);
    for (c = 0U; c < channels; ++c) {
        prisma_stream_long(&s, w->sum[c]);
        prisma_stream_u64(&s, w->sumsq[c]);
    }
    if (channels == 6U) {
        for (c = 0U; c < 3U; ++c) {
            prisma_stream_u64(&s, w->sumvi[c]);
        }
    }
    prisma_stream_end(&s);
}
#endif
