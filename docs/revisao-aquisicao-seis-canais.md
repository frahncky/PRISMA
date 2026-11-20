# PRISMA — revisão da aquisição real de seis canais (DEMOEM)

> **Tipo:** revisão técnica de projeto, não esquemático pronto para fabricação.
> **Data:** 20/11/2026. **Escopo:** DEMOEM + placa-filha MCF51EM256, esquema de referência DEMOEM rev. C. **Situação:** revisão documental; nenhuma conexão à rede elétrica ou ensaio metrológico foi realizado nesta revisão. A revisão física da placa do usuário continua por confirmar.

## Decisão de arquitetura

Manter o **MCF51EM256 como unidade de aquisição** e o **ESP32-S3 somente como gateway/HMI/IoT**. Criar um módulo externo de **seis canais analógicos condicionados e isolados no lado de medição**, com três entradas de tensão e três de corrente. Os seis sinais entregues à DEMOEM são de **baixa tensão compatível com o ADC**. Não desenhar nem encomendar a PCB final até concluir os testes de mapeamento, faixa, temporização e calibração abaixo.

```text
   L1/L2/L3/N (domínio perigoso; não acessar na bancada sem proteções)
             │
    [3 transdutores de tensão ISOLADOS]
    [3 TCs/sensores de corrente adequados]  ← proteções de secundário
             │ (saídas isoladas, de baixa energia)
    [AFE 6 canais: burden quando exigido, filtro,
     offset/referência, amplificador, proteção e testes]
             │ (0–VREF nos pinos; referência definida)
    ┌────────▼────────────────────────┐
    │ DEMOEM / MCF51EM256             │
    │ Va/Vb/Vc + Ia/Ib/Ic             │
    └────────┬────────────────────────┘
             └── SCI3 UART → ESP32-S3 → PRISMA / tela / IoT
```

**Regra obrigatória:** entradas de rede e saídas USB/PC/ESP32 nunca compartilham o domínio perigoso. Exigir isolamento galvânico apropriado, proteção contra falhas e revisão elétrica antes de qualquer teste energizado. A DEMOEM e seus conectores não são entrada direta de rede.

## 1. Matriz de sinais e estado de verificação

Os nomes abaixo vêm do manual NXP DEMOEM rev. 1.02 (J29/J38) e do esquema DEMOEMSC rev. C, folha 4/10 indicada no PDF como página 3/9. A correspondência com o firmware foi conferida em `firmware/codewarrior/EM256 Demo/Sources/main.c`.

| Grandeza | Canal DEMOEM | ADC no firmware | J38: linha lógica proposta | Tipo de entrada | Estado |
| --- | --- | --- | --- | --- | --- |
| Va | AD4 | ADC3 | 1 | Simples | Leitura bruta com QE8 já validada |
| Vb | AD5 | ADC1 | 2 | Simples | Leitura bruta com QE8 já validada |
| Vc | AD6 | ADC2 | 3 | Simples | Leitura bruta com QE8 já validada |
| Ia | DADP0 / DADM0 | ADC3, diferencial DAD0 | 4 | Diferencial | Port de 6 canais existe; validar fisicamente |
| Ib | DADP1 / DADM1 | ADC1, diferencial DAD1 | 5 | Diferencial | Port de 6 canais existe; validar fisicamente |
| Ic | DADP2 / DADM2 | ADC2, diferencial DAD2 | 6 | Diferencial | Port de 6 canais existe; validar fisicamente |

**ATENÇÃO:** linhas 1–6 acima representam a ordem funcional da documentação e dos sinais no esquema, **não a identificação comprovada da numeração física dos 12 pinos de J38**. Antes de usar um cabo/adaptador, identificar pino 1, lado MCU e lado QE8 por serigrafia, esquema **e teste de continuidade com a placa desenergizada**. Registrar foto e tabela pino-físico → net em bancada. Não presumir que uma coluna de J38 inteira seja GND.

