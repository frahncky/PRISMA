#ifndef PRISMA_BOOT_H
#define PRISMA_BOOT_H
/* Bootloader serial PRISMA: grava a aplicação na flash pelos quadros de comando.
 *
 * Usa os mesmos quadros 0x10 (comando) / 0x11 (resposta) de prisma_command.h,
 * com códigos próprios (0x20..0x25) e payload maior (PRISMA_CMD_MAX_PAYLOAD 140,
 * escrita de até 128 bytes). Ver docs/bootloader.md.
 *
 * Segurança da gravação:
 *  - só grava dentro de [app_start, desc_addr) e nunca na faixa reservada
 *    (hole: bytes de configuração do bloco de flash da aplicação);
 *  - qualquer apagamento invalida antes o descritor (último setor da área), então
 *    uma atualização interrompida deixa a placa no bootloader, nunca numa
 *    aplicação pela metade;
 *  - o descritor (magic, tamanho, CRC-32) só é gravado no COMMIT, depois de o
 *    bootloader recalcular o CRC-32 da imagem gravada;
 *  - na partida, a aplicação só roda se o descritor e o CRC-32 conferem.
 *
 * O acesso à flash fica em prisma_boot_hal: no MCF51EM256 são os registradores
 * F2CMD/F2STAT; no PC (tests/test_bootloader.py), uma flash simulada.
 * C89 sem ponto flutuante. Inclua prisma_frame_stream.h e prisma_command.h antes.
 */
#ifndef PRISMA_COMMAND_H
#error "Inclua prisma_command.h antes de prisma_boot.h"
#endif

#define PRISMA_BOOT_REV 1U
#define PRISMA_BOOT_MAX_CHUNK 128U

#define PRISMA_CMD_BOOT_INFO 0x20U   /* -> rev, aplicação válida, página, área, maior bloco, faixa reservada */
#define PRISMA_CMD_BOOT_ERASE 0x21U  /* endereço u32, páginas u16 */
#define PRISMA_CMD_BOOT_WRITE 0x22U  /* endereço u32, dados (múltiplo de 4, até 128) */
#define PRISMA_CMD_BOOT_CRC 0x23U    /* endereço u32, tamanho u32 -> CRC-32 u32 (sem a faixa reservada) */
#define PRISMA_CMD_BOOT_COMMIT 0x24U /* tamanho u32, CRC-32 u32 -> grava o descritor */
#define PRISMA_CMD_BOOT_RUN 0x25U    /* responde e salta para a aplicação */

#define PRISMA_REPLY_RANGE 0x03U     /* fora da área, desalinhado ou na faixa reservada */
#define PRISMA_REPLY_FLASH 0x04U     /* erro da controladora, destino não apagado ou conferência falhou */
#define PRISMA_REPLY_IMAGE 0x05U     /* CRC não confere ou aplicação inválida */

#define PRISMA_BOOT_MAGIC 0x4D535250UL  /* "PRSM" em little-endian */
#define PRISMA_BOOT_DESC_BYTES 16U
#define PRISMA_BOOT_HOLE_MAX 32U        /* bytes (longwords inteiros) da faixa reservada */

#define PRISMA_BOOT_NONE 0U
#define PRISMA_BOOT_RUN_APP 1U

typedef struct {
    unsigned long app_start;          /* início da aplicação (tabela de vetores) */
    unsigned long app_end;            /* fim exclusivo da área; o último setor é o descritor */
    unsigned long hole_start;         /* faixa [hole_start, hole_end) que nunca é escrita */
    unsigned long hole_end;
    unsigned short page_size;
    /* 0 = ok; outro valor = erro da controladora. */
    unsigned char (*erase_page)(unsigned long address);
    /* Grava longwords já alinhados; length múltiplo de 4. */
    unsigned char (*program)(unsigned long address, const unsigned char *data, unsigned short length);
    /* Ponteiro para ler a flash a partir de address (no MCU, o próprio endereço). */
    const unsigned char *(*memory)(unsigned long address);
} prisma_boot_hal;

