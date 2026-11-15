#include <hidef.h>
#include "derivative.h"

/* PRISMA serial and raw ADC diagnostic for DEMOEM / MCF51EM256.
 * J6 PTC1/TX3 -> CH340 RXD; connect the grounds. RX (CH340 TXD -> J6 PTC0/RX3,
 * J10 on PTC0) is only needed for commands from the PC (prisma_command.h).
 * Terminal: PRISMA_SCI_BAUD (default 115200), 8 data bits, no parity, 1 stop bit.
 * J38 connects the QE8 filtered PWM signals to the EM256 ADC inputs.
 */

/*
 * ICS trim stored in the reserved nonvolatile bytes (0x3FE FTRIM, 0x3FF TRIM).
 * A scripted mass erase removes the factory value, so the image carries its own
 * trim, found on the bench by measuring the SCI baud (scripts/gravar_demoem.ps1).
 * Higher TRIM -> lower ICS frequency.
 */
#ifndef PRISMA_ICS_TRIM
#define PRISMA_ICS_TRIM 0xA0U
#endif
#ifndef PRISMA_ICS_FTRIM
#define PRISMA_ICS_FTRIM 0x00U
#endif
/* 1: imagem para o bootloader (projeto "EM256 App"): ligada em 0x20000, sem
 * vetores nem trims no bloco 1 (são do bootloader), tabela de vetores na RAM e
 * comando 0x04 para reiniciar no bootloader. 0: imagem independente, gravada
 * pelo PEmicro (este projeto). Ver docs/bootloader.md. */
#ifndef PRISMA_APP_IMAGE
#define PRISMA_APP_IMAGE 0
#endif

#if !PRISMA_APP_IMAGE
const byte prisma_nv_ftrim @0x000003FE = PRISMA_ICS_FTRIM;
const byte prisma_nv_trim  @0x000003FF = PRISMA_ICS_TRIM;
#else
/* Cabeçalho lido pelo bootloader: SP e PC iniciais, como um vetor de reset. */
typedef void (*prisma_vector)(void);
extern unsigned long far _SP_INIT[];
extern void _startup(void);
prisma_vector prisma_app_sp @0x00020000 = (prisma_vector)_SP_INIT;
prisma_vector prisma_app_pc @0x00020004 = (prisma_vector)_startup;
#endif

/* Interrupções: na imagem independente o vetor fica na tabela da flash (sintaxe
 * do HCS08 porting support); na imagem do bootloader, a tabela fica na RAM. */
#if PRISMA_APP_IMAGE
#define PRISMA_ISR(vector, name) interrupt void name(void)
#else
#define PRISMA_ISR(vector, name) interrupt vector void name(void)
#endif

#ifndef PRISMA_SCI_BAUD
#define PRISMA_SCI_BAUD 115200UL
#endif
#define PRISMA_BUS_HZ 19922944UL                 /* 32.768 kHz x 1216 / 2 (FEI, trimmed). */
/* SBR = bus / (16 x baud), rounded: 19200 -> 65 (-0.2 %), 115200 -> 11 (-1.7 %). */
#define SCI3_SBR ((byte)((PRISMA_BUS_HZ / 16UL + PRISMA_SCI_BAUD / 2UL) / PRISMA_SCI_BAUD))
#define ADC_WAIT_LIMIT 2000UL

/* 1: rajadas no protocolo binário v2 (A5 5A + CRC16, docs/protocolo.md).
 * 0: rajadas em JSON hex, formato anterior validado em bancada.
 * Mensagens de status continuam em JSON ASCII nos dois modos. */
#ifndef PRISMA_BINARY
#define PRISMA_BINARY 1
#endif
#if PRISMA_BINARY
#include "../../../include/prisma_frame_stream.h"
#endif

/* 1: medição contínua. A interrupção do MTIM1 amostra sem parar e acumula
 * somas por janela de ciclos inteiros (prisma_meter.h); o laço principal envia
 * um resumo por janela (~1 s, quadro 0x02) e uma rajada de forma de onda por
 * resumo (quadro 0x01). Exige PRISMA_BINARY.
 * 0: modo rajada anterior (adquire, para, transmite), validado em bancada. */
#ifndef PRISMA_CONTINUOUS
#define PRISMA_CONTINUOUS 1
#endif
#if PRISMA_CONTINUOUS
#if !PRISMA_BINARY
#error "PRISMA_CONTINUOUS requer PRISMA_BINARY"
#endif
#include "../../../include/prisma_meter.h"
#include "../../../include/prisma_command.h"
#endif