- **J38:** com os seis jumpers instalados, liga os PWM filtrados do MC9S08QE8 às seis entradas. Para cada sensor externo, **retirar o jumper do respectivo canal** e verificar que o sinal do QE8 ficou desconectado. Para aquisição real completa, retirar os seis e identificar o **lado MCU** antes de conectar a saída condicionada.
- **J29:** três jumpers colocam **DADM0/1/2 em GND** (configuração de fábrica). Com a abordagem provisória descrita abaixo, mantê-los instalados **somente se** os três sinais DADP permanecerem inteiramente entre GND e VREF. Se o AFE exigir leitura diferencial real com referência de meio de escala em DADM, será necessário retirar os respectivos jumpers, redesenhar o AFE e validar a configuração do ADC. **Não aplicar sinal negativo em relação a VSSA a nenhum pino.**
- **J1 (MCU_PORT):** alternativa de breakout de sinais, VDD e retorno, conforme esquema. A pinagem da documentação principal não substitui a confirmação física da orientação do conector.
- **J6, SCI3:** caminho de telemetria separado dos sinais analógicos; não usar RS-232 ±12 V na UART lógica de 3,3 V.

### Dois modos que não podem ser confundidos

1. **Demonstração**: QE8 + J38 → ADC; bom para conferir software e aquisição, **não** comprova escala elétrica, sensores nem isolação.
2. **Medição real**: sensores isolados + AFE externo → ADC com QE8 desconectado; requer calibração e testes de erro, fase, faixa, não saturação e segurança.

O modo contínuo atual usa `PRISMA_CHANNELS=6` por padrão no firmware, enquanto a validação descrita de forma robusta em bancada é **três canais brutos**. Ativar uma máscara de seis canais no software **não prova** que os seis sinais já foram medidos adequadamente.

## 2. AFE: requisitos antes de escolher componentes

**Topologia de primeira revisão (não é circuito homologado):**

| Bloco | Solução proposta | Decisão dependente de ensaio |
| --- | --- | --- |
| TV-A/B/C | Três transdutores isolados com saída baixa tensão, independentes e adequados ao tipo de ligação | Faixa 127/220 V fase-neutro e/ou fase-fase; precisão e resposta de fase |
| TC-A/B/C | Três TCs de medição, ou sensores de corrente isolados, com relação nominal documentada | Faixa real de corrente, banda, exatidão, saturação e tipo de saída |
| Burden e proteção | Burden individual **apenas para TC que exija burden externo**, com proteção apropriada de secundário | Dimensionar por corrente secundária máxima, tensão-alvo, potência dissipada e especificação do TC. **Nunca deixar secundário de TC convencional aberto quando energizado** |
| Offset analógico | Tensão de polarização estável, tipicamente próxima de VREF/2 (≈1,65 V se VREF=3,3 V) | Avaliar ruído, deriva e impedância; não usar simplesmente divisor de alta impedância sem buffer quando a carga exigir |
| Ganho / filtro | Condicionamento por canal + filtro anti-aliasing, componentes toleranciados | Verificar headroom, fase relativa, impedância de saída e frequência de amostragem |
| Proteção ADC | Resistência série dimensionada, limitação/clamp compatível e estratégia para sobrecarga | Provar que correntes de injeção e tensão absoluta ficam dentro dos limites do **datasheet**, inclusive com placa desligada |
| Alimentação AFE | Fonte SELV regulada, sem retroalimentação do USB ou de VDD | Orçamento de corrente, GND/retorno, proteção e barreira galvânica |

**Faixa de primeiro protótipo:** sinal condicionado próximo de 1,65 V em repouso e, sob excitação nominal de bancada, dentro de uma margem conservadora como **0,3–3,0 V** no pino para VREF=3,3 V. Isto é uma **meta de projeto para margem dinâmica**, não especificação autorizada do ADC; confirmar VREFH/VREFL, limites absolutos e precisão no datasheet do MCF51EM256.

