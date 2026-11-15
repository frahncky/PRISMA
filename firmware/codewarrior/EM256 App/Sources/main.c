/* Aplicação para o bootloader PRISMA: o mesmo firmware do "EM256 Demo",
 * ligado em 0x20000 (bloco 2 da flash) com a tabela de vetores na RAM.
 * Ver docs/bootloader.md. Não edite aqui: o código fica em "EM256 Demo". */
#define PRISMA_APP_IMAGE 1
#include "../../EM256 Demo/Sources/main.c"
