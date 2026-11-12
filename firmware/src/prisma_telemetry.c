#include "prisma_telemetry.h"
#include <stdio.h>
#include <stdarg.h>

static int append(char *out, size_t cap, size_t *used, const char *format, ...)
{
    int length;
    va_list args;
    if (*used >= cap) return -1;
    va_start(args, format);
    length = vsnprintf(out + *used, cap - *used, format, args);
    va_end(args);
    if (length < 0 || (size_t)length >= cap - *used) return -1;
    *used += (size_t)length;
    return 0;
}

static int number(char *out, size_t cap, size_t *used, const char *name, int32_t value)
{
    uint32_t magnitude = value < 0 ? (uint32_t)(-(value + 1)) + 1U : (uint32_t)value;
    return append(out, cap, used, ",\"%s\":%s%lu.%03lu", name, value < 0 ? "-" : "",
                  (unsigned long)(magnitude / 1000U), (unsigned long)(magnitude % 1000U));
}

int prisma_encode_sample(const prisma_sample *s, char *out, size_t cap)
{
    size_t used = 0;
    if (!s || !out || !cap) return -1;
    if (append(out, cap, &used, "{\"type\":\"sample\",\"t\":%lu.%03lu",
               (unsigned long)(s->time_ms / 1000U), (unsigned long)(s->time_ms % 1000U))) return -1;
    if (number(out, cap, &used, "va", s->va_mv) || number(out, cap, &used, "vb", s->vb_mv)
        || number(out, cap, &used, "vc", s->vc_mv)) return -1;
    if (s->currents_present && (number(out, cap, &used, "ia", s->ia_ma)
        || number(out, cap, &used, "ib", s->ib_ma) || number(out, cap, &used, "ic", s->ic_ma))) return -1;
    if (append(out, cap, &used, "}\n")) return -1;
    return (int)used;
}

int prisma_encode_status(const prisma_status *s, char *out, size_t cap)
{
    const unsigned char *p;
    size_t used = 0;
    if (!s || !out || !cap || !s->lcd_line) return -1;
    if (append(out, cap, &used, "{\"type\":\"status\",\"leds\":{\"run\":%s},\"gpio\":{\"input\":%s},"
               "\"adc\":{\"adc0_raw\":%u},\"lcd\":[\"", s->led_run ? "true" : "false",
               s->gpio_input ? "true" : "false", (unsigned)s->adc0_raw)) return -1;
    for (p = (const unsigned char *)s->lcd_line; *p; ++p) {
        if (*p == '"' || *p == '\\') {
            if (append(out, cap, &used, "\\%c", *p)) return -1;
        } else if (*p < 32 || *p >= 127) {
            if (append(out, cap, &used, "\\u%04x", (unsigned)*p)) return -1;
        } else if (append(out, cap, &used, "%c", *p)) return -1;
    }
    if (append(out, cap, &used, "\"]}\n")) return -1;
    return (int)used;
}
