# Bootloader serial e atualização remota (OTA)

Objetivo: atualizar o firmware da DEMOEM pela mesma serial da telemetria, sem o PEmicro. Primeiro pelo PC e depois pelo ESP32-S3, que vai receber a imagem por Wi-Fi.

## Estado

| Parte | Situação |
| --- | --- |
| Protocolo e núcleo em C (`firmware/include/prisma_boot.h`) | Pronto. Testado no PC com flash simulada (`tests/test_bootloader.py`). |
| Gravador no PC (`prisma.core.bootloader`, `scripts/atualizar_demoem.py`) | Pronto. Lê o S19, repete o que se perde e só confirma com o CRC-32 da placa. |
| Projeto do bootloader no CodeWarrior (driver da flash, salto para a aplicação) | **Pendente.** |
| Aplicação ligada em 0x20000 e comando `0x04` (reiniciar no bootloader) | **Pendente.** |
| Teste na placa | **Bloqueado:** o RX3 (CH340 TXD → PTC0) ainda não recebe; ver [bancada](bancada-demoem.md). |

## Mapa de memória (MCF51EM256)

A flash tem dois blocos independentes. O bootloader roda no bloco 1 e grava o bloco 2, então não precisa executar da RAM enquanto grava.

| Faixa | Conteúdo |
| --- | --- |
| `0x00000–0x1FFFF` (FTSR1) | Bootloader: vetores, trim do relógio (`0x3FE/0x3FF`), proteção e segurança (`0x400–0x40F`). Gravado só pelo PEmicro. |
| `0x20000–0x3FBFF` (FTSR2) | Aplicação: tabela de vetores em `0x20000` e código a partir de `0x20410`. |
| `0x203FE–0x2040F` | **Reservado:** trim, chave e opções do bloco 2. O bootloader nunca escreve ali e preserva esses bytes quando apaga a página. |
| `0x3FC00–0x3FFFF` | Descritor da aplicação: magic `PRSM`, tamanho, CRC-32 e CRC invertido. |
| `0x800000–0x8003FF` (RAM) | Cópia da tabela de vetores da aplicação. O ColdFire V1 só aceita o VBR em `0x0` ou no início da RAM. |

A licença Special Edition do CodeWarrior limita cada imagem a 64 KB de código. Isso basta para a aplicação atual (~5 KB). Falta confirmar que o linker aceita a aplicação em `0x20000`.

## Protocolo

São os mesmos quadros de [comandos](protocolo.md) (`0x10` comando e `0x11` resposta, com CRC-16). O bootloader aceita payload de até 140 bytes:

| Código | Argumentos | Resposta |
| --- | --- | --- |
| `0x20` INFO | — | rev u8 · aplicação válida u8 · página u16 · início u32 · limite u32 · maior bloco u16 · último erro da flash u8 · reservado u8 · faixa reservada (início u32, fim u32) |
| `0x21` ERASE | endereço u32 · páginas u16 | — |
| `0x22` WRITE | endereço u32 · dados (múltiplo de 4, até 128) | — |
| `0x23` CRC | endereço u32 · tamanho u32 | CRC-32 u32 (zlib, sem a faixa reservada) |
| `0x24` COMMIT | tamanho u32 · CRC-32 u32 | CRC calculado pela placa u32 |
| `0x25` RUN | — | responde e salta para a aplicação |

Estados extras: `3` = fora da área, desalinhado ou na faixa reservada · `4` = erro de gravação (controladora, destino não apagado ou conferência) · `5` = imagem inválida.

## Por que uma atualização interrompida não estraga a placa

1. Qualquer ERASE apaga antes o descritor. A partir daí, a placa fica no bootloader até o próximo COMMIT.
2. Cada WRITE confere se o destino está apagado e relê o que gravou.
3. No COMMIT, a placa recalcula o CRC-32 da imagem inteira. Só grava o descritor se o CRC conferir.
4. Na partida, o bootloader só salta para a aplicação se o descritor, o CRC e o vetor de reset estiverem certos.

Se a energia cair ou a serial falhar no meio, basta rodar a atualização de novo. Se alguma resposta se perder, o gravador repete sem regravar às cegas. Um WRITE repetido que volta "destino não apagado" é conferido pelo CRC daquele bloco. Um COMMIT repetido é conferido pelo INFO.

O bootloader em si nunca se regrava pela serial. Se ele estiver errado, a correção é pelo PEmicro, como hoje.

## Entrada no bootloader

- Na partida, sem aplicação válida, a placa fica no bootloader.
- Com aplicação válida, a aplicação atende o comando `0x04` (rev 4): grava uma palavra mágica numa posição da RAM que a inicialização não apaga e força um reset (opcode ilegal). O bootloader vê a palavra e fica.
- O PC (ou o ESP32) manda o INFO do bootloader. Se não houver resposta, manda `0x04` para a aplicação e tenta de novo.

## Próximos passos

1. Criar o projeto `EM256 Boot` no CodeWarrior, copiando o `EM256 Demo` com outro `main.c` e outro linker:
   - driver do bloco 2: `F2CDIV = 0x4C`, que dá ~192 kHz a partir de 19,92 MHz; comandos `0x20` (longword) e `0x40` (página);
   - SCI3 sem interrupção, por varredura;
   - salto para a aplicação: copia os vetores para a RAM, ajusta `VBR = 0x800000`, carrega SP e PC.
2. Aplicação: linker em `0x20000`, RAM a partir de `0x800400`, sem os bytes de trim em `0x3FE`, mais o comando `0x04`.
3. Gravar o bootloader pelo PEmicro e a aplicação pelo `scripts/atualizar_demoem.py`, depois que o RX3 funcionar.
4. ESP32-S3: mesmo fluxo do `BootClient`, com a imagem recebida por Wi-Fi.
