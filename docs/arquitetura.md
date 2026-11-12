# Arquitetura do PRISMA

O PRISMA separa quatro camadas:

1. Interface Windows em PySide6: editor C, osciloscópio, fasores e harmônicas.
2. Processamento NumPy: RMS, extração fasorial e harmônicos.
3. Aquisição: geração de sinais sintéticos (DEMO) ou porta serial COM com JSON.
4. Adaptação futura de dispositivos: DEMOEM/BDM, ESP32, STM32 e outros.

Qt roda na thread principal; aquisição serial em QThread. Para altas taxas, implementar processamento em worker e decimação.

## Suporte ao MCF51EM256

- Verificar driver PEmicro Embedded Multilink no Windows 11.
- Separar canal BDM e canal serial virtual.
- Confirmar porta COM, jumpers SCI1/SCI3 e configuração do firmware.
- Integrar compilador ColdFire V1 e gravador BDM sem infringir licenças.
- Criar firmware que transmita telemetria no protocolo PRISMA v1.

O protocolo JSON do PRISMA não é um protocolo nativo do MCF51EM256. Não se pode ler automaticamente todas as variáveis da placa sem firmware ou mecanismo de depuração compatível.

**Limite de segurança:** os gráficos são apenas estimativas até que exista um sistema de aquisição calibrado, sincronizado e eletricamente isolado.