/* Revisão do firmware informada pelo comando INFO: 1 = rajada, 2 = medição
 * contínua, 3 = comandos pela RX3 (rajada configurável e autocalibração do ADC),
 * 4 = imagem do bootloader (comando 0x04). */
#if PRISMA_APP_IMAGE
#define PRISMA_FW_REV 4U
#if !PRISMA_CONTINUOUS
#error "PRISMA_APP_IMAGE requer PRISMA_CONTINUOUS (comandos pela RX3)"
#endif
#else
#define PRISMA_FW_REV 3U
#endif

/* Pedido de "fique no bootloader": palavra no fim da RAM, fora do que as
 * inicializações zeram (as duas imagens terminam a RAM em 0x803FF0). */
#define PRISMA_CMD_ENTER_BOOT 0x04U
#define PRISMA_BOOT_REQUEST (*(volatile unsigned long *)0x00803FF0UL)
#define PRISMA_BOOT_REQUEST_MAGIC 0x424F4F54UL  /* "BOOT" */

/* Canais na medição contínua:
 * 3: tensões AD4/AD5/AD6 (modo validado em bancada).
 * 6: tensões AD4/AD5/AD6 + correntes diferenciais DAD0/DAD1/DAD2 (DADM no GND
 *    pelo J29). Cada ADC converte a tensão e depois a corrente do mesmo par:
 *    ADC3 = AD4 + DAD0, ADC1 = AD5 + DAD1, ADC2 = AD6 + DAD2 (AN3949). */
#ifndef PRISMA_CHANNELS
#if PRISMA_CONTINUOUS
#define PRISMA_CHANNELS 6
#else
#define PRISMA_CHANNELS 3
#endif
#endif
/* Conversões descartadas depois de trocar o canal de um ADC: a troca imediata
 * entre entrada simples e diferencial deixou resíduo na bancada (14/11/2026). */
#ifndef PRISMA_SETTLE
#define PRISMA_SETTLE 1
#endif
#if (PRISMA_CHANNELS != 3) && (PRISMA_CHANNELS != 6)
#error "PRISMA_CHANNELS deve ser 3 ou 6"
#endif
#if (PRISMA_CHANNELS == 6) && !PRISMA_CONTINUOUS
#error "6 canais exigem PRISMA_CONTINUOUS"
#endif
#define BURST_MASK ((byte)(PRISMA_CHANNELS == 6 ? 0x3FU : 0x07U))

static byte adc_timeout;

static void InitSystems(void)
{
  SOPT1 = 0x23;
  SPMSC1 = 0x00;
  SPMSC2 = 0x00;
  SPMSC3 = 0x00;
  SCGC1 = 0xFF;
  SCGC2 = 0xFF;
  SCGC3 = 0xFF;
  SCGC4 = 0xFF;
  SCGC5 = 0xFF;

  /*
   * FEI with the factory-trimmed 32.768 kHz reference, DMX32 enabled and
   * DRS=01 produces about 39.85 MHz ICSOUT / 19.92 MHz peripheral bus.
   */
  ICSTRM = NV1ICSTRM;
  ICSSC_FTRIM = NV1FTRIM_FTRIM;
  ICSC1 = 0x04;
  ICSC2 = 0x00;
  ICSSC = (byte)((ICSSC & 0x1FU) | 0x60U);
  while ((ICSSC & 0x0CU) != 0x00U) {
  }
}

static void SCI3_Init(void)
{
  /* Alternate function 3 selects RX3 on PTC0 and TX3 on PTC1. */
  PTCPF2 = (byte)((PTCPF2 & 0xF0U) | 0x0FU);
  SCI3C2 = 0x00;
  SCI3BDH = 0x00;
  SCI3BDL = SCI3_SBR;
  SCI3C1 = 0x00;
  SCI3C3 = 0x00;                         /* Normal TTL transmit polarity. */
  SCI3C2 = 0x0C;                         /* Enable transmitter and receiver. */
}

static void SCI3_PutChar(char value)
{
  while (SCI3S1_TDRE == 0U) {
  }
  SCI3D = (byte)value;
}

static void SCI3_PutString(const char *text)
{
  while (*text != '\0') {
    SCI3_PutChar(*text++);
  }
}

static void SCI3_PutUnsigned(word value)
{
  char digits[5];
  byte count = 0U;

  do {
    digits[count++] = (char)('0' + (value % 10U));
    value = (word)(value / 10U);
  } while (value != 0U);

  while (count != 0U) {
    SCI3_PutChar(digits[--count]);
  }
}

