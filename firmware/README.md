# Firmware de telemetria PRISMA

Este diretório contém um encoder JSON em C99, uma aplicação usando HAL e um simulador host. **Ainda não existe imagem validada para gravação na DEMOEM/MCF51EM256.**

## Componentes

| Arquivo | Função |
| --- | --- |
| `include/prisma_telemetry.h` | Estruturas de amostra e estado. Tensões em mV e correntes em mA na entrada do encoder. |
| `src/prisma_telemetry.c` | Geração de JSON sem formatação de ponto flutuante, com verificação de capacidade do buffer. |
| `include/prisma_hal.h` | Contrato para inicialização, amostragem sincronizada, transmissão e leitura de estados. |
| `src/main.c` | Loop de aquisição e envio, com mensagem de estados a cada 1000 amostras. |
| `ports/host_simulator.c` | Sinais sintéticos no computador, sem acesso a hardware. |
| `ports/mcf51em256_port.example.c` | Port pendente, bloqueado por `#error` até configurar o hardware real. |

## Compilar e testar no computador

Com GCC:

```bash
gcc -std=c99 -Wall -Wextra -Werror -Ifirmware/include firmware/src/main.c firmware/src/prisma_telemetry.c firmware/ports/host_simulator.c -lm -o prisma-host.exe
./prisma-host.exe > telemetria-host.jsonl
```

No PowerShell, use `.\prisma-host.exe` para executar. O simulador produz 5000 amostras a 1000 amostras/s em tempo simulado e cinco mensagens de estado. Ele escreve tão rápido quanto o stdout permitir, sem tentar reproduzir o tempo real ou a capacidade de uma SCI. Não confundir esse teste com transmissão física.

A suíte pytest compila o código com warnings tratados como erros, interpreta a saída com o parser real do aplicativo e verifica RMS, frequência e fator de potência. Também testa limites de buffer, valores int32 extremos e escape de texto do LCD.

O exemplo de projeto `examples/projects/host-gcc.json` permite compilar pela interface e gerar o mapa do linker.

## Integração ColdFire

Seguir [o roteiro da bancada](../docs/bancada-demoem.md). A implementação da HAL depende da revisão efetiva da placa, dos registradores, clock, timer, SCI, ADC, GPIO e LCD. Startup, linker e bibliotecas devem vir da toolchain/BSP correspondente e respeitar suas licenças.

O timestamp usa milissegundos em uint32; uma sessão precisa ser reiniciada após reset do dispositivo ou antes do rollover. Cada amostra deve representar canais sincronizados. `currents_present=0` omite os canais de corrente, sem inventar leituras.

A transmissão JSON tem custo significativo. Dimensionar `tamanho_da_linha × amostras_por_segundo × 10` para 8N1, mais estados e folga. 115200 baud pode ser insuficiente até para algumas centenas de amostras/s, e não comporta automaticamente as taxas necessárias para h15. A taxa do modo demo não é promessa de desempenho do hardware.

BDM não equivale a uma porta COM. A interface não acessa variáveis da placa sem firmware compatível ou um depurador real configurado e validado.
