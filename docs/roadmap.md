# Roadmap — PRISMA

## Critério de conclusão

`[x]` significa entrega implementada e testada no ambiente indicado. Testes em computador e simulador não substituem homologação na DEMOEM. O usuário possui a placa, mas ela não estava disponível nesta sessão; revisão, pinagem, CodeWarrior e PEmicro ainda precisam ser identificados.

| Fase | Software | Encerramento da fase |
| --- | --- | --- |
| 1 · Protótipo | Disponível e testado em computador | Pendente de teste com DEMOEM real |
| 2 · Aquisição | CSV/SQLite, diagnóstico e telemetria de estados disponíveis; encoder C testado no host | Pendente de port e validação de hardware |
| 3 · Programação e depuração | Executor de toolchain e cliente GDB/MI testados com processos de teste; build C host real validado | Pendente de compatibilidade CodeWarrior/PEmicro e testes físicos |
| 4 · Instrumentação avançada | Cálculos, calibração, janelas, fasores, relatórios, perfis e API de plugins disponíveis | Software entregue para JSON/CSV; validação metrológica e drivers de hardware específicos pendentes |

## Fase 1 — protótipo

- [x] Aplicativo desktop em Python/PySide6, voltado ao Windows
- [x] Editor C para abrir e salvar arquivos
- [x] Osciloscópio, fasores, harmônicas e valores RMS em demonstração
- [x] Leitura serial e protocolo JSON v1
- [x] Testes automatizados do parser, cálculos e interface sem tela
- [ ] Testes com placa DEMOEM real — depende da bancada disponível

## Fase 2 — aquisição real

- [x] Coleta de portas, VID/PID e metadados USB pelo aplicativo
- [x] Script Windows de inventário USB, COM e versões dos drivers
- [ ] Identificação efetiva dos drivers BDM, VID/PID e COM da DEMOEM
- [x] Roteiro de integração e tabelas para documentar a revisão da placa
- [ ] Confirmação dos jumpers SCI, pinos e condicionamento no manual da revisão
- [x] Encoder de telemetria C, interface HAL, aplicação e simulador host compilados e testados
- [ ] Port da HAL para ColdFire V1, startup/linker e firmware gravável na DEMOEM
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
- [ ] Receita CodeWarrior/ColdFire específica da instalação, compilada e validada
- [ ] Comando PEmicro específico do probe/versão, gravação física e recuperação validadas
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

## Evidências e documentação

- [Bancada DEMOEM](bancada-demoem.md): informações a coletar, orçamento serial e checklist de aceitação física.
- [Toolchain](toolchain.md): formato do projeto, execução, confirmação de gravação e limites do cliente GDB/MI.
- [Instrumentação](instrumentacao.md): métodos, semântica das potências, calibração, histórico e relatórios.
- [Firmware](../firmware/README.md): build host e requisitos do port ColdFire.
- [Plugins](plugins.md): perfis, protocolos incluídos e API de adaptadores instaláveis.

Para encerrar todas as fases, preencher e executar os critérios físicos. Não marcar os itens pendentes como concluídos somente por existir uma interface, um template ou um simulador.
