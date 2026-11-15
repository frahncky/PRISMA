# Instrumentação avançada

## Configuração

A aba **Análise** seleciona referência de 60 Hz, 50 Hz ou estimação automática entre 40 e 70 Hz; a janela do ajuste pode ser retangular ou Hann. A referência visual dos fasores pode ser absoluta ou relativa a uma fase. Clique na ponta de um fasor para selecioná-lo e inspecione módulo e ângulo na aba Análise. Zoom e arraste dos gráficos continuam disponíveis pelo pyqtgraph.

O estimador usa cruzamentos ascendentes interpolados e mediana de períodos. Requer pelo menos três cruzamentos e rejeita sinal constante, faixa não suportada ou períodos instáveis. Não substitui um PLL nem garante desempenho em sinais muito distorcidos.

### Ligação do experimento: monofásico, bifásico ou trifásico

O seletor na barra de cima da janela principal (ou `--ligacao mono|bi|tri`, que fica salvo) diz quais fases têm sensores:

| Ligação | Fases | Tensão de linha | Total (coluna à direita) | Desequilíbrio e sequência |
| --- | --- | --- | --- | --- |
| Monofásico | A | — | "Total": a própria fase A | não se aplica |
| Bifásico | A e B | Vab | "Bifásico": P, Q e S somados; V e I médios das duas fases | não se aplica |
| Trifásico | A, B e C | Vab, Vbc, Vca | "Trifásico": P, Q e S somados; V e I médios das três fases | IEC 61000-4-30, limite do PRODIST |

- Os canais das fases fora da ligação continuam sendo lidos (aba Hardware/ADC), mas ficam fora do quadro de medições, dos totais, da energia, da demanda, das tendências, dos fasores, do osciloscópio, dos alertas, das respostas e do relatório. Na tela aparecem como "—".
- No bifásico, a tensão de linha é `Va − Vb` dos fasores. Ela serve tanto para duas fases de uma rede trifásica (127/220 V, 120°) quanto para fase dividida (180°).
- A ligação não descarta dados nem zera contadores. Ao trocar de experimento, zere energia e demanda (botão Zerar).
- A DEMOEM entrega as fases nos mesmos canais em qualquer ligação (fase A = `AD4` + `DADP0`, e assim por diante); os jumpers do J38 de cada caso estão em [ligações da DEMOEM](ligacoes-hardware-demoem.md#45-módulos-de-sensor-sugeridos).

## Método

O ajuste harmônico usa mínimos quadrados simultâneos com intercepto, seno e cosseno de cada ordem, ponderados pela janela escolhida. Isso reduz o vazamento entre ordens em janelas que não contêm um número inteiro de ciclos. A ordem máxima respeita tanto Nyquist (calculado pelo maior intervalo entre amostras) quanto a quantidade disponível de amostras. Timestamps precisam ser estritamente crescentes e canais sincronizados.

- **RMS:** valor eficaz AC no domínio do tempo, removendo a média da janela. Não inclui componente DC.
- **Fasor:** amplitude RMS da fundamental com referência cossenoidal. Uma senoide de fase zero tem ângulo de −90°.
- **THD Va:** raiz da soma dos quadrados das amplitudes harmônicas disponíveis dividida pela fundamental. Não é uma THD de banda ilimitada. Sem fundamental significativa ou sem h2 mensurável, fica indisponível.
- **P:** média do produto dos sinais AC de tensão e corrente da mesma fase.
- **Q1:** parte imaginária de `V1 × conjugado(I1)`; positiva para corrente atrasada. É potência reativa da fundamental, não uma decomposição completa da potência não ativa em sinais distorcidos.
- **S:** produto dos valores RMS AC de tensão e corrente.
- **FP:** `P/S`, com sinal; indisponível quando S é desprezível.

As potências só aparecem quando **todos** os canais `ia`, `ib`, `ic` estão presentes em todas as amostras da janela. A demonstração gera correntes de 5 A RMS com atraso nominal de `acos(0,9)`; os valores P/FP da janela variam ligeiramente com a distorção e o número de ciclos.

## Calibração

Carregue um JSON em **Dados e dispositivos → Carregar calibração…**. O formato está em `examples/calibracao-identidade.json`. Para cada canal configurado:

```text
valor_corrigido = valor_recebido × gain + offset
```

### Calibração da DEMOEM em duas etapas

Em **Análise → Fonte e calibração** (ou no menu **Dados e dispositivos**):

1. **ADC com tensão DC** (só a placa, sem rede elétrica). Abra o J38 para desligar o gerador QE8. Ligue um potenciômetro de 10 kΩ entre o 3,3 V e o GND da própria DEMOEM e leve o cursor, por 1 kΩ, aos pinos do J38 do lado do microcontrolador (pode ligar AD4, AD5 e AD6 juntos). Para cada ponto, meça a tensão no pino com o multímetro, digite e clique em **Registrar ponto**. O assistente mostra a contagem média e o ruído da última rajada, aceita um ponto por rajada nova e recusa canais saturados (0 ou 65535). Use 3 pontos ou mais (ex.: 0,3 V, 1,6 V e 3,0 V). O resultado é a reta `volts = contagem × gain + offset` por canal, com o maior desvio dos pontos (verde abaixo de 5 mV). O perfil salvo leva `"pin_volts": true` e o app continua mostrando "Tensão no pino ADC".
2. **Sensores com multímetro** (com transformador/divisor isolado e TCs ligados). Com carga estável, informe a tensão RMS de cada fase e, se houver canais de corrente, a corrente medida com alicate. O ganho de cada canal é multiplicado por `medido / exibido`, assim como o offset, e o perfil deixa de ser "volts no pino".

A **calibração de fase com carga resistiva** vem depois da etapa 2 e preserva a etapa em que o perfil está. A calibração ativa é guardada nas configurações do app e volta na próxima abertura; **Restaurar calibração identidade** a remove.

Os coeficientes são aplicados uma única vez na entrada, antes do buffer, cálculos e gravação. Ganhos devem ser positivos; os coeficientes devem ser finitos. Trocar a calibração encerra o registro e limpa o buffer, evitando misturar escalas. Nome e coeficientes são registrados na origem do CSV, nos metadados SQLite e no relatório. O aplicativo não ajusta os coeficientes sozinho: obtê-los com referência e método documentados na bancada.

## Histórico e relatório

- **Aquisição → Iniciar registro CSV…:** arquivo incremental de amostras.
- **Dados e dispositivos → Iniciar histórico SQLite…:** adiciona uma nova sessão ao banco selecionado, com origem, calibração, início e fim UTC.
- **Consultar histórico SQLite…:** lista sessões e quantidade de amostras; exporta uma sessão inteira ou intervalo de timestamps para CSV. O banco é aberto em modo somente leitura para a consulta.
- **Exportar relatório HTML…:** salva a última análise válida com origem, parâmetros, tensões, harmônicas e potências disponíveis. O HTML é autossuficiente e pode ser impresso em PDF pelo navegador.

CSV e SQLite armazenam valores já corrigidos. Os campos de corrente ficam vazios/NULL quando ausentes; não são substituídos por zero. Os timestamps das amostras são relativos à origem informada pelo firmware; não são horários UTC. O início UTC da sessão SQLite é o horário do computador.

Nenhum cálculo de software comprova calibração física, isolamento, precisão ADC ou sincronização da bancada.