**Correntes diferenciais no firmware existente:** com DADM preso ao GND por J29 e saída de corrente polarizada positiva em DADP, a conversão diferencial mede uma diferença sempre positiva; o firmware trata os resultados como contagens e os cálculos AC removem a média. Essa abordagem permite aproveitar o software atual, mas não equivale a usar uma entrada bipolar centrada em zero. Comparar resolução/linearidade e rejeição de ruído com uma variante de AFE que alimente DADP/DADM diferencialmente (somente depois de validar a configuração do ADC e alterar/ensaiar o firmware se necessário).

**Não fixar valores finais** de resistor burden, divisor, ganho, capacitores de filtro, diodos de clamp ou conectores enquanto não se conhecer o modelo exato de cada transdutor, a faixa nominal/máxima e o relatório de ensaios. Não copiar módulos ZMPT/TC genéricos sem analisar o amplificador e a excursão real da saída; seus valores e qualidade variam.

## 3. Temporização, banda e transporte — pontos críticos

- No firmware `main.c`, o timer MTIM1 marca ~**1995,5 amostras/s**; o modo de seis canais compartilha ADC3 entre Va/Ia, ADC1 entre Vb/Ib e ADC2 entre Vc/Ic. Os três canais de tensão são disparados em sequência de registradores e as correntes **depois**, com conversão descartada quando `PRISMA_SETTLE=1`; simultaneidade exata de tensão/corrente **não existe**.
- O atraso nominal tensão → corrente mencionado no código é **~40 µs**, equivalente a ~**0,864° em 60 Hz**. Isso é **estimativa, não calibração**: aferir por osciloscópio/referência e registrar `delay_us` de cada canal. Validar erros de FP e de P com carga resistiva e indutiva/capacitiva conhecida.
- Em ~1995,5 amostras/s, Nyquist é ~**997,7 Hz**. A harmônica h15 em 60 Hz ocorre a **900 Hz**, deixando só ~98 Hz de faixa de transição para o anti-aliasing. **Não prometer THD/h15 metrológico** sem projetar e testar o filtro ou sem elevar a taxa de aquisição/usar AFE ou ADC externo adequado.
- UART 115200 8N1 oferece teto teórico de **11 520 bytes/s**. Uma rajada binária de 500 amostras × 6 canais ocupa cerca de **6019 bytes**, ou **~0,52 s de transmissão**, fora o overhead. O resumo `0x02` preserva as somas mesmo quando a serial não transmite todas as amostras. Conferir perdas, CRC, sequência e temporização real.
- A autocalibração interna do ADC **não substitui** calibração de ganho, offset e fase de sensores + filtros + ADC.

## 4. Plano de validação em bancada, sem rede elétrica

**Não usar tensão de rede neste plano.** Começar com a DEMOEM isolada de sensores reais e com gerador de funções/fonte de baixa tensão limitada; instrumentação de teste apropriada e inspeção da PCB desenergizada.

| Etapa | Ensaio | Evidência/critério de aceite |
| --- | --- | --- |
| A0 | Fotografar as duas faces, identificar revisão, J29/J38, J1 e orientação do pino 1 | Fotos legíveis + tabela de continuidade J38/QE8/ADC, sem ambiguidade |
| A1 | QE8 ligado, 3 canais; gravar logs e conferir firmware/estado | Amostras e frequência coerentes com o gerador, registro da versão e `adc_timeout_mask` |
| A2 | QE8 desligado dos seis canais, entradas sem estímulo acidental | Não confundir entradas flutuantes com sinal zero; medir os níveis DC definidos pelo AFE |
| A3 | Um canal de cada vez: aplicar baixa tensão senoidal e varrer amplitude/frequência | Sem recorte, sobretensão, ruído excessivo ou saturação; registrar offsets e escala |
| A4 | Três tensões + três correntes **sintéticas** com defasagens conhecidas | `0x3F` sem canais trocados; sinal, ordem, sequência, fase e FP coerentes |
| A5 | Medir diferença de instante Va/Ia, Vb/Ib, Vc/Ic; testar `PRISMA_SETTLE` | Atrasos medidos por canal e correções `delay_us` armazenadas |
| A6 | Enviar rajadas contínuas e resumos por 15 min via CH340 | CRC, `seq`, perdas, overrun e latência auditados, sem prometer perda zero antes do teste |
| A7 | Varrer frequência até o limite analógico projetado e acima de Nyquist em sinal seguro | Resposta do filtro e alias medidos; ordem harmônica liberada conforme resultado |
| A8 | Calibrar com fontes/instrumentos de referência documentados | Tabela com 3+ pontos por canal: ganho, offset, atraso de fase, RMS, frequência, P e THD |
| A9 | Revisão formal de segurança do AFE, isolação, proteção de TC, layout e fontes | Aprovação de esquema/requisitos **antes** da primeira conexão à rede |

