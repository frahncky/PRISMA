# Roadmap — PRISMA

## Fase 1 — protótipo v0.1
- [x] Aplicativo desktop Windows em Python/PySide6
- [x] Editor de código C para abrir e salvar arquivos
- [x] Osciloscópio, fasores, harmônicas e valores RMS em modo demonstração
- [x] Leitura serial COM e protocolo JSON v1
- [x] Testes do parser e cálculos
- [ ] Testes com placa DEMOEM real

## Fase 2 — aquisição real
- [ ] Identificar USB VID/PID, drivers BDM e porta COM
- [ ] Documentar jumpers SCI, pinos e condicionamento de sinais
- [ ] Firmware de telemetria ColdFire V1
- [ ] Indicadores físicos de LEDs, GPIO, ADC e LCD
- [ ] Histórico CSV/SQLite

## Fase 3 — programação e depuração
- [ ] Adaptador CodeWarrior / compilador C para MCF51EM256
- [ ] Build, relatório de erros e mapa de memória
- [ ] Gravação Flash via PEmicro com confirmação explícita
- [ ] Breakpoints e inspeção de registradores

## Fase 4 — instrumentação avançada
- [ ] Estimação dinâmica de frequência
- [ ] Calibração e janelamento
- [ ] Harmônicas, THD, potências P/Q/S e fator de potência
- [ ] Fasores interativos, relatórios e exportação
- [ ] Plugins para outras placas
