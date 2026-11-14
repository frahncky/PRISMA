# Integração e aceitação da DEMOEM

A placa DEMOEM/MCF51EM256 foi testada fisicamente em 14/11/2026. O firmware foi compilado no CodeWarrior 6.3.2, gravado pelo PEmicro/HI-WAVE e executado de forma autônoma. A telemetria foi recebida por um CH340 em COM4 a 19200 8N1.

## Resultado reproduzível

- Alimentar a DEMOEM pela fonte/bateria adequada.
- Para a serial, ligar somente `J6 PTC1/TX3 -> CH340 RXD` e `J6 GND -> CH340 GND`. Não ligar VCC/5 V/3,3 V. PTC0/RX3 é opcional e ficou desconectado no teste de transmissão.
- Remover J7/J8 ao usar o adaptador externo, evitando disputa com a interface serial da placa.
- Manter J36 em 1–2 para alimentar o MC9S08QE8 e J38 fechado para levar seus seis sinais PWM filtrados aos ADCs. J29 mantém DADM0/1/2 referidos ao GND na configuração de demonstração.
- No PRISMA, carregar `examples/profiles/demoem-ch340.json`, selecionar a COM do CH340 e conectar.

Mensagem observada no primeiro teste: `{"type":"status","source":"DEMOEM","message":"PRISMA SCI3 OK"}`. A versão trifásica fixa foi validada com `adc_timeout_mask: 0` em ADC3/AD4, ADC1/AD5 e ADC2/AD6. Em 40 leituras foram observadas faixas de 0–65535 em AD4/AD5 e 0–32032 em AD6. Os valores ainda são contagens brutas, sem calibração ou unidade física.


## Resultado do diagnóstico do multiplexador

O mapeamento do MCF51EM256 foi confirmado pela tabela de canais da AN3949: DAD0=ADC3/canal 1, DAD1=ADC1/canal 2, DAD2=ADC2/canal 3, AD4=ADC3/canal 4, AD5=ADC1/canal 5 e AD6=ADC2/canal 6. A alternância imediata de cada módulo entre entrada diferencial e simples fez o primeiro resultado carregar resíduos do canal anterior. A revisão validada mantém um canal fixo por módulo (`AD4`, `AD5`, `AD6`). Os canais diferenciais devem ser adquiridos futuramente em blocos separados, com tempo de assentamento comprovado.

Captura de 30 s em 14/11/2026 com o mesmo firmware: 175 linhas (5,8 linhas/s), `adc_timeout_mask` sempre 0. Os canais ficam em zero entre 45 % e 66 % do tempo e raramente altos juntos (30 % das linhas com dois ou mais canais diferentes de zero), coerente com três sinais defasados. AD5 satura em 65535 em 20 das 175 linhas; AD6 não passa de 32032. Os valores se agrupam em degraus próximos de múltiplos de ~8000 contagens. A 5,8 linhas/s não se reconstrói a forma de onda de 50/60 Hz: é necessária captura em rajada com taxa fixa.

### Rajada a ~1995 Hz (14/11/2026)

- **Gravação automática:** `scripts/gravar_demoem.ps1 -Build` compila, executa `FLASH SELECT/ERASE/ARM`, `LOAD … VERIFYALL`, `RESET` e `GO` pelo HI-WAVE sem interação, gravando o log em `bin/gravacao.log`.
- **Trim do oscilador:** o `FLASH ERASE` apaga o trim de fábrica em `0x3FE/0x3FF` (a SCI caiu para ~15 500 baud). O firmware agora grava o próprio trim (`PRISMA_ICS_TRIM`). `scripts/calibrar_trim_demoem.py COM4 [min] [max]` mede o baud real e encontrou **TRIM = 0xA7** (0x7F → 1,120×; 0x9F → 1,022×; 0xAF → 0,977×; 0xA7 → 1,000× do nominal, resolução da varredura ~1,5 %).
- **Resultado:** blocos de 500 amostras × 3 canais, `adc_timeout_mask` 0. Fundamental estimada em **51,85 Hz**, estável entre blocos; fasores AD4/AD5/AD6 separados por **120°**. Cada canal forma um lóbulo positivo em degraus (pico ~56 000–65 535) ocupando cerca de um terço do período e fica em zero no restante; THD estimada ~95 %. A frequência depende do oscilador do QE8 e do trim do EM256; confirmar com instrumento de referência antes de interpretar 51,85 Hz.

## Teste com USB único (gravação + telemetria pela PEmicro) — pendente

Objetivo: dispensar o CH340 usando a serial virtual do Embedded Multilink da própria DEMOEM. O diagnóstico de 13/11/2026 mostrou a interface `VID_1357&PID_0504&MI_01` ("USB and Serial Interface") **sem porta COM** (`serial_ports: []`). O manual cita o Terminal Window Utility do "P&E Embedded Multilink Toolkit" com opção "virtual USB COM"; não está confirmado que o Windows crie uma COM padrão acessível ao pyserial.

