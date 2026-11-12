#ifndef PRISMA_HAL_H
#define PRISMA_HAL_H
#include "prisma_telemetry.h"

/* O port da placa deve configurar clock, timer, ADC e SCI conforme seu manual. */
int prisma_hal_init(void);
/* 1=amostra sincronizada, 0=nenhuma disponível, -1=encerrar/erro. */
int prisma_hal_next(prisma_sample *sample);
/* Deve concluir a transmissão ou retornar erro; não descartar dados silenciosamente. */
int prisma_hal_write(const char *data, size_t length);
void prisma_hal_status(prisma_status *status);
#endif
