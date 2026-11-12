# PRISMA

**Plataforma de Registro, Instrumentação, Sinais, Medição e Análise**

*Programar. Medir. Analisar.*

O PRISMA é um software desktop para Windows voltado ao desenvolvimento de sistemas embarcados e à instrumentação virtual. O primeiro hardware-alvo é o **kit DEMOEM / MCF51EM256 (ColdFire V1)**.

> **Protótipo v0.1.0.** A interface possui osciloscópio, diagrama fasorial, harmônicas e valores RMS usando dados **sintéticos**, claramente identificados. A porta COM recebe telemetria JSON somente quando existe firmware compatível. **Compilação ColdFire, gravação BDM e depuração ainda não estão implementadas.**

## Recursos

- Interface desktop escura em português, com editor de código C;
- Gráficos trifásicos, fasores e espectro harmônico;
- Espectro limitado às ordens abaixo de Nyquist, conforme a taxa de amostragem;
- Modo demonstração com dados sintéticos de 60 Hz;
- Monitoramento serial (115200 baud, protocolo JSON por linha);
- Testes automatizados para processamento e protocolo;
- Estrutura modular para ampliar o suporte a outros dispositivos.

## Instalação (Windows 11)

Instale Python 3.11 ou superior e, no PowerShell dentro do projeto, execute:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m prisma
```

O programa inicia no **modo demonstração**, sem necessidade da DEMOEM.

A demonstração gera 2400 amostras/s e inclui uma terceira harmônica de 2,5%
na fase A. Na aquisição serial, a maior distância temporal entre amostras limita
as ordens exibidas. A THD informa o intervalo de harmônicas analisado; quando
nem a segunda harmônica pode ser medida, aparece como indisponível.

## Comunicação real

Confira se o Windows disponibiliza uma porta COM. O dispositivo "BDM Serial Interface" não comprova, sozinho, a existência de uma COM funcional. Para visualizar dados reais, a placa precisará de firmware que transmita amostras no formato descrito em [docs/protocolo.md](docs/protocolo.md).

**Segurança:** não conecte tensão de rede diretamente aos pinos do microcontrolador. Aquisição de grandezas elétricas exige condicionamento e isolamento apropriados.

## Estrutura

- `src/prisma/ui` — interface gráfica;
- `src/prisma/core` — cálculos, protocolo e comunicação;
- `firmware` — integração com MCF51EM256 (planejada);
- `docs` — arquitetura, protocolo e roadmap;
- `scripts` — diagnóstico de drivers no Windows;
- `tests` — testes automatizados.

## Estado do desenvolvimento

| Entrega | Estado |
|---|---|
| Interface gráfica e instrumentos em modo demonstrativo | Implementado |
| Leitura serial JSON | Implementado em software, não testado na DEMOEM |
| Drivers USB / BDM Windows 11 | A validar |
| Firmware real para DEMOEM | Pendente |
| Compilação e gravação BDM | Pendente |
| Depuração e registradores | Pendente |

## Executar testes

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Licença

Nenhuma licença de uso ou redistribuição foi definida.
