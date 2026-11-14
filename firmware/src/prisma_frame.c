#include "prisma_frame.h"

uint16_t prisma_crc16_update(uint16_t crc, const uint8_t *data, size_t length)
{
    size_t i;
    int bit;
    for (i = 0; i < length; ++i) {
        crc = (uint16_t)(crc ^ ((uint16_t)data[i] << 8));
        for (bit = 0; bit < 8; ++bit) {
            crc = (crc & 0x8000u) ? (uint16_t)((crc << 1) ^ 0x1021u) : (uint16_t)(crc << 1);
        }
    }
    return crc;
}

static uint8_t *put_u16(uint8_t *p, uint16_t v)
{
    p[0] = (uint8_t)(v & 0xFFu);
    p[1] = (uint8_t)(v >> 8);
    return p + 2;
}

static uint8_t *put_u32(uint8_t *p, uint32_t v)
{
    p = put_u16(p, (uint16_t)(v & 0xFFFFu));
    return put_u16(p, (uint16_t)(v >> 16));
}

int prisma_encode_burst_frame(uint32_t seq, uint32_t fs_mhz, uint16_t n, uint8_t mask, uint8_t flags,
                              const uint16_t *values, uint8_t *output, size_t capacity)
{
    size_t k, count, payload, total, i;
    uint8_t *p;
    uint16_t crc;

    if (values == NULL || output == NULL || n < 2u || n > 4096u) {
        return -1;
    }
    if (mask == PRISMA_MASK_VOLTAGES) {
        k = 3u;
    } else if (mask == PRISMA_MASK_ALL) {
        k = 6u;
    } else {
        return -1;
    }
    count = (size_t)n * k;
    payload = PRISMA_BURST_HEADER_BYTES + 2u * count;
    total = PRISMA_FRAME_OVERHEAD + payload;
    if (capacity < total || total > 0x7FFFFFFFu) {
        return -1;
    }
    p = output;
    *p++ = 0xA5u;
    *p++ = 0x5Au;
    *p++ = PRISMA_FRAME_BURST;
    p = put_u16(p, (uint16_t)payload);
    p = put_u32(p, seq);
    p = put_u32(p, fs_mhz);
    p = put_u16(p, n);
    *p++ = mask;
    *p++ = flags;
    for (i = 0; i < count; ++i) {
        p = put_u16(p, values[i]);
    }
    crc = prisma_crc16_update(0xFFFFu, output + 2, (size_t)(p - (output + 2)));
    p = put_u16(p, crc);
    return (int)(p - output);
}
