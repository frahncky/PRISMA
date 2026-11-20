# PRISMA AFE-LV A0 — primeira placa de interface 6 canais (KiCad)

**Estado: desenho preliminar não testado**. Os arquivos KiCad foram gerados programaticamente, com estrutura de expressões balanceada, **mas não passaram pelo ERC/DRC do KiCad (ferramenta indisponível neste ambiente)**. **Não encomendar, energizar com rede elétrica, nem associar a calibração a uma classe de exatidão antes das verificações abaixo.**

## Arquivos
- `prisma_afe_lv.kicad_sch`: 6 células IN → R1k → ADC, C10n à referência GND e ponto de teste.
- `prisma_afe_lv.kicad_pcb`: roteamento inicial em duas camadas, aproximadamente **124 × 120 mm** (contorno x=6..130, y=15..135), montagem 4 × M3.
- `BOM.csv`: lista de itens e alternativas a confirmar.

### ATENÇÃO — objetivo limitado deste protótipo

Este circuito **não** mede tensão/corrente de rede sozinho. Os seis sinais `IN_VA`, `IN_VB`, `IN_VC`, `IN_IA`, `IN_IB`, `IN_IC` devem vir de **sensores isolados E de um estágio de condicionamento externo** que garanta, em todas as condições (incluindo transientes e falhas), uma saída dentro dos limites absolutos do ADC do MCF51EM256 **com referência compatível**. O filtro R1k/C10n tem apenas função de EMI/ruído em alta frequência (fc ideal ≈ 15,9 kHz) e **NÃO é filtro anti-alias adequado para 1995,5 Sa/s**. Não existe aqui TV, TC, burden, isolador, op-amp, proteção completa, fonte nem conector de rede elétrica.

Usar `GND` desta PCB apenas como retorno dos **domínios SELV isolados comprovados**, nunca neutro, fase ou PE como substituto sem análise formal de segurança. A referência de todas as seis saídas deve ser compatível; se os sensores tiverem retornos separados que não possam ser unidos, **esta PCB não é adequada sem revisão**. Cabeamento e proteção externa precisam impedir sobretensão no ADC mesmo com a DEMOEM desligada.

## Pinout da interface de protótipo

Cada **entrada J1–J6** e **saída J7–J12** possui apenas 2 pinos:

| Canal | Entrada | Saída | Pino 1 | Pino 2 | Destino funcional da saída |
|---|---|---|---|---|---|
| Va | J1 | J7 | sinal | GND | AD4, ADC3 |
| Vb | J2 | J8 | sinal | GND | AD5, ADC1 |
| Vc | J3 | J9 | sinal | GND | AD6, ADC2 |
| Ia | J4 | J10 | sinal | GND | DADP0, ADC3; DADM0 ligado a GND por J29 **apenas se compatível com condicionamento** |
| Ib | J5 | J11 | sinal | GND | DADP1, ADC1; DADM1 idem |
| Ic | J6 | J12 | sinal | GND | DADP2, ADC2; DADM2 idem |

**J7–J12 não são footprint nem pinagem direta de J38.** São 6 conectores de 2 pinos para cabos/adaptador **a identificar por continuidade no J38/J1 físico, lado MCU**, com J38 desligando QE8. Não conectar um cabo 2×6 diretamente à DEMOEM por suposição. Pin 1 dos headers está marcado pelo pad retangular; ver orientação de PCB após abrir no KiCad.

### Decisões técnicas
1. Resistores 1k ±1% em série: limitam pequenas correntes transientes e constituem filtro RC com C10n. **Não garantem proteção a sobretensão**.
2. Capacitores 10nF C0G/NP0 0805, 50 V, ao GND: baixa deriva, mas a capacitância e impedância de origem devem ser validadas para a precisão pretendida.
3. Cabeçalhos 2,54 mm são apenas para **protótipo SELV**. Substituir por conectores polarizados/travados no produto final e fazer novo DRC.
4. Rastros F.Cu para sinal, B.Cu para retorno. O layout possui trilhas de GND conectando os canais; não inclui plano de GND nem guarda analógica. Medir ruído e acoplamento antes de declarar desempenho.
5. A interface não produz deslocamento a 1,65 V. Esse **offset deve ser fornecido e estabilizado pelo AFE externo**.

## Verificação obrigatória no KiCad antes de fabricar
- [ ] Abrir ambos arquivos no KiCad 8/9 e salvar novamente com a versão instalada.
- [ ] Executar ERC e DRC com a biblioteca de footprints instalada; resolver 100% dos **erros**, e analisar todos os avisos.
- [ ] Confirmar que o símbolo `PRISMA:Conn02` embutido e os 12 footprints de cabeçalho preservam a numeração 1=sinal, 2=GND.
- [ ] Conferir footprints R/C 0805 e disponibilidade exata das peças e padstacks.
- [ ] Conferir em inspeção visual e com DRC todos os cruzamentos de trilha, pads, furos e afastamentos.
- [ ] Conferir a geometria dos quatro furos M3 e a distância mínima das trilhas e das bordas.
- [ ] Confirmar continuidade elétrica ponta a ponta **após montagem, sem DEMOEM conectada**.
- [ ] Gerar Gerbers/BOM/arquivos de furação apenas depois dessas etapas.

## Ensaio sem rede
1. Identificar o lado do MCU em J38 e orientação de J29/J1 na placa real, com multímetro e esquema rev. C, **sem energizar**.
2. Testar esta interface isoladamente com fonte/gerador **SELV** de 0,3 a 3,0 V; verificar os seis canais em DC e senoidal e ausência de curtos/contato cruzado.
3. Conectar à DEMOEM somente após medir cada saída com multímetro/osciloscópio e comprovar níveis permitidos em VDD e em desligamento.
4. Conferir assinatura de cada canal na aquisição `0x3F`, `adc_timeout_mask`, sequência, CRC e offsets.
5. Medir ganho e defasagem entre canais e o efeito do RC; projetar posteriormente **filtro anti-alias de ordem apropriada** com base na banda/harmônicas pretendidas.
6. Repetir com os modelos de TVs/TCs escolhidos **após** projeto formal de isolamento e proteção do AFE externo.

## O que continua pendente (não fingir concluído)
- Fotografia/revisão física da DEMOEM; confirmação de cada pino de J38 por continuidade.
- Modelo/faixa/datasheet dos três TVs e dos três TCs, burden e isolação; fonte de alimentação e proteção.
- **AFE metrológico completo** com polarização/buffer/anti-alias e clamps dimensionados por datasheet, com ERC/DRC.
- Ensaios físicos de seis canais, calibração ganho/fase, precisão e atualização dos respectivos registros do PRISMA.
- Validar no hardware o ESP32-S3, a tela física, bateria/power-path, IoT, firmware/bootloader e documentação de segurança.

## Fontes
- [NXP DEMOEM User Manual](https://www.nxp.com/docs/en/user-guide/DEMOEMUM.pdf)
- [NXP DEMOEMSC rev. C](https://www.nxp.com/downloads/en/schematics/DEMOEMSC.pdf)
- [NXP MCF51EM256](https://www.nxp.com/products/MCF51EM)
- [Revisão de aquisição PRISMA](../../docs/revisao-aquisicao-seis-canais.md)
