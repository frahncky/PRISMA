# Histórico de versões

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

A implementação física ColdFire/PEmicro permanece pendente: a placa não estava disponível durante esta entrega. Nenhum firmware foi gravado nem periférico físico foi homologado.

## 0.1.0

- Protótipo desktop, editor C, instrumentos em demonstração e leitura serial JSON.
- Limites de Nyquist, testes de cálculos e interface, registro CSV e apresentação do projeto.
