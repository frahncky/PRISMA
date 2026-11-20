<div align="center">

<img src="docs/images/banner.svg" alt="PRISMA" width="100%">

### Plataforma de Registro, Instrumentação, Sinais, Medição e Análise

Analisador de energia trifásico em português: tensões, correntes, potências, FP, energia, demanda,<br>
formas de onda, fasores e harmônicas, ligado por serial à placa **DEMOEM / ColdFire MCF51EM256**.

[![Testes PRISMA](https://github.com/frahncky/PRISMA/actions/workflows/ci.yml/badge.svg)](https://github.com/frahncky/PRISMA/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![PySide6](https://img.shields.io/badge/UI-PySide6-41CD52?logo=qt&logoColor=white)](https://doc.qt.io/qtforpython-6/)
![Versão](https://img.shields.io/badge/vers%C3%A3o-0.2.0-6f42c1)
![Plataforma](https://img.shields.io/badge/Windows-11-0078D4?logo=windows&logoColor=white)
![Hardware](https://img.shields.io/badge/ColdFire-MCF51EM256-e35d6a)

**[Começar](#-começar-em-1-minuto)** ·
**[Recursos](#-recursos)** ·
**[Hardware](#-hardware-e-bancada)** ·
**[Estado](#-estado-do-projeto)** ·
**[Documentação](#-documentação)**

<br>

<img src="docs/images/prisma-demo.png" alt="Interface do PRISMA em modo demonstração: quadro de medições por fase e trifásico, frequência, THD, energia, desequilíbrio, osciloscópio, fasores e harmônicas" width="92%">

<sub>Captura real do aplicativo em modo demonstração · sinais sintéticos</sub>

</div>

<br>

> [!NOTE]
> **Protótipo v0.2.0.** Abre em modo demonstração e funciona sem placa. A DEMOEM já foi gravada e lida em bancada (CodeWarrior + PEmicro, telemetria via CH340). As leituras de ADC ainda são contagens brutas: a calibração metrológica está pendente.

## ⚡ Começar em 1 minuto

```powershell
git clone https://github.com/frahncky/PRISMA.git
cd PRISMA
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m prisma
```

Requer **Windows 11** e **Python 3.11+**. O app abre direto em demonstração: 2400 amostras/s, três fases de 127 V RMS a 60 Hz e 2,5 % de 3ª harmônica na fase A.

Com a placa:

```powershell
.\.venv\Scripts\python.exe -m prisma --port COM4 --profile examples\profiles\demoem-ch340.json --connect
.\.venv\Scripts\python.exe -m prisma --last          # reusa a última porta, perfil e monitor
.\.venv\Scripts\python.exe -m prisma --ligacao mono   # experimento monofásico (bi, tri); também no seletor do topo
.\.venv\Scripts\python.exe -m prisma --painel --screen 2   # painel touch em tela cheia no 2º monitor (ou F10)
.\scripts\criar_atalho.ps1                             # atalho "PRISMA" na área de trabalho
```

Pela rede (Wi-Fi), sem cabo entre a placa e a tela: o app conecta no gateway ESP32-S3 (`prisma.local`) ou na ponte do PC, que serve a serial da DEMOEM em TCP. Na lista de portas, escolha **Gateway na rede…**, ou passe o endereço:

```powershell
uv run python scripts\ponte_tcp.py COM3                 # neste PC: DEMOEM do CH340 na porta TCP 3333
uv run python scripts\ponte_tcp.py --demo               # sem placa: demonstração de 6 canais pela rede
.\.venv\Scripts\python.exe -m prisma --port 192.168.0.20:3333 --connect --painel   # em outro PC ou na tela
```

Numa tela dedicada (medidor), use o modo quiosque, que abre só o painel, conecta sozinho, reconecta e avisa quando os dados param: `python -m prisma --quiosque --port prisma.local` ([guia do quiosque](docs/quiosque.md), com partida automática no Windows e no Raspberry Pi).

O app reconecta sozinho se o Wi-Fi cair. Pela rede só passam os comandos de identificar, de rajada e de autocalibração; a atualização de firmware continua local ([protocolo](docs/protocolo.md#pela-rede-tcp)).

## ✨ Recursos

<table>
  <tr>
    <td width="33%" valign="top">
      <h3>📈 Medições</h3>
      Quadro de multimedidor por fase e trifásico (V, tensão de linha, I, P, Q, S, FP Indut./Capac.), osciloscópio Va/Vb/Vc, fasores com a fase A em 0°, harmônicas até h15 com THD, desequilíbrio e sequência de fases.
    </td>
    <td width="33%" valign="top">
      <h3>🔋 Energia e demanda</h3>
      Energia ativa importada/exportada e reativa, demanda de 15 min e máxima com horário, mínimos e máximos por fase. Calibração ganho/offset por canal.
    </td>
    <td width="33%" valign="top">
      <h3>📡 Aquisição serial</h3>
      JSON por linha via COM, perfis por placa, plugins de protocolo (JSON/CSV) e diagnóstico USB/serial do Windows.
    </td>
  </tr>
  <tr>
    <td valign="top">
      <h3>💾 Histórico</h3>
      Registro CSV contínuo e sessões SQLite com filtro temporal e exportação, sempre com origem e coeficientes de calibração.
    </td>
    <td valign="top">
      <h3>🔧 Build e gravação</h3>
      Projetos JSON com toolchain configurável, log, mapa de memória, hash do artefato e confirmação antes de gravar. Build CodeWarrior por linha de comando.
    </td>
    <td valign="top">
      <h3>📝 Editor e relatórios</h3>
      Editor de firmware C (<code>.c</code>/<code>.h</code>) e relatório HTML autossuficiente da análise, pronto para imprimir em PDF.
    </td>
  </tr>
</table>

<p align="center">
  <img src="docs/images/prisma-painel.png" alt="Painel touch em tela cheia: visão geral com valores por fase, indicadores, formas de onda, fasores e harmônicas" width="92%"><br>
  <sub><b>Painel touch</b> (<code>--painel</code> ou F10): Visão geral, Valores, Formas de onda, Fasores e harmônicas, Energia e demanda e Tendências, com alvos grandes para toque</sub>
</p>

<p align="center">
  <img src="docs/images/painel-1280x800-visao-geral.png" alt="Painel touch em 1280×800: quadro de valores por fase, indicadores, tensões, fasores e harmônicas numa tela só" width="70%"><br>
  <sub><b>Tela de referência: 10,1" com 1280×800, IPS e toque capacitivo.</b> O painel cabe inteiro, sem rolagem (o layout pede no mínimo 1181×674). <a href="docs/images/painel-1280x800-todas.png">Ver as seis abas nesse tamanho</a></sub>
</p>

<table>
  <tr>
    <td align="center" width="50%"><img src="docs/images/prisma-analise.png" alt="Configuração de análise e tabela de potências por fase"><br><sub>Análise, calibração e potências AC</sub></td>
    <td align="center" width="50%"><img src="docs/images/prisma-build.png" alt="Compilação com hash do artefato e mapa de memória"><br><sub>Build com hash e mapa de memória</sub></td>
  </tr>
</table>

## 🧩 Como tudo se conecta

```mermaid
flowchart LR
    S["Sensores isolados<br/>tensão e corrente"] --> A["Condicionamento<br/>e filtros"]
    A --> B["DEMOEM<br/>ColdFire MCF51EM256"]
    B -->|"SCI3 · rajadas JSON · 115200 8N1"| P["🖥️ PRISMA desktop"]
    B -.->|"UART"| G["Gateway ESP32-S3<br/>(protótipo)"]
    G -.->|"USB CDC"| P
    G -.->|"Wi-Fi · MQTT/TLS"| I["☁️ IoT"]
    G -.-> H["📱 Painel touch web"]
```

<sub>Linhas contínuas: caminho validado em bancada. Tracejadas: código publicado, ainda sem teste físico.</sub>

## 🔌 Hardware e bancada

| Bancada validada | Configuração |
| --- | --- |
| **Placa** | DEMOEM com MCF51EM256 (ColdFire V1) |
| **Gravação** | CodeWarrior 6.3.2 + PEmicro Embedded Multilink (HI-WAVE) |
| **Telemetria** | `J6 PTC1/TX3 → CH340 RXD` + GND, J7/J8 sem jumper, perfil [`demoem-ch340.json`](examples/profiles/demoem-ch340.json) |
| **Formato** | Rajadas de 500 amostras × 3 canais a ~1995 Hz, uma linha JSON por bloco, 115200 8N1 (~1,2 blocos/s) |

```json
{"type":"sample","t":0.001,"va":110.2,"vb":-92.1,"vc":-18.3}
```

> [!WARNING]
> Nunca ligue tensão de rede direto ao ADC ou aos pinos do microcontrolador. Medições reais exigem transdutores **isolados** e condicionamento. Os valores exibidos são estimativas, sem calibração certificada.

Guias: [ligações da placa](docs/ligacoes-hardware-demoem.md) · [modo quiosque](docs/quiosque.md) · [roteiro de bancada](docs/bancada-demoem.md) · [protocolo](docs/protocolo.md) · [bootloader/OTA](docs/bootloader.md) · [firmware ColdFire](firmware/README.md) · [gateway ESP32-S3](gateway/esp32s3/README.md)

## 🗺️ Estado do projeto

| Entrega | Estado |
| --- | --- |
| Interface, instrumentos e editor em demonstração | ✅ Pronto |
| Análise: frequência, janelas, harmônicas, potência, calibração | ✅ Pronto em software |
| Histórico CSV / SQLite e relatórios | ✅ Pronto |
| Aquisição em rajada AD4/AD5/AD6 na DEMOEM (CH340, 115200 8N1) | ✅ Validada em bancada: trifásico a 120°, sem perda de blocos |
| Build e gravação ColdFire (CodeWarrior + HI-WAVE) | ✅ Automatizados: `scripts/gravar_demoem.ps1 -Build` |
| Firmware ColdFire: rajada com timer, trim do oscilador gravado | ✅ Validados · autocalibração do ADC desativada |
| Telemetria por um único USB (serial virtual PEmicro) | ⏳ Driver atual não cria porta COM |
| Depuração ColdFire pelo PRISMA (GDB) | ⏳ Sem GDB ColdFire V1 na instalação; depuração via HI-WAVE |
| Medição calibrada e homologação física | ⏳ Pendente |
| Gateway ESP32-S3: ponte USB, resumos v2, MQTT e atualização da DEMOEM por Wi-Fi | 🧪 Compila no PlatformIO; núcleo testado no PC; não gravado num ESP |
| Tela touch física e bateria | 🧪 Projeto documentado, sem teste físico |

Detalhes por fase no [roadmap](docs/roadmap.md) e no [histórico de versões](CHANGELOG.md).

<details>
<summary><b>💾 Registrar amostras em CSV e SQLite</b></summary>

<br>

Com o modo demo ativo ou a serial recebendo amostras, use **Aquisição → Iniciar registro CSV…**. O arquivo traz `t_s`, `va_V`, `vb_V`, `vc_V`, `ia_A`, `ib_A`, `ic_A` e `origem` (UTF-8, vírgula como separador, ponto decimal). O registro continua além da janela dos gráficos sem manter tudo em memória e é encerrado ao trocar de fonte, desconectar ou fechar o app.

Em **Dados e dispositivos → Iniciar histórico SQLite…**, as sessões ficam no mesmo banco; **Consultar histórico SQLite…** exporta uma sessão inteira ou filtrada por tempo para CSV.

</details>

<details>
<summary><b>📐 Análise e relatórios</b></summary>

<br>

Na aba **Análise**, escolha 50 Hz, 60 Hz ou automático (40–70 Hz), janela retangular/Hann e a referência dos fasores. Clique na ponta de um fasor para inspecioná-lo. As harmônicas exibidas ficam sempre abaixo de Nyquist, conforme o maior intervalo entre amostras.

Na demonstração, as correntes são de 5 A RMS com FP 0,9. Na serial, as potências exigem `ia`, `ib` e `ic` sincronizadas. Métodos e limites em [instrumentação](docs/instrumentacao.md).

</details>

<details>
<summary><b>🔧 Compilação, gravação e depuração</b></summary>

<br>

Abra um projeto JSON na aba **Build / depuração**. Exemplos:

- [`host-gcc.json`](examples/projects/host-gcc.json): compila o simulador C no computador.
- [`demoem-codewarrior.json`](examples/projects/demoem-codewarrior.json): compila o firmware da DEMOEM via `CmdIDE` sem abrir a IDE.

A gravação exige comando configurado e confirmação explícita. Na bancada, gravação e depuração da DEMOEM são feitas pelo HI-WAVE. Veja o [guia de toolchain](docs/toolchain.md).

</details>

<details>
<summary><b>🧱 Arquitetura e estrutura do repositório</b></summary>

<br>

A interface roda na thread principal do Qt e a leitura serial em uma `QThread` própria. O núcleo separa protocolo, buffer de amostras e cálculos.

| Camada | Tecnologia |
| --- | --- |
| Aplicativo | Python 3.11+, PySide6 |
| Gráficos | pyqtgraph |
| Processamento | NumPy |
| Comunicação | pyserial, JSON por linha |
| Qualidade | pytest, GitHub Actions |

```text
src/prisma/        app: ui/ (janela, instrumentos, editor) e core/ (protocolo, cálculos, serial)
firmware/          encoder C, simulador host e projeto CodeWarrior da DEMOEM
gateway/esp32s3/   gateway PlatformIO: ponte USB, painel web, MQTT e atualização da DEMOEM
examples/          telemetria, calibração, perfis e projetos de toolchain
docs/              guias, protocolo, roadmap e imagens
scripts/           diagnóstico de drivers no Windows
tests/             protocolo, cálculos, firmware host e interface Qt
```

Mais em [arquitetura](docs/arquitetura.md).

</details>

<details>
<summary><b>🛠️ Desenvolvimento e testes</b></summary>

<br>

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Os testes cobrem protocolo, serial fragmentada, cálculos trifásicos, frequência, potência, calibração, Nyquist, SQLite, relatórios, interface Qt sem tela, firmware host compilado com GCC e o cliente GDB/MI com processos de teste. O [GitHub Actions](https://github.com/frahncky/PRISMA/actions/workflows/ci.yml) roda a suíte a cada push e pull request.

</details>

## 📚 Documentação

| | Guia | Conteúdo |
| :-: | --- | --- |
| 🏛️ | [Arquitetura](docs/arquitetura.md) | Camadas do app e integração com o MCF51EM256 |
| 📨 | [Protocolo serial](docs/protocolo.md) | Mensagens, unidades e limites da telemetria |
| ⬆️ | [Bootloader/OTA](docs/bootloader.md) | Atualização do firmware pela serial, mapa de memória e segurança |
| 📐 | [Instrumentação](docs/instrumentacao.md) | Frequência, harmônicas, potências, calibração |
| 🔧 | [Toolchain](docs/toolchain.md) | Projetos, compilação, gravação e depuração |
| 🧩 | [Perfis e plugins](docs/plugins.md) | Adaptadores JSON/CSV e API de protocolos |
| 🧪 | [Bancada DEMOEM](docs/bancada-demoem.md) | Jumpers, testes e critérios de aceitação |
| 🔌 | [Ligações da placa](docs/ligacoes-hardware-demoem.md) | Alimentação, sensores, UART, touch, bateria e IoT |
| 📡 | [Gateway ESP32-S3](gateway/esp32s3/README.md) | PlatformIO, ponte USB, painel touch, MQTT/TLS e OTA da DEMOEM |
| 💾 | [Firmware](firmware/README.md) | Encoder C, simulador host e projeto CodeWarrior |
| 🗺️ | [Roadmap](docs/roadmap.md) | Fases e pendências físicas |

## 🔒 Licença

Nenhuma licença de uso ou redistribuição foi concedida. O projeto é proprietário.

<div align="center">

<br>

<img src="https://img.shields.io/badge/◈-PRISMA-0b1020?style=for-the-badge" alt="PRISMA">

<sub>Programar · Medir · Analisar</sub>

</div>
