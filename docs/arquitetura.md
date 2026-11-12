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

## Entregas de software v0.2

- `core/history.py`: sessões SQLite e exportação incremental com filtro temporal.
- `core/calibration.py`: transformação de entrada por canal, antes do buffer e do registro.
- `core/measurement.py`: estimação de frequência, ajuste harmônico ponderado, RMS e potência AC.
- `core/devices.py`: perfis declarativos de protocolo/baud e inventário de portas.
- `core/reports.py`: relatório HTML autossuficiente com condições e origem da análise.
- `core/toolchain.py`: projetos, `QProcess` assíncrono, digest e cliente GDB/MI.
- `ui/features.py`: controles de análise, histórico, estados de hardware e desenvolvimento.
- `firmware/`: encoder C, contrato HAL, aplicação e port simulador de computador.

Os perfis selecionam PRISMA JSON v1 ou plugins instalados no grupo `prisma.protocols`. A distribuição inclui um plugin CSV trifásico; novos adaptadores são carregados apenas ao selecionar o perfil. Drivers para outros enquadramentos e protocolos proprietários exigem implementação específica. A gravação delega ao executável explicitamente configurado; o aplicativo não implementa o protocolo proprietário BDM nem distribui ferramentas do fabricante. O cliente GDB/MI exige servidor compatível e ainda precisa de validação com o ColdFire da bancada.

CSV e SQLite recebem amostras aceitas já calibradas. Troca de fonte/calibração encerra o registro e limpa a janela. SQLite confirma as transações a cada atualização da interface e no encerramento; uma queda abrupta pode perder a última transação. A gravação e o ajuste ainda rodam na thread de interface: taxas elevadas precisam de medição de desempenho e eventual extração para workers antes de homologação.
