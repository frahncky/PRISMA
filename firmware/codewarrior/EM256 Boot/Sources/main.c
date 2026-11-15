#include <hidef.h>
#include "derivative.h"

/* Bootloader serial PRISMA para a DEMOEM / MCF51EM256 (docs/bootloader.md).
 *
 * Fica no bloco 1 da flash (com vetores, trim do relógio e configuração) e
 * grava a aplicação no bloco 2 (0x20000..0x3FBFF) pela SCI3, com os quadros de
 * comando de prisma_command.h e a lógica de prisma_boot.h (testada no PC).
 * Os dois blocos de flash são independentes: o código roda do bloco 1 enquanto
 * o bloco 2 é apagado ou gravado, sem rotina na RAM.
 *
 * Partida:
 *  - aplicação pediu (comando 0x04: palavra "BOOT" no fim da RAM) -> fica;
 *  - sem aplicação válida (descritor + CRC-32) -> fica;
 *  - senão, espera ~150 ms por um comando do bootloader (recupera uma aplicação
 *    que trava logo na partida) e salta para a aplicação.
 * Sem interrupções: a SCI3 e a flash são lidas por varredura.
 */

#ifndef PRISMA_ICS_TRIM
#define PRISMA_ICS_TRIM 0xA0U                 /* mesmo trim do firmware independente */
#endif
#ifndef PRISMA_ICS_FTRIM
#define PRISMA_ICS_FTRIM 0x00U
#endif
const byte prisma_nv_ftrim @0x000003FE = PRISMA_ICS_FTRIM;
const byte prisma_nv_trim  @0x000003FF = PRISMA_ICS_TRIM;

#define PRISMA_SCI_BAUD 115200UL
#define PRISMA_BUS_HZ 19922944UL
#define SCI3_SBR ((byte)((PRISMA_BUS_HZ / 16UL + PRISMA_SCI_BAUD / 2UL) / PRISMA_SCI_BAUD))

#define PRISMA_CMD_MAX_PAYLOAD 140U           /* escrita de 128 bytes + endereço */
#include "../../../include/prisma_frame_stream.h"
#include "../../../include/prisma_command.h"
#include "../../../include/prisma_boot.h"

#define APP_START 0x00020000UL                /* bloco 2 */
#define APP_END 0x00040000UL                  /* o último setor guarda o descritor */
#define APP_HOLE_START 0x000203FEUL           /* NV2FTRIM..NV2OPT: nunca gravados */
#define APP_HOLE_END 0x00020410UL
#define FLASH_PAGE 0x400U                     /* setor de 1 KiB */

#define BOOT_REQUEST (*(volatile unsigned long *)0x00803FF0UL)
#define BOOT_REQUEST_MAGIC 0x424F4F54UL       /* "BOOT", gravado pela aplicação (main.c, comando 0x04) */
#define BOOT_WINDOW_LOOPS 60000UL             /* ~150 ms de varredura da SCI3 a ~20 MHz */

/* F2CDIV: FCLK = 19,92 MHz / 8 / (12 + 1) = 191,6 kHz (precisa ficar entre 150 e 200 kHz). */
#define FLASH2_CDIV 0x4CU
#define FSTAT_FCBEF 0x80U
#define FSTAT_FCCF 0x40U
#define FSTAT_ERRORS 0x30U                    /* FPVIOL | FACCERR */
#define FCMD_PROGRAM 0x20U                    /* longword */
#define FCMD_PAGE_ERASE 0x40U

static void InitSystems(void)
{
  SOPT1 = 0x23;                               /* COP desligado (escrita única: vale para a aplicação). */
  SPMSC1 = 0x00;
  SPMSC2 = 0x00;
  SPMSC3 = 0x00;
  SCGC1 = 0xFF;
  SCGC2 = 0xFF;
  SCGC3 = 0xFF;
  SCGC4 = 0xFF;
  SCGC5 = 0xFF;
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
  PTCPF2 = (byte)((PTCPF2 & 0xF0U) | 0x0FU);  /* RX3 no PTC0, TX3 no PTC1 */
  SCI3C2 = 0x00;
  SCI3BDH = 0x00;
  SCI3BDL = SCI3_SBR;
  SCI3C1 = 0x00;
  SCI3C3 = 0x00;
  SCI3C2 = 0x0C;                              /* TE + RE, sem interrupção */
}

static void SCI3_PutByte(unsigned char value)
{
  while (SCI3S1_TDRE == 0U) {
  }
  SCI3D = value;
}

static void SCI3_PutString(const char *text)
{
  while (*text != '\0') {
    SCI3_PutByte((unsigned char)*text++);
  }
}

/* 1 com um byte em *value. Erro de recepção (OR/NF/FE/PF) descarta o byte: o CRC do quadro resolve. */
static byte SCI3_Poll(byte *value)
{
  byte status = SCI3S1;
  if ((status & 0x20U) == 0U) {               /* RDRF */
    return 0U;
  }
  *value = SCI3D;                             /* ler S1 e depois D limpa RDRF e os erros */
  return (byte)((status & 0x0FU) == 0U);
}

