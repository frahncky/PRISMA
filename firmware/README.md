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
| `codewarrior/EM256 Demo/Sources/main.c` | Firmware de bancada validado: rajadas de 500 amostras AD4/AD5/AD6 a ~1995 Hz (MTIM1), SCI3 a 115200 8N1 (`PRISMA_SCI_BAUD`) e trim do oscilador em 0x3FE/0x3FF. |
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

Para compilar, abra `EM256 Demo.mcp` e execute **Make**. Para gravar, abra a configuração PEmicro incluída no projeto, carregue `bin/Project.abs`, confirme **Connect/OK**, aguarde programar/verificar e use **Run/Go**. Depois da gravação, o cabo PEmicro pode ser removido; permanecem a alimentação da placa e o CH340.

O timestamp usa milissegundos em uint32; uma sessão precisa ser reiniciada após reset do dispositivo ou antes do rollover. Cada amostra deve representar canais sincronizados. `currents_present=0` omite os canais de corrente, sem inventar leituras.

A transmissão JSON tem custo significativo. Dimensionar `tamanho_da_linha × amostras_por_segundo × 10` para 8N1, mais estados e folga. 115200 baud pode ser insuficiente até para algumas centenas de amostras/s, e não comporta automaticamente as taxas necessárias para h15. A taxa do modo demo não é promessa de desempenho do hardware.

BDM não equivale a uma porta COM. A interface não acessa variáveis da placa sem firmware compatível ou um depurador real configurado e validado.
