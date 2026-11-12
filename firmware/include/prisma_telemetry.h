#ifndef PRISMA_TELEMETRY_H
#define PRISMA_TELEMETRY_H
#include <stddef.h>
#include <stdint.h>

typedef struct {
    uint32_t time_ms;
    int32_t va_mv, vb_mv, vc_mv;
    int currents_present;
    int32_t ia_ma, ib_ma, ic_ma;
} prisma_sample;

typedef struct {
    int led_run;
    int gpio_input;
    uint16_t adc0_raw;
    const char *lcd_line;
} prisma_status;

/* Retorna bytes escritos, sem NUL, ou -1 se o buffer for insuficiente. */
int prisma_encode_sample(const prisma_sample *sample, char *output, size_t capacity);
int prisma_encode_status(const prisma_status *status, char *output, size_t capacity);
#endif