/* ---- Flash do bloco 2 ---------------------------------------------------- */

static void Flash2_Init(void)
{
  if ((F2CDIV & 0x80U) == 0U) {               /* FDIVLD: escrita única depois do reset */
    F2CDIV = FLASH2_CDIV;
  }
}

/* Sequência da controladora: escreve no endereço, comando, dispara e espera. */
static byte Flash2_Command(unsigned long address, unsigned long data, byte command)
{
  while ((F2STAT & FSTAT_FCBEF) == 0U) {
  }
  F2STAT = FSTAT_ERRORS;                      /* limpa erros anteriores */
  *(volatile unsigned long *)address = data;
  F2CMD = command;
  F2STAT = FSTAT_FCBEF;                       /* dispara */
  if ((F2STAT & FSTAT_ERRORS) != 0U) {
    return (byte)(F2STAT & FSTAT_ERRORS);
  }
  while ((F2STAT & FSTAT_FCCF) == 0U) {
  }
  return (byte)(F2STAT & FSTAT_ERRORS);
}

static unsigned char Hal_Erase(unsigned long address)
{
  if (address < APP_START || address >= APP_END) {
    return 0x80U;                             /* defesa extra: nunca o bloco 1 */
  }
  return Flash2_Command(address, 0xFFFFFFFFUL, FCMD_PAGE_ERASE);
}

static unsigned char Hal_Program(unsigned long address, const unsigned char *data, unsigned short length)
{
  unsigned short i;
  byte err;
  if (address < APP_START || address + length > APP_END) {
    return 0x80U;
  }
  for (i = 0U; i < length; i = (unsigned short)(i + 4U)) {
    /* ColdFire é big-endian: data[i] fica no menor endereço. */
    unsigned long value = ((unsigned long)data[i] << 24) | ((unsigned long)data[i + 1U] << 16)
                        | ((unsigned long)data[i + 2U] << 8) | (unsigned long)data[i + 3U];
    err = Flash2_Command(address + i, value, FCMD_PROGRAM);
    if (err != 0U) {
      return err;
    }
  }
  return 0U;
}

static const unsigned char *Hal_Memory(unsigned long address)
{
  return (const unsigned char *)address;
}

static const prisma_boot_hal hal = {
  APP_START, APP_END, APP_HOLE_START, APP_HOLE_END, FLASH_PAGE, Hal_Erase, Hal_Program, Hal_Memory
};

/* ---- Salto para a aplicação ---------------------------------------------- */

static unsigned long jump_sp;
static unsigned long jump_pc;

static void Boot_Jump(void)
{
  const unsigned char *header = (const unsigned char *)APP_START;
  while (SCI3S1_TC == 0U) {                   /* a última resposta termina de sair */
  }
  SCI3C2 = 0x00U;                             /* a aplicação reconfigura a SCI3 */
  jump_sp = prisma_rd32_be(header);
  jump_pc = prisma_rd32_be(header + 4);
  /* A aplicação monta a própria tabela de vetores na RAM e ajusta o VBR. */
  asm {
    movea.l jump_sp,a7
    movea.l jump_pc,a0
    jmp     (a0)
  }
}

static prisma_boot boot;
static prisma_cmd_parser cmd;

/* Atende um byte; devolve 1 se um comando completo foi respondido. */
static byte Boot_Feed(byte value)
{
  if (prisma_cmd_feed(&cmd, value) == 0U) {
    return 0U;
  }
  if (prisma_boot_handle(&boot, &cmd, SCI3_PutByte) == PRISMA_BOOT_RUN_APP) {
    Boot_Jump();
  }
  return 1U;
}

void main(void)
{
  byte stay;
  byte value;
  unsigned long wait;

  InitSystems();
  Flash2_Init();
  stay = (byte)(BOOT_REQUEST == BOOT_REQUEST_MAGIC);
  BOOT_REQUEST = 0UL;
  prisma_boot_init(&boot, &hal);
  prisma_cmd_init(&cmd);
  SCI3_Init();

  if ((stay == 0U) && (boot.app_valid != 0U)) {
    for (wait = BOOT_WINDOW_LOOPS; (wait != 0UL) && (stay == 0U); --wait) {
      if ((SCI3_Poll(&value) != 0U) && (Boot_Feed(value) != 0U)) {
        stay = 1U;                            /* alguém falou com o bootloader: fica */
      }
    }
    if (stay == 0U) {
      Boot_Jump();
    }
  }

  SCI3_PutString(boot.app_valid != 0U
                 ? "{\"type\":\"status\",\"source\":\"DEMOEM\",\"message\":\"BOOTLOADER (APP OK)\"}\r\n"
                 : "{\"type\":\"status\",\"source\":\"DEMOEM\",\"message\":\"BOOTLOADER (SEM APP)\"}\r\n");
  for (;;) {
    if (SCI3_Poll(&value) != 0U) {
      (void)Boot_Feed(value);
    }
  }
}
