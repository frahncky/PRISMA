#include "prisma_hal.h"

int main(void)
{
    prisma_sample sample;
    prisma_status status;
    char output[512];
    unsigned count = 0;
    int available, length;
    if (prisma_hal_init()) return 1;
    for (;;) {
        available = prisma_hal_next(&sample);
        if (available < 0) break;
        if (!available) continue;
        length = prisma_encode_sample(&sample, output, sizeof output);
        if (length < 0 || prisma_hal_write(output, (size_t)length)) return 1;
        if (++count % 1000U == 0) {
            prisma_hal_status(&status);
            length = prisma_encode_status(&status, output, sizeof output);
            if (length < 0 || prisma_hal_write(output, (size_t)length)) return 1;
        }
    }
    return 0;
}
