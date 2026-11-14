#include <hidef.h>
#include "derivative.h"

/* PRISMA serial and raw ADC diagnostic for DEMOEM / MCF51EM256.
 * J6 PTC1/TX3 -> CH340 RXD; connect the grounds. RX is not required.
 * Terminal: 19200 baud, 8 data bits, no parity, 1 stop bit.
 * J38 connects the QE8 filtered PWM signals to the EM256 ADC inputs.
 */

#define SCI3_SBR_19200_AT_19MHZ 65U
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
  SCI3BDL = SCI3_SBR_19200_AT_19MHZ;
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

static void Delay(void)
{
  volatile unsigned long count;

  for (count = 0UL; count < 350000UL; ++count) {
  }
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

  for (;;) {
    word ad4;
    word ad5;
    word ad6;

    adc_timeout = 0U;
    /* One fixed input per ADC avoids high-impedance mux settling artifacts. */
    ad4 = ADC3_Read(4U, 0U);
    ad5 = ADC1_Read(5U, 0U);
    ad6 = ADC2_Read(6U, 0U);
    SCI3_PutString("{\"type\":\"status\",\"source\":\"DEMOEM\",\"message\":\"ADC RAW 3PH\",\"adc\":{\"ad4_raw\":");
    SCI3_PutUnsigned(ad4);
    SCI3_PutString(",\"ad5_raw\":");
    SCI3_PutUnsigned(ad5);
    SCI3_PutString(",\"ad6_raw\":");
    SCI3_PutUnsigned(ad6);
    SCI3_PutString("},\"adc_timeout_mask\":");
    SCI3_PutUnsigned((word)adc_timeout);
    SCI3_PutString("}\r\n");
    PTAD_PTAD5 = (byte)!PTAD_PTAD5;
    Delay();
  }
}