1. Desligar a placa. Desconectar o CH340 do J6.
2. Configurar os headers de 3 pinos conforme o DEMOEM User Manual v1.02, seções 7.2–7.3 (figuras 7-4 a 7-7). A serigrafia "PBE" é "P&E":
   - **J7 (TX_EN):** jumper entre o pino **P&E_RX** e o pino **central**. O pino da outra ponta ("TX") fica livre.
   - **J8 (RX_EN):** jumper entre o pino **P&E_TX** e o pino **central**. O pino "RX" fica livre.
   - **J9 (TX_SEL):** jumper entre o **central** e **PTC1** (SCI3, padrão).
   - **J10 (RX_SEL):** jumper entre o **central** e **PTC0** (SCI3, padrão).
   - Sem jumper em J7/J8 a serial virtual fica desabilitada (configuração usada com o CH340).
3. Ligar somente o USB tipo B da DEMOEM.
4. Instalar/atualizar os PEmicro Windows USB Drivers oficiais e rodar novamente `scripts\diagnostico_windows.ps1`.
5. Verificar se surgiu uma COM associada a `VID_1357`. Se não surgir, testar o P&E Terminal Utility a 19200 8N1; registrar o resultado e encerrar aqui (o PRISMA via pyserial exige COM).
6. Gravar o firmware pelo HI-WAVE e **fechar a sessão de depuração** (BDM e serial podem não operar simultaneamente).
7. No PRISMA, carregar `examples/profiles/demoem-pemicro.json`, selecionar a COM da PEmicro e conectar.
8. Critério de aceite: receber `PRISMA SCI3 OK` e telemetria ADC equivalente ao teste com CH340; depois regravar sem desconectar o cabo e confirmar que a COM volta a funcionar.

| Item | Resultado |
| --- | --- |
| COM criada pelo driver PEmicro | **Não** (14/11/2026): com J7/J8 habilitados, `MI_00`/`MI_01` enumeram na classe Jungo, driver Jungo 12.7.0.0 de 28/11/2017; nenhuma porta em `Win32_SerialPort`. Pendente repetir após atualizar os PEmicro Windows USB Drivers |
| Canal virtual pelo P&E Terminal Utility | Pendente (utilitário não instalado em `C:\PEMicro`) |
| Telemetria recebida no PRISMA | Pendente |
| Regravar e reconectar sem trocar cabo | Pendente |

> Para o detalhamento de alimentação, entradas de sensores, SCI/UART, ligação da tela touch, bateria recarregável e gateway IoT, veja o [guia de ligações da DEMOEM](ligacoes-hardware-demoem.md). Ele distingue recursos confirmados da placa de integrações propostas.

## 1. Identificar a bancada

No Windows conectado à placa, sem instalar nem trocar drivers automaticamente:

```powershell
.\scripts\diagnostico_windows.ps1 -OutputPath .\diagnostico-prisma.json
```

O JSON inclui dispositivos USB, VID/PID nos identificadores PnP, portas COM e versões dos drivers. A opção **Dados e dispositivos → Salvar diagnóstico serial/USB…** também coleta os metadados das portas visíveis ao aplicativo, em qualquer sistema suportado pelo pyserial.

Registrar localmente:

| Campo | Valor observado / evidência |
| --- | --- |
| Modelo e revisão da PCB | A identificar na serigrafia |
| MCU e encapsulamento | A confirmar na placa |
| Manual e esquemático correspondentes à revisão | A obter |
| VID/PID de BDM e da interface serial | A coletar pelo diagnóstico |
| Driver PEmicro e versão | A coletar pelo diagnóstico |
| CodeWarrior, compilador e versão | A identificar na instalação |
| Gravador/probe e número de série | A identificar |
| Tensão de alimentação e nível lógico da SCI | A confirmar no manual |

Um dispositivo BDM detectado não comprova uma porta COM. Não usar VID/PID de outros kits como identificação desta placa.

## 2. Confirmar ligações antes do port de firmware

O mapa mínimo validado é:

| Função | Pino/conector | Jumper | Referência no manual |
| --- | --- | --- | --- |
| SCI TX / RX / GND | J6 PTC1 / PTC0 / GND | J7/J8 removidos com CH340 | Manual e esquemático DEMOEM |
| ADC de diagnóstico | DADP0/1/2 com DADM0/1/2 | J36 1–2, J38 fechado, J29 padrão | Manual e esquemático DEMOEM |
| ADC Ia / Ib / Ic, se presentes | Pendente | Pendente | Pendente |
| LEDs e GPIO de leitura | Pendente | Pendente | Pendente |
| LCD | Pendente | Pendente | Pendente |
| Clock e referência ADC | Pendente | Pendente | Pendente |
| BDM e alimentação do probe | Pendente | Pendente | Pendente |

Confirmar sensores, escala ADC, offset, filtros anti-aliasing, sincronização entre canais e isolamento. Não conectar a rede elétrica diretamente ao MCU. Usar primeiro sinais de baixa tensão de um gerador de bancada compatível com os limites do circuito.

## 3. Portar e compilar

O encoder C e a aplicação em `firmware/src/` são compiláveis no computador. O port `firmware/ports/mcf51em256_port.example.c` está bloqueado com `#error` até que a HAL real seja implementada. Ele não configura registradores, não assume pinagem e não produz uma imagem gravável por si só.