typedef struct {
    const prisma_boot_hal *hal;
    unsigned char app_valid;
    unsigned char flash_error;        /* último erro da controladora, para o INFO */
} prisma_boot;

static unsigned long prisma_rd32(const unsigned char *p)
{
    return (unsigned long)p[0] | ((unsigned long)p[1] << 8) | ((unsigned long)p[2] << 16)
         | ((unsigned long)p[3] << 24);
}

/* Vetores do ColdFire ficam em big-endian (ordem da memória do próprio MCU). */
static unsigned long prisma_rd32_be(const unsigned char *p)
{
    return ((unsigned long)p[0] << 24) | ((unsigned long)p[1] << 16) | ((unsigned long)p[2] << 8)
         | (unsigned long)p[3];
}

static unsigned long prisma_boot_desc_addr(const prisma_boot_hal *hal)
{
    return hal->app_end - hal->page_size;
}

/* CRC-32 (zlib: poly 0xEDB88320 refletido) de [address, address+length), pulando a faixa reservada. */
static unsigned long prisma_boot_crc32(const prisma_boot_hal *hal, unsigned long address, unsigned long length)
{
    unsigned long crc = 0xFFFFFFFFUL;
    unsigned long end = address + length;
    unsigned char bit;
    while (address < end) {
        if (address >= hal->hole_start && address < hal->hole_end) {
            address = hal->hole_end;
            continue;
        }
        crc ^= (unsigned long)*hal->memory(address);
        for (bit = 0U; bit < 8U; ++bit) {
            crc = (crc & 1UL) ? ((crc >> 1) ^ 0xEDB88320UL) : (crc >> 1);
        }
        ++address;
    }
    return crc ^ 0xFFFFFFFFUL;
}

static unsigned char prisma_boot_overlaps_hole(const prisma_boot_hal *hal, unsigned long address,
                                               unsigned long length)
{
    return (unsigned char)(address < hal->hole_end && address + length > hal->hole_start);
}

/* Descritor íntegro e CRC da imagem conferindo; o vetor de reset tem de cair na área. */
static unsigned char prisma_boot_validate(const prisma_boot_hal *hal)
{
    const unsigned char *d = hal->memory(prisma_boot_desc_addr(hal));
    unsigned long length = prisma_rd32(d + 4);
    unsigned long crc = prisma_rd32(d + 8);
    unsigned long reset_pc;
    if (prisma_rd32(d) != PRISMA_BOOT_MAGIC || prisma_rd32(d + 12) != (crc ^ 0xFFFFFFFFUL)
        || length < 8UL || length > prisma_boot_desc_addr(hal) - hal->app_start) {
        return 0U;
    }
    reset_pc = prisma_rd32_be(hal->memory(hal->app_start + 4UL));
    if (reset_pc < hal->app_start || reset_pc >= hal->app_start + length) {
        return 0U;
    }
    return (unsigned char)(prisma_boot_crc32(hal, hal->app_start, length) == crc);
}

static void prisma_boot_init(prisma_boot *b, const prisma_boot_hal *hal)
{
    b->hal = hal;
    b->flash_error = 0U;
    b->app_valid = prisma_boot_validate(hal);
}

static unsigned char prisma_boot_page_blank(const prisma_boot_hal *hal, unsigned long page)
{
    const unsigned char *p = hal->memory(page);
    unsigned short i;
    for (i = 0U; i < hal->page_size; ++i) {
        if (p[i] != 0xFFU && !(page + i >= hal->hole_start && page + i < hal->hole_end)) {
            return 0U;
        }
    }
    return 1U;
}

/* Antes de mexer na área, o descritor sai: a placa fica no bootloader até o próximo COMMIT. */
static unsigned char prisma_boot_invalidate(prisma_boot *b)
{
    unsigned long desc = prisma_boot_desc_addr(b->hal);
    if (!prisma_boot_page_blank(b->hal, desc)) {
        unsigned char err = b->hal->erase_page(desc);
        if (err != 0U) {
            b->flash_error = err;
            return PRISMA_REPLY_FLASH;
        }
    }
    b->app_valid = 0U;
    return PRISMA_REPLY_OK;
}

