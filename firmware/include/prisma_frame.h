#ifndef PRISMA_FRAME_H
#define PRISMA_FRAME_H
/* Protocolo binário PRISMA v2 (ver docs/protocolo.md).
 *
 *   A5 5A | tipo u8 | len u16 LE | payload | CRC16-CCITT-FALSE u16 LE
 *
 * Rajada (tipo 0x01): seq u32, fs_mhz u32, n u16, máscara u8, flags u8,
 * depois n x k palavras u16 LE intercaladas (k = 3 ou 6).
 * Sem alocação dinâmica nem ponto flutuante: adequado ao ColdFire V1.
 */
#include <stddef.h>
#include <stdint.h>

#define PRISMA_FRAME_BURST 0x01u
#define PRISMA_MASK_VOLTAGES 0x07u
#define PRISMA_MASK_ALL 0x3Fu
#define PRISMA_FLAG_SIGNED 0x80u
#define PRISMA_BURST_HEADER_BYTES 12u
#define PRISMA_FRAME_OVERHEAD 7u

/* Bytes de um quadro de rajada com n amostras de k canais. */
#define PRISMA_BURST_FRAME_BYTES(n, k) \
    (PRISMA_FRAME_OVERHEAD + PRISMA_BURST_HEADER_BYTES + 2u * (size_t)(n) * (size_t)(k))

uint16_t prisma_crc16_update(uint16_t crc, const uint8_t *data, size_t length);

/* Escreve o quadro completo em output. values contém n x k palavras
 * intercaladas por amostra. Retorna bytes escritos ou -1 (argumento ou
 * capacidade inválidos). */
int prisma_encode_burst_frame(uint32_t seq, uint32_t fs_mhz, uint16_t n, uint8_t mask, uint8_t flags,
                              const uint16_t *values, uint8_t *output, size_t capacity);
#endif