1. Abrir `firmware/codewarrior/EM256 Demo/EM256 Demo.mcp` no CodeWarrior 6.3.2.
2. Implementar `prisma_hal_init`, `prisma_hal_next`, `prisma_hal_write` e `prisma_hal_status` conforme `firmware/include/prisma_hal.h`.
3. Conferir a disponibilidade de C99, `stdint.h` e `vsnprintf` na biblioteca do compilador; adaptar o encoder se necessário.
4. Usar timer de hardware e amostragem sincronizada. `time_ms` deve ser crescente; reiniciar a sessão antes de seu rollover de aproximadamente 49,7 dias ou após reset da placa.
5. Medir o tamanho real das mensagens e a capacidade da SCI. Não selecionar uma taxa de amostragem apenas pela taxa do modo demo.
6. Compilar no IDE e conferir MCU, linker, memória, warnings e símbolos de depuração.
7. Só então preencher o projeto JSON da toolchain e testar a execução pelo PRISMA.

## 4. Orçamento da serial

A capacidade aproximada em 8N1 é `baudrate / 10` bytes/s. A 115200 baud, são cerca de 11520 bytes/s antes de folgas e mensagens de estado. Uma linha de 140 bytes a 200 amostras/s exigiria 28000 bytes/s e não cabe nesse enlace.

Para analisar h15 de 60 Hz, a amostragem deve superar 1800 amostras/s. A taxa de 2400 amostras/s do demo **não comprova viabilidade de JSON pela SCI da DEMOEM**. Dependendo dos canais e da taxa de baud validada, será necessário um transporte binário/blocos, redução de canais ou outro enlace. Nunca decimar sem filtro anti-aliasing. Se o firmware não sustentar a transmissão, registrar perdas e corrigir o transporte antes de aceitar as medições.

## 5. Aceitação física

- [x] Identificação de drivers, toolchain e probe documentada.
- [x] SCI validada com mensagens JSON completas a 19200 8N1.
- [ ] ADC comparado com referência conhecida em pelo menos três pontos por canal.
- [ ] Frequência de 50/60 Hz e amplitudes comparadas com instrumento de referência.
- [x] Conversão dos ADC1/2/3 concluída sem timeout e variação bruta observada em DADP0/DADP2.
- [ ] LEDs/GPIO/LCD e escala física do ADC comparados com referência; a tela apenas reproduz a telemetria recebida.
- [ ] Histórico CSV/SQLite com dados reais, origem e coeficientes de calibração conferidos.
- [x] Build ColdFire reproduzível e mapa de memória gerado.
- [ ] Backup do firmware anterior, se permitido e suportado pelo probe, e plano de recuperação definidos.
- [x] Gravação PEmicro executada com confirmação e firmware reiniciado corretamente.
- [ ] Breakpoint, pausa, continuação e registradores conferidos na sessão real de depuração.
- [ ] Relatório local com data, versões, comandos, hashes, resultados e limitações.

Somente após anexar essas evidências devem ser encerradas as pendências físicas do roadmap. Não guardar licenças, credenciais, firmwares proprietários ou números de série em um repositório público.

### Serial a 115200 baud (14/11/2026)

`PRISMA_SCI_BAUD = 115200` (SBR 11, −1,74 % de erro de divisão com o barramento nominal). Em 20 s chegaram 24 rajadas válidas, nenhuma inválida e sem saltos de `seq`: ~1,2 blocos/s, seis vezes a taxa a 19200. Se a placa passar a ter erros de enquadramento, recalibrar o trim (`scripts/calibrar_trim_demoem.py`) ou voltar para 19200 recompilando com `PRISMA_SCI_BAUD=19200UL` e ajustando o perfil.

### Potenciômetros do QE8 (14/11/2026)

Gravação de 60 s girando os três potenciômetros: fora da transição, RMS e frequência quase não mudam (12–13,5 mil contagens, ~51,9 Hz). Em um ponto do giro o QE8 cortou AD4 e AD5 por ~6 s (dois blocos) e AD6 ficou com 1 a 2 pulsos. O PRISMA passou a mostrar “Sem sinal” e o RMS por fase nesses blocos, e a estimar a frequência pelo canal com mais sinal. A função exata de cada potenciômetro no programa de fábrica do QE8 não está documentada.

### Relógio da placa medido pelo PC (14/11/2026)

O período entre rajadas depende só do relógio da DEMOEM (timer de amostragem e baud), então o cristal do PC serve de referência. Com TRIM 0xA7 o relógio estava **1,9 % lento** (807,3 ms medidos contra 791,9 ms nominais), o que deslocava a frequência estimada e somava −3,6 % de erro no baud. Com **TRIM 0xA0** ficou em **+0,02 a +0,04 %**. A frequência do gerador QE8 medida passou a ser **~51,1 Hz** (provável 50 Hz nominal com o oscilador do QE8 ~2 % rápido). `scripts/calibrar_trim_demoem.py` agora usa esse método (≈0,05 % de resolução) e corrige o TRIM sozinho.