/* Apaga uma página preservando os bytes da faixa reservada que caem nela
 * (no MCF51EM256, trims e proteção do bloco 2 dividem a página com a aplicação). */
static unsigned char prisma_boot_erase_page(prisma_boot *b, unsigned long page)
{
    const prisma_boot_hal *hal = b->hal;
    unsigned char saved[PRISMA_BOOT_HOLE_MAX];
    unsigned long lo = hal->hole_start & ~3UL;
    unsigned long hi = (hal->hole_end + 3UL) & ~3UL;
    unsigned short keep = 0U, i;
    unsigned char err;
    if (lo < page) { lo = page; }
    if (hi > page + hal->page_size) { hi = page + hal->page_size; }
    if (lo < hi) {
        keep = (unsigned short)(hi - lo);
        for (i = 0U; i < keep; ++i) {
            unsigned long a = lo + i;
            saved[i] = (a >= hal->hole_start && a < hal->hole_end) ? *hal->memory(a) : 0xFFU;
        }
    }
    err = hal->erase_page(page);
    if (err == 0U && !prisma_boot_page_blank(hal, page)) {
        err = 0xFFU;
    }
    for (i = 0U; err == 0U && i < keep; i = (unsigned short)(i + 4U)) {
        if ((saved[i] & saved[i + 1U] & saved[i + 2U] & saved[i + 3U]) != 0xFFU) {
            err = hal->program(lo + i, &saved[i], 4U);
        }
    }
    if (err != 0U) {
        b->flash_error = err;
        return PRISMA_REPLY_FLASH;
    }
    return PRISMA_REPLY_OK;
}

static unsigned char prisma_boot_erase(prisma_boot *b, unsigned long address, unsigned short pages)
{
    const prisma_boot_hal *hal = b->hal;
    unsigned long desc = prisma_boot_desc_addr(hal);
    unsigned char status;
    if (pages == 0U || (address - hal->app_start) % hal->page_size != 0UL || address < hal->app_start
        || address >= desc || (unsigned long)pages > (desc - address) / hal->page_size) {
        return PRISMA_REPLY_RANGE;
    }
    status = prisma_boot_invalidate(b);
    while (status == PRISMA_REPLY_OK && pages-- != 0U) {
        status = prisma_boot_erase_page(b, address);
        address += hal->page_size;
    }
    return status;
}

static unsigned char prisma_boot_write(prisma_boot *b, unsigned long address, const unsigned char *data,
                                       unsigned short length)
{
    const prisma_boot_hal *hal = b->hal;
    const unsigned char *target;
    unsigned short i;
    unsigned char err;
    if (length == 0U || length > PRISMA_BOOT_MAX_CHUNK || (length & 3U) != 0U || (address & 3UL) != 0UL
        || address < hal->app_start || address + length > prisma_boot_desc_addr(hal)
        || prisma_boot_overlaps_hole(hal, address, length)) {
        return PRISMA_REPLY_RANGE;
    }
    if (b->app_valid != 0U) {
        return PRISMA_REPLY_IMAGE;        /* aplicação válida: apague (ERASE) antes de regravar */
    }
    target = hal->memory(address);
    for (i = 0U; i < length; ++i) {
        if (target[i] != 0xFFU) {
            return PRISMA_REPLY_FLASH;    /* destino não apagado */
        }
    }
    err = hal->program(address, data, length);
    target = hal->memory(address);
    for (i = 0U; err == 0U && i < length; ++i) {
        if (target[i] != data[i]) {
            err = 0xFFU;                  /* conferência depois da gravação */
        }
    }
    if (err != 0U) {
        b->flash_error = err;
        return PRISMA_REPLY_FLASH;
    }
    return PRISMA_REPLY_OK;
}

