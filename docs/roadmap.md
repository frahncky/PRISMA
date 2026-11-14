# Roadmap — PRISMA

## Critério de conclusão

`[x]` significa entrega implementada e testada no ambiente indicado. A comunicação, gravação e leitura ADC bruta foram validadas na DEMOEM real; isso ainda não substitui calibração metrológica nem aquisição sincronizada.

| Fase | Software | Encerramento da fase |
| --- | --- | --- |
| 1 · Protótipo | Disponível e testado em computador | Pendente de teste com DEMOEM real |
| 2 · Aquisição | CSV/SQLite, diagnóstico e telemetria de estados disponíveis; encoder C testado no host | Pendente de port e validação de hardware |
| 3 · Programação e depuração | Executor de toolchain e cliente GDB/MI testados com processos de teste; build C host real validado | Pendente de compatibilidade CodeWarrior/PEmicro e testes físicos |
| 4 · Instrumentação avançada | Cálculos, calibração, janelas, fasores, relatórios, perfis e API de plugins disponíveis | Software entregue para JSON/CSV; validação metrológica e drivers de hardware específicos pendentes |
| 5 · Gateway, touch, bateria e IoT | Firmware ESP32-S3 de referência e web HMI versionados; projeto power-path documentado | Build ESP32-S3, UART/USB, tela física, MQTT/TLS e bateria devem ser testados em bancada |

## Fase 1 — protótipo

- [x] Aplicativo desktop em Python/PySide6, voltado ao Windows
- [x] Editor C para abrir e salvar arquivos
- [x] Osciloscópio, fasores, harmônicas e valores RMS em demonstração
- [x] Leitura serial e protocolo JSON v1
- [x] Testes automatizados do parser, cálculos e interface sem tela
- [x] Testes de gravação, execução e serial com placa DEMOEM real

## Fase 2 — aquisição real

- [x] Coleta de portas, VID/PID e metadados USB pelo aplicativo
- [x] Script Windows de inventário USB, COM e versões dos drivers
- [x] Identificação do PEmicro para BDM e do CH340 como porta COM
- [x] Roteiro de integração e tabelas para documentar a revisão da placa
- [x] Confirmação e teste da SCI3 em J6 e do CH340 externo
- [x] Encoder de telemetria C, interface HAL, aplicação e simulador host compilados e testados
- [x] Projeto ColdFire V1 com startup/linker, SCI3 e ADC bruto gravável na DEMOEM
- [x] Recepção e tela de estados LED, GPIO, ADC e LCD informados pelo firmware
- [ ] Comparação dos indicadores com estados físicos da placa
- [x] Registro incremental CSV, com origem, correntes opcionais e calibração
- [x] Histórico SQLite por sessão, consulta, filtro temporal e exportação CSV
- [ ] Validação de vazão serial e sincronismo no hardware, incluindo transporte mais eficiente se necessário

## Fase 3 — programação e depuração

- [x] Projeto JSON com executáveis/argumentos configuráveis para a toolchain instalada
- [x] Execução assíncrona, saída de erros, cancelamento, timeout e exibição de mapa de memória
- [x] Projeto GCC host de referência compilável, com artefato e mapa reais
- [x] Hash do artefato e confirmação explícita antes de executar o gravador configurado
- [x] Cliente GDB/MI para conexão remota, breakpoints e inspeção de registradores; testes com processo de teste
- [x] Receita CodeWarrior 6.3.2/ColdFire compilada e validada
- [x] Gravação física pelo PEmicro/HI-WAVE e execução sem o USB BDM validadas
- [ ] Compatibilidade do servidor/depurador com ColdFire e teste real de breakpoint/registradores

## Fase 4 — instrumentação avançada

- [x] Estimação dinâmica de frequência entre 40 e 70 Hz
- [x] Perfis de calibração linear por canal e janelas retangular/Hann
- [x] Ajuste harmônico e THD com limite de Nyquist e validação de dados
- [x] Correntes trifásicas opcionais, P, Q1, S e fator de potência AC por fase
- [x] Fasores selecionáveis e referência visual absoluta ou relativa a uma fase
- [x] Relatório HTML autossuficiente e exportação de dados CSV/SQLite
- [x] Perfis declarativos para outras placas que transmitam PRISMA JSON v1
- [x] API de plugins Python instaláveis por entry points, carregados apenas ao selecionar o perfil
- [x] Plugin CSV trifásico com correntes opcionais e perfil de exemplo
- [ ] Drivers proprietários e validação específica em outras placas
- [ ] Calibração física, precisão, janelas e desempenho comparados com referência de bancada

## Fase 5 — sistema integrado DEMOEM + ESP32-S3

- [x] Código-fonte gateway ESP32-S3 para recepção UART, retransmissão USB CDC e avaliação de amostras JSON v1 (**sem compilação no hardware nesta entrega**)
- [x] Painel web responsivo para navegador touch com indicador de dados antigos e sem correntes
- [x] Lógica inicial de estimativa RMS AC e potência ativa em janela de um segundo
- [x] Código inicial de MQTT com TLS/CA, NTP, reconexão e contadores, sem credenciais no Git
- [x] Documentação de ligação, power-path, sensores, interfaces, riscos e testes
- [ ] Compilação e gravação do firmware ESP32-S3 com PlatformIO na placa adquirida
- [ ] Teste de encaminhamento USB CDC (115200 8N1), perdas, latência e qualidade temporal
- [ ] Seleção/integração do módulo TFT/touch real com driver e alimentação próprios
- [ ] Modelo de pack, BMS, carregador power-path, DC/DC e bateria testados e certificados
- [ ] Validação de segurança da rede HTTP e de MQTT/TLS com broker real
- [ ] Integração com aquisição física e firmware ColdFire autenticado/calibrado

## Evidências e documentação

- [Gateway ESP32-S3](../gateway/esp32s3/README.md): firmware e etapas de montagem/compilação, sem validação física.
- [Ligações DEMOEM](ligacoes-hardware-demoem.md): alimentação, sensores, touch, bateria e IoT.
- [Bancada DEMOEM](bancada-demoem.md): informações a coletar, orçamento serial e checklist de aceitação física.
- [Toolchain](toolchain.md): formato do projeto, execução, confirmação de gravação e limites do cliente GDB/MI.
- [Instrumentação](instrumentacao.md): métodos, semântica das potências, calibração, histórico e relatórios.
- [Firmware](../firmware/README.md): build host e requisitos do port ColdFire.
- [Plugins](plugins.md): perfis, protocolos incluídos e API de adaptadores instaláveis.

Para encerrar todas as fases, preencher e executar os critérios físicos. Não marcar os itens pendentes como concluídos somente por existir uma interface, um template ou um simulador.
