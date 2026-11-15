# Firmware de telemetria PRISMA

Este diretório contém um encoder JSON em C99, uma aplicação usando HAL, um simulador host e o projeto `codewarrior/EM256 Demo`, compilado e gravado com sucesso na DEMOEM/MCF51EM256 real.

## Componentes

| Arquivo | Função |
| --- | --- |
| `include/prisma_telemetry.h` | Estruturas de amostra e estado. Tensões em mV e correntes em mA na entrada do encoder. |
| `src/prisma_telemetry.c` | Geração de JSON sem formatação de ponto flutuante, com verificação de capacidade do buffer. |
| `include/prisma_hal.h` | Contrato para inicialização, amostragem sincronizada, transmissão e leitura de estados. |
| `src/main.c` | Loop de aquisição e envio, com mensagem de estados a cada 1000 amostras. |
| `ports/host_simulator.c` | Sinais sintéticos no computador, sem acesso a hardware. |
| `ports/mcf51em256_port.example.c` | Port pendente, bloqueado por `#error` até configurar o hardware real. |
| `codewarrior/EM256 Demo/Sources/main.c` | Firmware da DEMOEM: AD4/AD5/AD6 a ~1995 Hz (MTIM1), SCI3 a 115200 8N1 (`PRISMA_SCI_BAUD`) e trim do oscilador em 0x3FE/0x3FF. Com `PRISMA_CONTINUOUS=1` (padrão) amostra sem parar na interrupção do MTIM1 e envia um resumo por janela de ~1 s mais uma rajada de 500 amostras; com `0`, volta ao modo rajada anterior (adquire, para e transmite), validado em bancada. |
| `PRISMA_CHANNELS` (em `main.c`) | `6` (padrão na medição contínua): tensões AD4/AD5/AD6 + correntes diferenciais DAD0/DAD1/DAD2 (ADC3/ADC1/ADC2, AN3949), com uma conversão descartada após cada troca (`PRISMA_SETTLE`); corrente ~40 µs depois da tensão. `3`: só tensões, como validado em bancada. ~4,3 KB de código e ~6,3 KB de RAM com 6 canais. |
| `include/prisma_command.h` | Comandos PC → placa (quadro `0x10`) e respostas (`0x11`): parser byte a byte com CRC, sem ponto flutuante. Na DEMOEM (rev 3) a RX3 enche um buffer circular na interrupção e o laço atende INFO, RAJADA (uma a cada N janelas) e AUTOCALIBRAÇÃO DO ADC. Testado com gcc em `tests/test_board_commands.py`. |
| `include/prisma_meter.h` | Núcleo da medição contínua em C89 sem ponto flutuante: Σx, Σx² e Σv·i por janela de ciclos inteiros da fase A e quadro de resumo `0x02`. Testado no PC com gcc em `tests/test_meter_firmware.py`. |
| `codewarrior/EM256 Demo/cmd/prisma_flash_and_run.cmd` | Comandos HI-WAVE para carregar, verificar e executar a imagem. |

## Compilar e testar no computador

Com GCC:

```bash
gcc -std=c99 -Wall -Wextra -Werror -Ifirmware/include firmware/src/main.c firmware/src/prisma_telemetry.c firmware/ports/host_simulator.c -lm -o prisma-host.exe
./prisma-host.exe > telemetria-host.jsonl
```

No PowerShell, use `.\prisma-host.exe` para executar. O simulador produz 5000 amostras a 1000 amostras/s em tempo simulado e cinco mensagens de estado. Ele escreve tão rápido quanto o stdout permitir, sem tentar reproduzir o tempo real ou a capacidade de uma SCI. Não confundir esse teste com transmissão física.

A suíte pytest compila o código com warnings tratados como erros, interpreta a saída com o parser real do aplicativo e verifica RMS, frequência e fator de potência. Também testa limites de buffer, valores int32 extremos e escape de texto do LCD.

O exemplo de projeto `examples/projects/host-gcc.json` permite compilar pela interface e gerar o mapa do linker.

## Integração ColdFire validada

O projeto foi validado com CodeWarrior for Microcontrollers 6.3.2, suporte ColdFire V1 e PEmicro/HI-WAVE. O linker limita a imagem à faixa aceita pela licença Special Edition. Artefatos de `bin/`, dados locais da IDE e executáveis proprietários não são versionados.

A SCI3 usa PTC1/TX3 no J6 ligado ao RXD do CH340 e GND comum, sem ligar VCC. O perfil do aplicativo é `examples/profiles/demoem-ch340.json`. A leitura validada fixa um módulo por sinal: ADC3/AD4, ADC1/AD5 e ADC2/AD6. Ela publica `ad4_raw`, `ad5_raw` e `ad6_raw`; são contagens não calibradas. Alternar imediatamente entradas simples e diferenciais produziu resíduos do multiplexador e não é usado nesta revisão.

Para compilar, abra `EM256 Demo.mcp` e execute **Make**, ou rode `scripts/compilar_demoem.ps1`. Não use `CmdIDE /b /q`: o IDE 6.3 trava ao fechar sozinho depois do build ("CodeWarrior Error", exceção 0xc0000005) e deixa essa janela aberta, embora o build já tenha terminado. O script compila sem `/q` e encerra o IDE que ele abriu. A RX3 usa `interrupt VectorNumber_Vsci3rx`, como o MTIM1. A rotina do MTIM1 usa `interrupt VectorNumber_Vmtim1`, a sintaxe do *HCS08 porting support* ligado no projeto; `__declspec(interrupt)` com o vetor em `exceptions.c` derruba o IDE 6.3. Pelo mesmo motivo, `prisma_meter.h` não inclui outros headers: o `.c` inclui `prisma_frame_stream.h` antes. Imagem atual: ~4 KB de código e ~3,3 KB de RAM. Para gravar, abra a configuração PEmicro incluída no projeto, carregue `bin/Project.abs`, confirme **Connect/OK**, aguarde programar/verificar e use **Run/Go**. Depois da gravação, o cabo PEmicro pode ser removido; permanecem a alimentação da placa e o CH340.

O timestamp usa milissegundos em uint32; uma sessão precisa ser reiniciada após reset do dispositivo ou antes do rollover. Cada amostra deve representar canais sincronizados. `currents_present=0` omite os canais de corrente, sem inventar leituras.

A transmissão JSON tem custo significativo. Dimensionar `tamanho_da_linha × amostras_por_segundo × 10` para 8N1, mais estados e folga. 115200 baud pode ser insuficiente até para algumas centenas de amostras/s, e não comporta automaticamente as taxas necessárias para h15. A taxa do modo demo não é promessa de desempenho do hardware.

BDM não equivale a uma porta COM. A interface não acessa variáveis da placa sem firmware compatível ou um depurador real configurado e validado.
