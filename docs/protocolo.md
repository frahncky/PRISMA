# Protocolo de telemetria PRISMA v1

A comunicação serial usa uma mensagem JSON UTF-8 por linha, padrão genérico 115200 baud, 8N1. O perfil `examples/profiles/demoem-ch340.json`, validado na DEMOEM, usa 115200 baud, 8N1 (firmware em rajada; até 14/11/2026 era 19200).

Exemplo de mensagem:
{"type":"sample","t":0.001,"va":110.2,"vb":-92.1,"vc":-18.3}

Campos:
- type: string fixa "sample".
- t: instante de aquisição em segundos, estritamente crescente.
- va, vb, vc: valores instantâneos das três fases, em volts.

O firmware é responsável por converter ADC para unidade física. Este protocolo NÃO presume pinagem, referência ADC nem isolamento elétrico. Canais ausentes podem ser transmitidos como zero, sem implicar existência de medição trifásica real.

JSON facilita prototipação, mas pode sobrecarregar o ColdFire em taxas maiores. Prever posteriormente protocolo binário com checksum/CRC, timestamp de hardware, detecção de perdas e mecanismos de controle seguros.

Análises precisas exigem calibração, frequência aferida e amostragem suficientemente rápida, estável e sincronizada.

## Extensões compatíveis: correntes e estados

Uma amostra pode incluir `ia`, `ib`, `ic`, em ampères, sincronizadas com as tensões. Os três campos devem estar presentes juntos, como números finitos. Ausência não significa corrente zero e mantém as potências indisponíveis.

```json
{"type":"sample","t":0.001,"va":110.2,"vb":-92.1,"vc":-18.3,"ia":4.1,"ib":-3.2,"ic":-0.9}
```

Os estados físicos são mensagens separadas e opcionais:

```json
{"type":"status","leds":{"run":true},"gpio":{"input":false},"adc":{"adc0_raw":2048},"lcd":["PRISMA","Aquisicao ativa"]}
```

`leds` e `gpio` contêm valores booleanos, `adc` contém números finitos nas unidades identificadas pelo firmware, e `lcd` contém até quatro linhas de 80 caracteres. Cada grupo digital/ADC aceita até 64 nomes de 40 caracteres. A tela apresenta esses dados como informados pelo firmware; não infere estados físicos a partir das tensões.

O diagnóstico ColdFire validado transmite `ad4_raw`, `ad5_raw` e `ad6_raw` dentro de `adc`, lidos respectivamente por ADC3, ADC1 e ADC2. São contagens brutas de 16 bits das três saídas TPM1 do gerador QE8 conectado pelo J38. Elas não são volts nem amperes e não devem ser tratadas como mensagens `sample` antes da calibração. `adc_timeout_mask` igual a zero confirma que os três módulos terminaram a conversão; bits 0, 1 e 2 identificam timeout nos ADC1, ADC2 e ADC3.

O leitor aceita linhas fragmentadas entre leituras e limita cada linha a 16384 bytes, descartando mensagens maiores até a próxima quebra de linha. São exibidos no máximo cinco avisos de linhas inválidas por conexão. Uma linha incompleta é descartada ao encerrar a conexão.

## Taxa de amostragem e transporte

A análise aceita referência de 50 Hz, 60 Hz ou estimação automática entre 40 e 70 Hz, selecionada na aba Análise. As harmônicas ficam estritamente abaixo de Nyquist; THD e potências seguem os métodos em [instrumentação](instrumentacao.md).

Dimensionar a capacidade da serial antes de definir a taxa do ADC: em 8N1, a vazão útil máxima aproximada é `baudrate / 10` bytes/s, sem folga. O JSON trifásico, principalmente com correntes, pode exceder 115200 baud em taxas baixas. Para aquisição de alta ordem harmônica, prever transporte mais eficiente e validar perdas/sincronismo; o gerador demo não atravessa a serial. Ver [orçamento da bancada](bancada-demoem.md).


## Rajada de taxa fixa (DEMOEM)

O firmware em rajada envia uma linha por bloco:

```json
{"type":"burst","source":"DEMOEM","seq":5,"fs_mhz":1995487,"n":500,"ch":["ad4","ad5","ad6"],"adc_timeout_mask":0,"data":"0000FA10..."}
```

- `fs_mhz`: taxa de amostragem em milihertz (inteiro). `n`: amostras por canal (2..4096).
- `data`: `n × 3` palavras de 16 bits em hexadecimal maiúsculo, 4 dígitos cada, intercaladas por amostra (`ch[0] ch[1] ch[2]`, próxima amostra...).
- Os três ADCs convertem juntos a cada tique do timer; os valores são contagens brutas, mapeadas para `va`, `vb` e `vc`.
- O PRISMA posiciona cada bloco em `t = seq × 10 s + i / fs`, de modo que a análise use um bloco por vez. Um `seq` menor que o anterior (reinício do firmware) limpa o buffer.

