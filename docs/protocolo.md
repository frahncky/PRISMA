# Protocolo de telemetria PRISMA v1

A comunicação serial usa uma mensagem JSON UTF-8 por linha, padrão 115200 baud, 8N1.

Exemplo de mensagem:
{"type":"sample","t":0.001,"va":110.2,"vb":-92.1,"vc":-18.3}

Campos:
- type: string fixa "sample".
- t: instante de aquisição em segundos, estritamente crescente.
- va, vb, vc: valores instantâneos das três fases, em volts.

O firmware é responsável por converter ADC para unidade física. Este protocolo NÃO presume pinagem, referência ADC nem isolamento elétrico. Canais ausentes podem ser transmitidos como zero, sem implicar existência de medição trifásica real.

JSON facilita prototipação, mas pode sobrecarregar o ColdFire em taxas maiores. Prever posteriormente protocolo binário com checksum/CRC, timestamp de hardware, detecção de perdas e mecanismos de controle seguros.

O cálculo atual assume fundamental fixa em 60 Hz. Análises precisas exigem calibração, frequência aferida e amostragem suficientemente rápida, estável e sincronizada.
