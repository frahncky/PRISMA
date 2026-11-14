#include <hidef.h>
#include "derivative.h"

/* PRISMA serial and raw ADC diagnostic for DEMOEM / MCF51EM256.
 * J6 PTC1/TX3 -> CH340 RXD; connect the grounds. RX is not required.
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
#define PRISMA_ICS_TRIM 0xA7U
#endif
#ifndef PRISMA_ICS_FTRIM
#define PRISMA_ICS_FTRIM 0x00U
#endif
const byte prisma_nv_ftrim @0x000003FE = PRISMA_ICS_FTRIM;
const byte prisma_nv_trim  @0x000003FF = PRISMA_ICS_TRIM;

#ifndef PRISMA_SCI_BAUD
#define PRISMA_SCI_BAUD 115200UL
#endif
#define PRISMA_BUS_HZ 19922944UL                 /* 32.768 kHz x 1216 / 2 (FEI, trimmed). */
/* SBR = bus / (16 x baud), rounded: 19200 -> 65 (-0.2 %), 115200 -> 11 (-1.7 %). */
#define SCI3_SBR ((byte)((PRISMA_BUS_HZ / 16UL + PRISMA_SCI_BAUD / 2UL) / PRISMA_SCI_BAUD))
#define ADC_WAIT_LIMIT 2000UL

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

static word burst_data[BURST_SAMPLES][3];
static word burst_seq;

static void MTIM1_Init(void)
{
  MTIM1SC = 0x10U;                            /* TSTP: stop while configuring. */
  MTIM1CLK = (byte)(0x00U | BURST_MTIM_PS);   /* CLKS = bus. */
  MTIM1MOD = BURST_MTIM_MOD;
  MTIM1SC = 0x20U;                            /* TRST: reset, run, no IRQ. */
}

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
  SCI3_PutString("{\"type\":\"status\",\"source\":\"DEMOEM\",\"message\":\"BURST MODE\"}\r\n");

  for (;;) {
    /* One fixed input per ADC avoids high-impedance mux settling artifacts. */
    Burst_Acquire();
    Burst_Send();
    ++burst_seq;
    PTAD_PTAD5 = (byte)!PTAD_PTAD5;
  }
}
