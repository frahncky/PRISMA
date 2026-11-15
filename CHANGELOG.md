# Histórico de versões

## Em desenvolvimento — integração DEMOEM + ESP32-S3 (sem alteração da versão do aplicativo)

- README principal atualizado com arquitetura do sistema completo, diagrama, ligações e estado de cada subsistema.
- Protótipo de gateway ESP32-S3 em PlatformIO para SCI/UART → USB CDC, painel web responsivo, resumos RMS AC/P e MQTT/TLS opcional.
- Guia de integração elétrica e procedimentos de alimentação, aquisição por sensores isolados, tela e bateria.
- Credenciais do gateway excluídas do versionamento por `.gitignore`.
- Instrumentação no formato de multimedidor: quadro V, I, P, Q, S, FP (ind/cap) e ângulo por fase + trifásico; frequência, THD e energia ativa/reativa acumuladas (kWh/kvarh, botão Zerar).
- Instrumentação em duas faixas para caber em 1360×720: tensão de linha no quadro de medições, desequilíbrio e sequência como indicadores, aviso só quando há problema; removidos fator de crista, componentes +/−/0, origem, calibração, versão e destaque do nome da placa.
- Novo ícone: mostrador de medidor com as três fases em arco e uma forma de onda; `prisma.ico` com 16–256 px.
- Painel touch como medidor inteligente (abre no monitor pedido com `--screen`, fontes maiores): abas Visão geral (tela inicial: valores, indicadores, formas de onda, fasores e harmônicas numa tela só), Valores, Formas de onda, Fasores e harmônicas, Energia e demanda e Tendências; relógio, energia importada/exportada/reativa, demanda de 15 min e máxima, mín/máx por fase. Sequência inversa vira alerta.
- Gráficos com Va/Vb/Vc e Ia/Ib/Ic (legenda no título e rótulo na ponta dos fasores); FP com a natureza da carga (Indut./Capac.); coluna Trifásico indica "média" (V, I) ou "soma" (P, Q, S).
- Fasores com a fase A como referência (0°) por padrão e correntes Ia/Ib/Ic tracejadas no diagrama, na janela principal e no painel.
- README e banner atualizados com a identidade nova e o painel touch.
- Correção: energia, demanda e tendências passam a usar o relógio do computador e só somam quando chega amostra nova. Em rajada (t = seq × 10 s) cada bloco contava 10 s em vez de ~0,55 s, inflando energia e demanda em ~18×.
- Voz (perguntas, microfone e fala) retirada do painel por enquanto; `prisma.core.query`/`speech` e `ui/microphone.py` continuam no código para retomar depois.
- Calibração em duas etapas para a DEMOEM. **1 · ADC com tensão DC**: assistente que mostra a contagem média ao vivo, registra um ponto por rajada (tensão do multímetro × contagem), recusa saturação e ajusta a reta contagem → volts no pino com o maior desvio de cada canal; o perfil ganha `pin_volts: true`. **2 · Sensores com multímetro**: agora também para correntes (Ia/Ib/Ic) e escala o offset junto com o ganho. A calibração ativa é lembrada na próxima abertura.
- Medição contínua na DEMOEM (`PRISMA_CONTINUOUS`): amostragem sem pausa na interrupção do MTIM1, janelas de ~1 s em ciclos inteiros da fase A e quadro de resumo `0x02` com Σx, Σx² e Σv·i. O app calcula RMS, frequência (erro < 0,0001 Hz no simulador) e potência exatos e integra energia e demanda sem lacunas pelo relógio da placa; rajadas seguem para os gráficos. Firmware compilado no CodeWarrior 6.3, ainda não gravado na placa.
- 6 canais na DEMOEM (`PRISMA_CHANNELS 6`): correntes nas entradas diferenciais DAD0/DAD1/DAD2, convertidas no mesmo ADC logo após a tensão, com conversão de assentamento. O app usa Vref/32768 por contagem nas correntes, mostra os 6 canais na aba Hardware/ADC (correntes tracejadas) e aplica o `delay_us` da calibração também à potência dos resumos. Compilado no CodeWarrior; ainda não gravado nem validado na placa.
- Aba Hardware/ADC mostra a linha "Medição contínua" (janela, frequência, RMS por canal, janelas perdidas) e voltou a caber em 1360×768 (rótulos com quebra faziam a página rolar).
- Comandos PC → placa pela SCI3 (firmware rev 3, quadros `0x10`/`0x11` com CRC, `prisma_command.h`): identificar a placa (revisão, canais, contadores de erro), escolher rajada a cada 1/5/30 janelas ou nenhuma e rodar a autocalibração de hardware do ADC. O app identifica a placa sozinho no primeiro resumo e mostra os botões na aba Hardware/ADC. Precisa do fio `CH340 TXD → J6 PTC0/RX3`. Compilado no CodeWarrior; ainda não gravado nem validado na placa.
- Build do firmware por `scripts/compilar_demoem.ps1` (também no botão Compilar do app): o `CmdIDE /b /q` deixava aberta a janela "CodeWarrior Error" (o IDE 6.3 trava ao fechar sozinho, depois do build pronto).
- Aba Hardware/ADC cabe em 1360×768 também com 6 canais (linhas da tabela de 20 px; o padding do tema travava em ~30 px).
- **Sem compilação do firmware ESP32-S3 ou homologação física**; firmware ColdFire/ADC reais, tela TFT e bateria power-path seguem pendentes.

## 0.2.0

- Histórico SQLite por sessão, consulta, filtro temporal e exportação CSV.
- Correntes trifásicas opcionais; potência ativa, reativa da fundamental, aparente e fator de potência AC.
- Estimação de frequência de 40–70 Hz, ajuste harmônico simultâneo e janelas retangular/Hann.
- Calibração linear por canal, metadados rastreáveis e relatório HTML autossuficiente.
- Fasores selecionáveis e referência visual relativa a uma fase.
- Perfis declarativos de dispositivo, inventário USB/serial e telemetria LED/GPIO/ADC/LCD.
- API de protocolos por entry points e plugin CSV trifásico, carregado sob seleção do perfil.
- Leitor serial com reconstituição de linhas fragmentadas e limite de tamanho.
- Projetos de toolchain, execução assíncrona, cancelamento, log e mapa de memória.
- Hash do artefato e confirmação explícita de gravação; cliente GDB/MI configurável.
- Encoder de firmware C, aplicação HAL e simulador host compilados e testados com GCC.
- Guia de bancada e roadmap distinguindo entrega de software de homologação física.
- CI configurado para Linux e Windows.
- Bibliotecas Qt instaladas no runner Linux e PySide6 limitado a versões anteriores à 6.12 devido a aborto reproduzido no encerramento do Python 3.11 com 6.12.0.

A implementação física ColdFire/PEmicro permanece pendente: a placa não estava disponível durante esta entrega. Nenhum firmware foi gravado nem periférico físico foi homologado.

## 0.1.0

- Protótipo desktop, editor C, instrumentos em demonstração e leitura serial JSON.
- Limites de Nyquist, testes de cálculos e interface, registro CSV e apresentação do projeto.