static void ADC_Init(void)
{
  /* Bus clock / 8, 16-bit mode and long sample time. */
  ADC1CFG1 = 0x7CU;
  ADC2CFG1 = 0x7CU;
  ADC3CFG1 = 0x7CU;
  ADC1CFG2 = 0x00U;
  ADC2CFG2 = 0x00U;
  ADC3CFG2 = 0x00U;
  ADC1SC2 = 0x00U;
  ADC2SC2 = 0x00U;
  ADC3SC2 = 0x00U;
  ADC1SC3 = 0x00U;
  ADC2SC3 = 0x00U;
  ADC3SC3 = 0x00U;
}

/*
 * Hardware self-calibration of the 16-bit ADC: 32-sample hardware average
 * during CAL, then PG/MG = (sum of CLPx/CLMx) / 2 with the MSB set.
 * A set bit in adc_cal_fail means CALF or timeout for ADC1/2/3.
 */
#define ADC_CAL_WAIT_LIMIT 200000UL
#define ADC_CALIBRATE(n, failbit) \
  do { \
    volatile unsigned long cw = ADC_CAL_WAIT_LIMIT; \
    word sum; \
    ADC##n##SC2 = 0x00U; \
    ADC##n##SC3 = 0x07U;                       /* AVGE, 32 samples. */ \
    ADC##n##SC3 = (byte)(ADC##n##SC3 | 0x80U); /* Start CAL. */ \
    while (((ADC##n##SC3 & 0x80U) != 0U) && (cw != 0UL)) { \
      --cw; \
    } \
    if ((cw == 0UL) || ((ADC##n##SC3 & 0x40U) != 0U)) { \
      adc_cal_fail = (byte)(adc_cal_fail | (failbit)); \
    } else { \
      sum = (word)(ADC##n##CLP0 + ADC##n##CLP1 + ADC##n##CLP2 + \
                   ADC##n##CLP3 + ADC##n##CLP4 + ADC##n##CLPS); \
      ADC##n##PG = (word)((sum >> 1) | 0x8000U); \
      sum = (word)(ADC##n##CLM0 + ADC##n##CLM1 + ADC##n##CLM2 + \
                   ADC##n##CLM3 + ADC##n##CLM4 + ADC##n##CLMS); \
      ADC##n##MG = (word)((sum >> 1) | 0x8000U); \
    } \
    ADC##n##SC3 = 0x00U;                       /* Single conversion. */ \
  } while (0)

static byte adc_cal_fail;

static void ADC_Calibrate(void)
{
  adc_cal_fail = 0U;
  ADC_CALIBRATE(1, 0x01U);
  ADC_CALIBRATE(2, 0x02U);
  ADC_CALIBRATE(3, 0x04U);
}

static void SCI3_PutSigned(word value)
{
  /* Differential 16-bit results are two's complement. */
  if ((value & 0x8000U) != 0U) {
    SCI3_PutChar('-');
    value = (word)(~value + 1U);
  }
  SCI3_PutUnsigned(value);
}

static word ADC1_Read(byte channel, byte differential)
{
  volatile unsigned long wait = ADC_WAIT_LIMIT;
  byte selection = (byte)(channel | (differential != 0U ? 0x20U : 0x00U));

  ADC1SC1A = selection;
  while ((ADC1SC1A_COCOA == 0U) && (wait != 0UL)) {
    --wait;
  }
  if (wait == 0UL) {
    adc_timeout = (byte)(adc_timeout | 0x01U);
    return 0U;
  }
  return ADC1RA;
}

static word ADC2_Read(byte channel, byte differential)
{
  volatile unsigned long wait = ADC_WAIT_LIMIT;
  byte selection = (byte)(channel | (differential != 0U ? 0x20U : 0x00U));

  ADC2SC1A = selection;
  while ((ADC2SC1A_COCOA == 0U) && (wait != 0UL)) {
    --wait;
  }
  if (wait == 0UL) {
    adc_timeout = (byte)(adc_timeout | 0x02U);
    return 0U;
  }
  return ADC2RA;
}

static word ADC3_Read(byte channel, byte differential)
{
  volatile unsigned long wait = ADC_WAIT_LIMIT;
  byte selection = (byte)(channel | (differential != 0U ? 0x20U : 0x00U));

  ADC3SC1A = selection;
  while ((ADC3SC1A_COCOA == 0U) && (wait != 0UL)) {
    --wait;
  }
  if (wait == 0UL) {
    adc_timeout = (byte)(adc_timeout | 0x04U);
    return 0U;
  }
  return ADC3RA;
}

/*
 * Burst acquisition: MTIM1 paces BURST_SAMPLES ticks at a fixed rate; on each
 * tick the three ADC modules start together (AD4/ADC3, AD5/ADC1, AD6/ADC2),
 * so the channels are simultaneous within the conversion time. The block is
 * sent afterwards as one JSON line with 4 hex digits per value:
 * {"type":"burst",...,"fs_mhz":F,"n":N,"ch":["ad4","ad5","ad6"],"data":"..."}.
 *
 * Bus ~19.923 MHz (FEI, 32.768 kHz x 1216 / 2). MTIM1 = bus / 128 with
 * MOD = 77 -> 78 counts -> ~1995.5 Hz. fs_mhz is in millihertz and is only as
 * accurate as the internal reference trim (check with the 50/60 Hz source).
 */
#define BURST_SAMPLES 500U
#define BURST_MTIM_PS 7U                      /* 2^7 = 128. */
#define BURST_MTIM_MOD 77U
#define BURST_FS_MHZ 1995487UL                /* 19922944 / 128 / 78 * 1000. */

static word burst_data[BURST_SAMPLES][PRISMA_CHANNELS];
static word burst_seq;

#if PRISMA_CONTINUOUS
/* Janela de ~1 s (amostras inteiras de fs); sem cruzamento, fecha em 1,25 s. */
#define METER_MIN_SAMPLES (BURST_FS_MHZ / 1000UL)
#define METER_MAX_SAMPLES (METER_MIN_SAMPLES + METER_MIN_SAMPLES / 4UL)
#define METER_HYSTERESIS 256U                  /* contagens (~13 mV no pino) */

static prisma_meter meter;
static volatile byte burst_armed;              /* laço pediu uma rajada */
static volatile byte burst_ready;              /* rajada completa, aguardando envio */
static volatile word burst_fill;
static byte burst_every = 1U;                  /* uma rajada a cada N janelas; 0 = nenhuma */
static byte burst_wait;

/* Recepção: a interrupção só guarda o byte; o laço principal interpreta. */
#define RX_SIZE 64U                            /* potência de 2; cabe ~4 comandos */
static volatile byte rx_buf[RX_SIZE];
static volatile byte rx_head;
static byte rx_tail;
static volatile byte rx_errors;                /* overrun, ruído, enquadramento ou buffer cheio */
static prisma_cmd_parser cmd;
static byte adc_cal_result = 0xFFU;            /* 0xFF: autocalibração nunca rodou */
#endif

static void MTIM1_Init(void)
{
  MTIM1SC = 0x10U;                            /* TSTP: stop while configuring. */
  MTIM1CLK = (byte)(0x00U | BURST_MTIM_PS);   /* CLKS = bus. */
  MTIM1MOD = BURST_MTIM_MOD;
  MTIM1SC = 0x20U;                            /* TRST: reset, run, no IRQ. */
}

#if PRISMA_CONTINUOUS
/* Ler S1 e depois D limpa RDRF e OR. Bits de erro: OR 0x08, NF 0x04, FE 0x02, PF 0x01. */
PRISMA_ISR(VectorNumber_Vsci3rx, SCI3_RX_ISR)
{
  byte status = SCI3S1;
  byte value = SCI3D;
  byte next = (byte)((rx_head + 1U) & (RX_SIZE - 1U));

  if (((status & 0x0FU) != 0U) || (next == rx_tail)) {
    if (rx_errors != 0xFFU) {
      ++rx_errors;
    }
  }
  if (next != rx_tail) {
    rx_buf[rx_head] = value;
    rx_head = next;
  }
}

/* Bits de timeout: 0x01 ADC1, 0x02 ADC2, 0x04 ADC3 (COCO ainda zerado). */
static byte ADC_Missing(void)
{
  byte mask = 0U;
  if (ADC1SC1A_COCOA == 0U) { mask = (byte)(mask | 0x01U); }
  if (ADC2SC1A_COCOA == 0U) { mask = (byte)(mask | 0x02U); }
  if (ADC3SC1A_COCOA == 0U) { mask = (byte)(mask | 0x04U); }
  return mask;
}

#if PRISMA_CHANNELS == 6
#define ADC_SC1_VOLTAGE3 4U                    /* AD4, simples */
#define ADC_SC1_VOLTAGE1 5U                    /* AD5 */
#define ADC_SC1_VOLTAGE2 6U                    /* AD6 */
#define ADC_SC1_CURRENT3 0x21U                 /* DAD0, diferencial */
#define ADC_SC1_CURRENT1 0x22U                 /* DAD1 */
#define ADC_SC1_CURRENT2 0x23U                 /* DAD2 */

/* Dispara os três ADCs juntos e espera (~20 us cada conversão de 16 bits). */
static byte ADC_ConvertAll(byte sc3, byte sc1, byte sc2)
{
  volatile word wait = 400U;
  ADC3SC1A = sc3;
  ADC1SC1A = sc1;
  ADC2SC1A = sc2;
  while (((ADC1SC1A_COCOA == 0U) || (ADC2SC1A_COCOA == 0U) || (ADC3SC1A_COCOA == 0U)) && (wait != 0U)) {
    --wait;
  }
  return ADC_Missing();
}

static unsigned short prev_v[3];
static byte have_prev;
#endif

/*
 * Uma amostra por estouro do MTIM1 (~1995,5 Hz), sem parar.
 *
 * 3 canais: lê a conversão disparada no tick anterior (pronta há ~500 us) e
 * dispara a próxima logo em seguida, sem espera ativa.
 *
 * 6 canais: lê as correntes disparadas no fim do tick anterior, converte as
 * tensões agora (com espera) e dispara as correntes, que ficam prontas para o
 * próximo tick. Tensão e corrente do mesmo tick saem juntas com um tick de
 * atraso; a corrente é amostrada ~2 conversões depois da tensão (~40 us com
 * PRISMA_SETTLE 1), corrigido no PC pelo delay_us da calibração. A corrente
 * diferencial (complemento de 2) vai em binário deslocado (+32768), como as
 * tensões, para o núcleo de medição só lidar com valores sem sinal.
 */
/* Sintaxe do porting support HCS08 do projeto: a entrada do vetor 75 sai daqui
 * e substitui a fraca (weak) de exceptions.c. */
PRISMA_ISR(VectorNumber_Vmtim1, MTIM1_ISR)
{
  unsigned short x[PRISMA_CHANNELS];
  byte timeout;
  byte c;

  MTIM1SC = (byte)(MTIM1SC & (byte)~0x80U);   /* Read-then-write clears TOF. */
  timeout = ADC_Missing();
#if PRISMA_CHANNELS == 6
  x[3] = (unsigned short)(ADC3RA ^ 0x8000U);  /* DAD0, tick anterior */
  x[4] = (unsigned short)(ADC1RA ^ 0x8000U);  /* DAD1 */
  x[5] = (unsigned short)(ADC2RA ^ 0x8000U);  /* DAD2 */
#if PRISMA_SETTLE
  timeout = (byte)(timeout | ADC_ConvertAll(ADC_SC1_VOLTAGE3, ADC_SC1_VOLTAGE1, ADC_SC1_VOLTAGE2));
#endif
  timeout = (byte)(timeout | ADC_ConvertAll(ADC_SC1_VOLTAGE3, ADC_SC1_VOLTAGE1, ADC_SC1_VOLTAGE2));
  x[0] = prev_v[0];
  x[1] = prev_v[1];
  x[2] = prev_v[2];
  prev_v[0] = ADC3RA;                         /* AD4, este tick */
  prev_v[1] = ADC1RA;                         /* AD5 */
  prev_v[2] = ADC2RA;                         /* AD6 */
#if PRISMA_SETTLE
  timeout = (byte)(timeout | ADC_ConvertAll(ADC_SC1_CURRENT3, ADC_SC1_CURRENT1, ADC_SC1_CURRENT2));
#endif
  ADC3SC1A = ADC_SC1_CURRENT3;                /* Correntes deste tick: lidas no próximo. */
  ADC1SC1A = ADC_SC1_CURRENT1;
  ADC2SC1A = ADC_SC1_CURRENT2;
  if (have_prev == 0U) {
    have_prev = 1U;                           /* Ainda não há par tensão/corrente. */
    return;
  }
#else
  x[0] = ADC3RA;                              /* AD4 */
  x[1] = ADC1RA;                              /* AD5 */
  x[2] = ADC2RA;                              /* AD6 */
  ADC3SC1A = 4U;
  ADC1SC1A = 5U;
  ADC2SC1A = 6U;
#endif

  prisma_meter_sample(&meter, x, timeout);
  if (burst_armed != 0U) {
    for (c = 0U; c < PRISMA_CHANNELS; ++c) {
      burst_data[burst_fill][c] = x[c];
    }
    adc_timeout = (byte)(adc_timeout | timeout);
    if (++burst_fill >= BURST_SAMPLES) {
      burst_armed = 0U;
      burst_ready = 1U;
    }
  }
}
#endif

static void MTIM1_WaitTick(void)
{
  while (MTIM1SC_TOF == 0U) {
  }
  MTIM1SC = (byte)(MTIM1SC & (byte)~0x80U);   /* Read-then-write clears TOF. */
}

static byte ADC_WaitAll(void)
{
  volatile unsigned long wait = ADC_WAIT_LIMIT;
  byte mask = 0U;

  while (((ADC1SC1A_COCOA == 0U) || (ADC2SC1A_COCOA == 0U) || (ADC3SC1A_COCOA == 0U))
         && (wait != 0UL)) {
    --wait;
  }
  if (ADC1SC1A_COCOA == 0U) { mask = (byte)(mask | 0x01U); }
  if (ADC2SC1A_COCOA == 0U) { mask = (byte)(mask | 0x02U); }
  if (ADC3SC1A_COCOA == 0U) { mask = (byte)(mask | 0x04U); }
  return mask;
}

static void Burst_Acquire(void)
{
  word i;

  adc_timeout = 0U;
  MTIM1SC = 0x20U;                            /* Restart the time base. */
  for (i = 0U; i < BURST_SAMPLES; ++i) {
    MTIM1_WaitTick();
    ADC3SC1A = 4U;                            /* AD4, single-ended. */
    ADC1SC1A = 5U;                            /* AD5. */
    ADC2SC1A = 6U;                            /* AD6. */
    adc_timeout = (byte)(adc_timeout | ADC_WaitAll());
    burst_data[i][0] = ADC3RA;
    burst_data[i][1] = ADC1RA;
    burst_data[i][2] = ADC2RA;
  }
}

static void SCI3_PutHex4(word value)
{
  static const char hex[] = "0123456789ABCDEF";
  byte shift;

  for (shift = 16U; shift != 0U; ) {
    shift = (byte)(shift - 4U);
    SCI3_PutChar(hex[(value >> shift) & 0x0FU]);
  }
}

static void SCI3_PutULong(unsigned long value)
{
  char digits[10];
  byte count = 0U;

  do {
    digits[count++] = (char)('0' + (value % 10UL));
    value /= 10UL;
  } while (value != 0UL);
  while (count != 0U) {
    SCI3_PutChar(digits[--count]);
  }
}

#if PRISMA_BINARY
static void SCI3_PutByte(unsigned char value)
{
  while (SCI3S1_TDRE == 0U) {
  }
  SCI3D = value;
}

/* Protocolo binário v2: 3019 bytes por rajada de 3 canais (contra ~3150 do
 * JSON hex) ou 6019 com 6 canais (~0,52 s a 115200), CRC16 calculado durante
 * o envio, sem buffer extra. */
static void Burst_Send(void)
{
  prisma_stream s;
  word i;
  byte c;

  prisma_stream_begin_burst(&s, SCI3_PutByte, (unsigned long)burst_seq, BURST_FS_MHZ,
                            (unsigned short)BURST_SAMPLES, BURST_MASK, (unsigned char)(adc_timeout & 0x07U));
  for (i = 0U; i < BURST_SAMPLES; ++i) {
    for (c = 0U; c < PRISMA_CHANNELS; ++c) {
      prisma_stream_word(&s, burst_data[i][c]);
    }
  }
  prisma_stream_end(&s);
}
#else
static void Burst_Send(void)
{
  word i;
  byte c;

  SCI3_PutString("{\"type\":\"burst\",\"source\":\"DEMOEM\",\"seq\":");
  SCI3_PutUnsigned(burst_seq);
  SCI3_PutString(",\"fs_mhz\":");
  SCI3_PutULong(BURST_FS_MHZ);
  SCI3_PutString(",\"n\":");
  SCI3_PutUnsigned(BURST_SAMPLES);
  SCI3_PutString(",\"ch\":[\"ad4\",\"ad5\",\"ad6\"],\"adc_timeout_mask\":");
  SCI3_PutUnsigned((word)adc_timeout);
  SCI3_PutString(",\"data\":\"");
  for (i = 0U; i < BURST_SAMPLES; ++i) {
    for (c = 0U; c < 3U; ++c) {
      SCI3_PutHex4(burst_data[i][c]);
    }
  }
  SCI3_PutString("\"}\r\n");
}
#endif

#if PRISMA_APP_IMAGE
/* Tabela de vetores na RAM (o ColdFire V1 só aceita o VBR em 0x0 ou no início
 * da RAM; 0x0 é do bootloader). 115 entradas; o linker começa a RAM em 0x800400. */
#define APP_VBR 0x00800000UL
#define APP_VECTORS 115U
extern void asm_exception_handler(void);

static void App_InstallVectors(void)
{
  unsigned long *table = (unsigned long *)APP_VBR;
  byte i;
  for (i = 0U; i < APP_VECTORS; ++i) {
    table[i] = (unsigned long)asm_exception_handler;
  }
  table[VectorNumber_Vmtim1] = (unsigned long)MTIM1_ISR;
  table[VectorNumber_Vsci3rx] = (unsigned long)SCI3_RX_ISR;
  asm {
    move.l #0x00800000,d0
    dc.w 0x4E7B,0x0801                        /* MOVEC D0,VBR (o assembler embutido não conhece VBR) */
  }
}
#endif

#if PRISMA_CONTINUOUS
/* Prepara a conversão lida no 1º tick, na partida e depois da autocalibração. */
static void Meter_Prime(void)
{
#if PRISMA_CHANNELS == 6
  have_prev = 0U;
  ADC3SC1A = ADC_SC1_CURRENT3;                /* O 1º tick lê "correntes" e descarta. */
  ADC1SC1A = ADC_SC1_CURRENT1;
  ADC2SC1A = ADC_SC1_CURRENT2;
#else
  ADC3SC1A = 4U;                              /* Primeira conversão para o 1º tick. */
  ADC1SC1A = 5U;
  ADC2SC1A = 6U;
#endif
}

/* Autocalibração de hardware com a amostragem parada (alguns ms). A janela em
 * andamento e a rajada pendente são descartadas; o PC vê uma janela perdida. */
static void Meter_CalibrateAdc(void)
{
  MTIM1SC = 0x10U;                            /* TSTP, sem IRQ. */
  ADC_Calibrate();
  adc_cal_result = adc_cal_fail;
  burst_armed = 0U;
  burst_ready = 0U;
  burst_wait = 0U;
  prisma_meter_restart(&meter);
  (void)ADC3_Read(4U, 0U);                    /* Assenta cada módulo no canal fixo. */
  (void)ADC1_Read(5U, 0U);
  (void)ADC2_Read(6U, 0U);
  Meter_Prime();
  MTIM1SC = 0x60U;                            /* TOIE + TRST. */
}

static void Command_Run(void)
{
  unsigned char data[18];
  byte code = cmd.payload[1];
  byte args = prisma_cmd_args(&cmd);

  if ((code == PRISMA_CMD_INFO) && (args == 0U)) {
    data[0] = 1U;                             /* versão do protocolo de comandos */
    data[1] = PRISMA_FW_REV;
    data[2] = PRISMA_CHANNELS;
    data[3] = burst_every;
    prisma_le32(&data[4], BURST_FS_MHZ);
    prisma_le16(&data[8], BURST_SAMPLES);
    data[10] = adc_cal_result;
    data[11] = rx_errors;
    prisma_le16(&data[12], cmd.errors);
    prisma_le32(&data[14], meter.windows);    /* leitura de 32 bits alinhada: atômica */
    prisma_cmd_reply(SCI3_PutByte, &cmd, PRISMA_REPLY_OK, data, 18U);
  } else if ((code == PRISMA_CMD_BURST) && (args == 1U)) {
    burst_every = cmd.payload[2];
    burst_wait = 0U;
    data[0] = burst_every;
    prisma_cmd_reply(SCI3_PutByte, &cmd, PRISMA_REPLY_OK, data, 1U);
  } else if ((code == PRISMA_CMD_ADC_CAL) && (args == 0U)) {
    Meter_CalibrateAdc();
    data[0] = adc_cal_result;
    prisma_cmd_reply(SCI3_PutByte, &cmd, PRISMA_REPLY_OK, data, 1U);
#if PRISMA_APP_IMAGE
  } else if ((code == PRISMA_CMD_ENTER_BOOT) && (args == 0U)) {
    prisma_cmd_reply(SCI3_PutByte, &cmd, PRISMA_REPLY_OK, data, 0U);
    while (SCI3S1_TC == 0U) {                 /* a resposta sai inteira antes do reset */
    }
    DisableInterrupts;
    PRISMA_BOOT_REQUEST = PRISMA_BOOT_REQUEST_MAGIC;
    asm { dc.w 0x4AFC }                       /* ILLEGAL: reset (CPUCR.IRD = 0 depois do reset) */
#endif
  } else {
    prisma_cmd_reply(SCI3_PutByte, &cmd,
                     (((code >= PRISMA_CMD_INFO) && (code <= PRISMA_CMD_ADC_CAL)) || (code == PRISMA_CMD_ENTER_BOOT))
                       ? PRISMA_REPLY_BAD_ARGS : PRISMA_REPLY_UNKNOWN,
                     data, 0U);
  }
}

static void Command_Poll(void)
{
  while (rx_tail != rx_head) {
    byte value = rx_buf[rx_tail];
    rx_tail = (byte)((rx_tail + 1U) & (RX_SIZE - 1U));
    if (prisma_cmd_feed(&cmd, value) != 0U) {
      Command_Run();
    }
  }
}
#endif

void main(void)
{
  InitSystems();
  SCI3_Init();
  SCI3_PutString("{\"type\":\"status\",\"source\":\"DEMOEM\",\"message\":\"BOOT\"}\r\n");
  ADC_Init();
  SCI3_PutString("{\"type\":\"status\",\"source\":\"DEMOEM\",\"message\":\"ADC CONFIG OK\"}\r\n");
  /* Hardware calibration remains opt-in: it must never block bring-up. */
  adc_cal_fail = 0U;

  PTAD_PTAD5 = 0;
  PTADD_PTADD5 = 1;

  MTIM1_Init();
  /* Settle each module on its fixed channel before the first burst. */
  (void)ADC3_Read(4U, 0U);
  (void)ADC1_Read(5U, 0U);
  (void)ADC2_Read(6U, 0U);
#if PRISMA_CONTINUOUS
#if PRISMA_CHANNELS == 6
  SCI3_PutString("{\"type\":\"status\",\"source\":\"DEMOEM\",\"message\":\"CONTINUOUS MODE 6CH\"}\r\n");
#else
  SCI3_PutString("{\"type\":\"status\",\"source\":\"DEMOEM\",\"message\":\"CONTINUOUS MODE\"}\r\n");
#endif
  Meter_Prime();
  prisma_meter_init(&meter, PRISMA_CHANNELS, METER_MIN_SAMPLES, METER_MAX_SAMPLES, METER_HYSTERESIS);
  prisma_cmd_init(&cmd);
  burst_armed = 0U;
  burst_ready = 0U;
  rx_head = 0U;
  rx_tail = 0U;
  rx_errors = 0U;
  (void)SCI3S1;                               /* Limpa RDRF/OR de lixo da partida. */
  (void)SCI3D;
  SCI3C2 = (byte)(SCI3C2 | SCI3C2_RIE_MASK);  /* Interrupção de recepção. */
#if PRISMA_APP_IMAGE
  App_InstallVectors();
#endif
  MTIM1SC = 0x60U;                            /* TOIE + TRST: run with IRQ. */
  EnableInterrupts;

  for (;;) {
    Command_Poll();                           /* Respostas saem entre um quadro e outro. */
    if (meter.ready_flag != 0U) {
      prisma_meter_window window;
      DisableInterrupts;                      /* Cópia sem a interrupção no meio. */
      window = meter.ready;
      meter.ready_flag = 0U;
      EnableInterrupts;
      prisma_meter_send(&window, PRISMA_CHANNELS, SCI3_PutByte, BURST_FS_MHZ);
      if (burst_wait != 0xFFU) {
        ++burst_wait;
      }
      if ((burst_every != 0U) && (burst_wait >= burst_every) && (burst_armed == 0U) && (burst_ready == 0U)) {
        burst_wait = 0U;
        adc_timeout = 0U;
        burst_fill = 0U;
        burst_armed = 1U;                     /* Próximos 500 ticks viram rajada. */
      }
    }
    if (burst_ready != 0U) {
      Burst_Send();                           /* ~0,26 s a 115200; a amostragem segue. */
      ++burst_seq;
      burst_ready = 0U;
      PTAD_PTAD5 = (byte)!PTAD_PTAD5;
    }
  }
#else
  SCI3_PutString("{\"type\":\"status\",\"source\":\"DEMOEM\",\"message\":\"BURST MODE\"}\r\n");

  for (;;) {
    /* One fixed input per ADC avoids high-impedance mux settling artifacts. */
    Burst_Acquire();
    Burst_Send();
    ++burst_seq;
    PTAD_PTAD5 = (byte)!PTAD_PTAD5;
  }
#endif
}
