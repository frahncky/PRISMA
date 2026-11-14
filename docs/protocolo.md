# Protocolo de telemetria PRISMA v1

A comunicação serial usa uma mensagem JSON UTF-8 por linha, padrão genérico 115200 baud, 8N1. O perfil `examples/profiles/demoem-ch340.json`, validado na DEMOEM, usa 19200 baud, 8N1.

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

O diagnóstico ColdFire atual transmite `dadp0_raw`, `dadp1_raw` e `dadp2_raw` dentro de `adc`. São palavras brutas de 16 bits dos pares diferenciais DADP0/DADM0, DADP1/DADM1 e DADP2/DADM2. Como o JSON preserva o registrador sem sinal, valores de 32768 a 65535 representam valores negativos em complemento de dois. Elas não são volts nem amperes e não devem ser tratadas como mensagens `sample` antes da calibração. `adc_timeout_mask` igual a zero confirma que os três módulos terminaram a conversão; bits 0, 1 e 2 identificam timeout nos ADC1, ADC2 e ADC3.

O leitor aceita linhas fragmentadas entre leituras e limita cada linha a 16384 bytes, descartando mensagens maiores até a próxima quebra de linha. São exibidos no máximo cinco avisos de linhas inválidas por conexão. Uma linha incompleta é descartada ao encerrar a conexão.

## Taxa de amostragem e transporte

A análise aceita referência de 50 Hz, 60 Hz ou estimação automática entre 40 e 70 Hz, selecionada na aba Análise. As harmônicas ficam estritamente abaixo de Nyquist; THD e potências seguem os métodos em [instrumentação](instrumentacao.md).

Dimensionar a capacidade da serial antes de definir a taxa do ADC: em 8N1, a vazão útil máxima aproximada é `baudrate / 10` bytes/s, sem folga. O JSON trifásico, principalmente com correntes, pode exceder 115200 baud em taxas baixas. Para aquisição de alta ordem harmônica, prever transporte mais eficiente e validar perdas/sincronismo; o gerador demo não atravessa a serial. Ver [orçamento da bancada](bancada-demoem.md).
