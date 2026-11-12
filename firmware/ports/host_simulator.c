/* Port de teste em computador: não acessa hardware nem representa aquisição real. */
#include "prisma_hal.h"
#include <math.h>
#include <stdio.h>
static uint32_t index_ms;
int prisma_hal_init(void) { index_ms = 0; return 0; }
int prisma_hal_next(prisma_sample *s)
{
    double phase;
    if (index_ms >= 5000U) return -1;
    phase = 6.283185307179586 * 60.0 * index_ms / 1000.0;
    s->time_ms = index_ms++;
    s->va_mv = (int32_t)(179605.0 * sin(phase));
    s->vb_mv = (int32_t)(179605.0 * sin(phase - 2.094395102393195));
    s->vc_mv = (int32_t)(179605.0 * sin(phase + 2.094395102393195));
    s->currents_present = 1;
    s->ia_ma = (int32_t)(7071.0 * sin(phase - 0.4510268118));
    s->ib_ma = (int32_t)(7071.0 * sin(phase - 2.094395102393195 - 0.4510268118));
    s->ic_ma = (int32_t)(7071.0 * sin(phase + 2.094395102393195 - 0.4510268118));
    return 1;
}
int prisma_hal_write(const char *data, size_t length)
{
    return fwrite(data, 1, length, stdout) == length ? 0 : -1;
}
void prisma_hal_status(prisma_status *s)
{
    s->led_run = 1; s->gpio_input = 0; s->adc0_raw = 2048;
    s->lcd_line = "SIMULADOR HOST";
}