static unsigned char prisma_boot_commit(prisma_boot *b, unsigned long length, unsigned long crc,
                                        unsigned long *computed)
{
    const prisma_boot_hal *hal = b->hal;
    unsigned long desc = prisma_boot_desc_addr(hal);
    unsigned char d[PRISMA_BOOT_DESC_BYTES];
    unsigned char err;
    if (length < 8UL || length > desc - hal->app_start) {
        return PRISMA_REPLY_RANGE;
    }
    *computed = prisma_boot_crc32(hal, hal->app_start, length);
    if (*computed != crc) {
        return PRISMA_REPLY_IMAGE;
    }
    if (!prisma_boot_page_blank(hal, desc)) {
        return PRISMA_REPLY_FLASH;        /* descritor antigo: o ERASE o remove */
    }
    prisma_le32(d, PRISMA_BOOT_MAGIC);
    prisma_le32(d + 4, length);
    prisma_le32(d + 8, crc);
    prisma_le32(d + 12, crc ^ 0xFFFFFFFFUL);
    err = hal->program(desc, d, PRISMA_BOOT_DESC_BYTES);
    if (err != 0U) {
        b->flash_error = err;
        return PRISMA_REPLY_FLASH;
    }
    b->app_valid = prisma_boot_validate(hal);
    return b->app_valid != 0U ? PRISMA_REPLY_OK : PRISMA_REPLY_IMAGE;
}

/* Atende um comando completo do parser; devolve PRISMA_BOOT_RUN_APP depois de responder ao RUN. */
static unsigned char prisma_boot_handle(prisma_boot *b, const prisma_cmd_parser *p, prisma_put_byte_fn put)
{
    const prisma_boot_hal *hal = b->hal;
    const unsigned char *a = &p->payload[2];
    unsigned char args = prisma_cmd_args(p);
    unsigned char data[24];
    unsigned char length = 0U;
    unsigned char status = PRISMA_REPLY_BAD_ARGS;
    unsigned long value = 0UL;

    switch (p->payload[1]) {
    case PRISMA_CMD_BOOT_INFO:
        if (args == 0U) {
            data[0] = PRISMA_BOOT_REV;
            data[1] = b->app_valid;
            prisma_le16(data + 2, hal->page_size);
            prisma_le32(data + 4, hal->app_start);
            prisma_le32(data + 8, prisma_boot_desc_addr(hal));
            prisma_le16(data + 12, PRISMA_BOOT_MAX_CHUNK);
            data[14] = b->flash_error;
            data[15] = 0U;
            prisma_le32(data + 16, hal->hole_start);
            prisma_le32(data + 20, hal->hole_end);
            length = 24U;
            status = PRISMA_REPLY_OK;
        }
        break;
    case PRISMA_CMD_BOOT_ERASE:
        if (args == 6U) {
            status = prisma_boot_erase(b, prisma_rd32(a), (unsigned short)(a[4] | (a[5] << 8)));
        }
        break;
    case PRISMA_CMD_BOOT_WRITE:
        if (args > 4U) {
            status = prisma_boot_write(b, prisma_rd32(a), a + 4, (unsigned short)(args - 4U));
        }
        break;
    case PRISMA_CMD_BOOT_CRC:
        if (args == 8U) {
            unsigned long address = prisma_rd32(a), size = prisma_rd32(a + 4);
            if (address < hal->app_start || size > hal->app_end - address) {
                status = PRISMA_REPLY_RANGE;
            } else {
                prisma_le32(data, prisma_boot_crc32(hal, address, size));
                length = 4U;
                status = PRISMA_REPLY_OK;
            }
        }
        break;
    case PRISMA_CMD_BOOT_COMMIT:
        if (args == 8U) {
            status = prisma_boot_commit(b, prisma_rd32(a), prisma_rd32(a + 4), &value);
            prisma_le32(data, value);
            length = 4U;
        }
        break;
    case PRISMA_CMD_BOOT_RUN:
        if (args == 0U) {
            status = b->app_valid != 0U ? PRISMA_REPLY_OK : PRISMA_REPLY_IMAGE;
        }
        break;
    default:
        status = PRISMA_REPLY_UNKNOWN;
        break;
    }
    prisma_cmd_reply(put, p, status, data, length);
    return (unsigned char)(p->payload[1] == PRISMA_CMD_BOOT_RUN && status == PRISMA_REPLY_OK
                           ? PRISMA_BOOT_RUN_APP : PRISMA_BOOT_NONE);
}
#endif