**Alvos exploratórios, não classe de exatidão:** após calibração e em bancada de baixa tensão, pode-se adotar ≤1% de desvio RMS, ≤1° de erro de fase e ≤0,1 Hz de desvio de frequência em 50/60 Hz como **critérios internos iniciais a serem acordados**; os resultados reais devem ser medidos e documentados, não presumidos.

### Registro de bancada (copiar uma linha por ensaio)

| Data | PCB/rev | FW/commit | Grandeza/canal | J38 / J29 | Fonte e amplitude | fs medido | Vbias mínima/máxima | Referência | Erro RMS | Erro fase | CRC/perdas | Resultado |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| a preencher |  |  |  |  |  |  |  |  |  |  |  |  |  |

## 5. Critérios para liberar o esquemático da PCB AFE v1

- [ ] Revisão física e numeração dos pinos de J38/J29/J1 **registradas e verificadas**.
- [ ] Modelos exatos dos três TVs e três TCs/sensores definidos, com datasheets e faixas.
- [ ] Corrente de curto/sobrecarga, tensão de saída máxima e proteção de secundários dimensionadas.
- [ ] Topologia GND/referência e barreira de isolamento revisadas para USB/ESP/HMI.
- [ ] Entrada em 0–VREF e limites de injeção verificados com DEMOEM energizada **e desligada**.
- [ ] Filtro, impedância e banda escolhidos em função da **harmônica máxima realmente validada**.
- [ ] Ponto de operação, ruído, ganhos, offsets e fase testados nos seis canais.
- [ ] Separação mecânica de bornes perigosos e baixa tensão, espaçamentos de isolação e gabinete revisados.
- [ ] Esquemático revisado por responsável técnico, ERC/DRC e plano de testes assinados.

**Protótipo intermediário já disponibilizado:** [AFE-LV A0 (KiCad)](../cad/afe-lv/README.md) contém esquemático e PCB apenas de interface de **seis sinais SELV já isolados e condicionados**, com RC de EMI e sem proteção contra rede. Não é o AFE metrológico. **Próxima entrega após este checklist:** AFE v1 completo com transdutores selecionados e datasheets, BOM de fabricante, anti-alias dimensionado, isolamento/proteção, ERC/DRC e validação física. Sem as medições acima, uma PCB de medição final seria hipótese insegura.

## Fontes primárias e arquivos relacionados

- [NXP — DEMOEM User Manual rev. 1.02](https://www.nxp.com/docs/en/user-guide/DEMOEMUM.pdf), §7.12 (J29), §7.14 (J38).
- [NXP — DEMOEMSC, esquema rev. C](https://www.nxp.com/downloads/en/schematics/DEMOEMSC.pdf), folhas 1/10 (MCU), 4/10 (gerador QE8/J38), 5/10 (SCI).
- [NXP — AN3949: ADC16 e sincronismo com PDB](https://www.nxp.com/docs/en/application-note/AN3949.pdf).
- [Ligações hardware do PRISMA](ligacoes-hardware-demoem.md), [bancada](bancada-demoem.md), [instrumentação](instrumentacao.md) e [firmware ColdFire](../firmware/README.md).