## Protocolo binário v2 (rajada com CRC)

Convive com o JSON na mesma serial: o leitor separa linhas de texto e quadros que começam com `A5 5A` (o firmware deve emitir JSON só em ASCII: texto UTF-8 como `¥Z` contém `A5 5A` e seria confundido com um quadro). Encoder C em `firmware/include/prisma_frame.h` e `firmware/src/prisma_frame.c`; decodificador em `prisma.core.protocol.StreamDecoder`.

| Campo | Tipo | Observação |
| --- | --- | --- |
| sincronismo | `A5 5A` | |
| tipo | u8 | `0x01` = rajada · `0x02` = resumo da medição contínua |
| len | u16 LE | bytes do payload |
| payload | len bytes | |
| CRC | u16 LE | CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) sobre tipo, len e payload |

Payload da rajada: `seq` u32, `fs_mhz` u32, `n` u16 (2..4096), máscara u8 (`0x07` = va/vb/vc; `0x3F` = va..ic), flags u8 (bits 0–2: timeout ADC1..3; bit 7: valores int16 com sinal), depois `n × k` palavras u16 LE intercaladas por amostra.

Um quadro com CRC inválido é descartado inteiro (pelo comprimento declarado) e contado. Cabeçalho inválido descarta até a próxima linha ou sincronismo.

**Vazão a 115200 8N1 (≈ 11 520 B/s úteis):** cada amostra trifásica ocupa 6 bytes contra 12 do JSON hex. Isso dá ≈ 1 900 amostras/s com 3 canais ou ≈ 950 amostras/s com 6 canais, contínuos e sem folga. Para h15 a 60 Hz (Nyquist acima de 900 Hz, ou seja, mais de 1 800 amostras/s) com 6 canais, é preciso continuar em rajadas com pausa ou subir o baud (por exemplo, 460800).

### Resumo da medição contínua (tipo 0x02)

Com `PRISMA_CONTINUOUS` (padrão), a DEMOEM amostra sem parar na interrupção do MTIM1 (~1995,5 Hz) e acumula somas inteiras por janela (`firmware/include/prisma_meter.h`). Cada janela fecha no primeiro cruzamento ascendente da fase A pela sua média depois de ~1 s, então cobre ciclos inteiros, e as janelas são contíguas. Sem cruzamento (sinal DC ou ausente) a janela fecha em 1,25 s com a flag `0x08`.

| Campo | Tipo | Observação |
| --- | --- | --- |
| seq | u32 | número da janela; um salto indica janela perdida |
| fs_mhz | u32 | taxa de amostragem em mHz |
| n | u32 | amostras da janela |
| máscara | u8 | `0x07` (va, vb, vc) ou `0x3F` (va..ic) |
| flags | u8 | bits 0–2: timeout ADC1..3 · `0x08`: sem cruzamentos · `0x10`: a janela anterior não foi lida a tempo |
| ciclos | u16 | ciclos inteiros de A na janela |
| period_q8 | u32 | do 1º cruzamento interno ao de fechamento, em 1/256 de amostra |
| por canal | u32 + u64 | Σx e Σx² das contagens |
| Σv·i | 3 × u64 | só com 6 canais: va·ia, vb·ib, vc·ic |

O PC calcula com inteiros exatos: `RMS² = (n·Σx² − (Σx)²) / n²`, `P = (n·Σvi − Σv·Σi) / n²` (vezes os ganhos da calibração) e `f = (ciclos − 1) · fs / (period_q8 / 256)`. O período usa dois cruzamentos medidos com o mesmo limiar (a média de A só muda quando a janela fecha). No simulador do PC (`tests/test_meter_firmware.py`), o erro ficou abaixo de 0,0001 Hz e de ±0,03 % no RMS. Esse limite vem da borda da janela, que fica a até ½ amostra do cruzamento exato.

A energia, a demanda e as tendências passam a vir desses resumos: o tempo é a soma das durações das janelas, sem lacunas e pelo relógio da placa. As rajadas (uma por resumo) continuam alimentando osciloscópio, fasores e harmônicas. As somas não dão o sinal de Q: o módulo é `√(S² − P²)` e o sinal vem da última análise de forma de onda. A compensação de atraso (`delay_us`) ainda não se aplica aos resumos.

### Calibração de fase

Cada canal do perfil de calibração aceita `delay_us` opcional, além de `gain` e `offset`. Um valor positivo indica que o canal chega atrasado (TC, filtro ou conversão sequencial). O app compensa por interpolação antes da análise. `delays_from_resistive_load` calcula o atraso das correntes a partir de uma carga resistiva (FP = 1).

```json
{"version": 1, "name": "Bancada", "channels": {"ia": {"gain": 0.0123, "offset": 0.0, "delay_us": 180.0}}}
```
