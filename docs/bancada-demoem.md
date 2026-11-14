# Integração e aceitação da DEMOEM

A placa DEMOEM/MCF51EM256 foi testada fisicamente em 14/11/2026. O firmware foi compilado no CodeWarrior 6.3.2, gravado pelo PEmicro/HI-WAVE e executado de forma autônoma. A telemetria foi recebida por um CH340 em COM4 a 19200 8N1.

## Resultado reproduzível

- Alimentar a DEMOEM pela fonte/bateria adequada.
- Para a serial, ligar somente `J6 PTC1/TX3 -> CH340 RXD` e `J6 GND -> CH340 GND`. Não ligar VCC/5 V/3,3 V. PTC0/RX3 é opcional e ficou desconectado no teste de transmissão.
- Remover J7/J8 ao usar o adaptador externo, evitando disputa com a interface serial da placa.
- Manter J36 em 1–2 para alimentar o MC9S08QE8 e J38 fechado para levar seus seis sinais PWM filtrados aos ADCs. J29 mantém DADM0/1/2 referidos ao GND na configuração de demonstração.
- No PRISMA, carregar `examples/profiles/demoem-ch340.json`, selecionar a COM do CH340 e conectar.

Mensagem observada no primeiro teste: `{"type":"status","source":"DEMOEM","message":"PRISMA SCI3 OK"}`. A versão ADC foi validada com `adc_timeout_mask: 0`: DADP0 e DADP2 variaram, enquanto DADP1 permaneceu em zero na configuração testada. Os valores ainda são palavras brutas, sem calibração ou unidade física.


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
| COM criada pelo driver PEmicro | Pendente |
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
