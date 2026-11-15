# Modo quiosque: o PRISMA numa tela dedicada

O modo quiosque transforma uma tela touch (referência: 10,1" 1280×800) no mostrador do medidor. A tela pode ser de um PC com Windows, de um Raspberry Pi ou de outro Linux.

```text
python -m prisma --quiosque --port prisma.local        # gateway ESP32-S3 pela rede
python -m prisma --quiosque --port COM3                # DEMOEM direto na USB
python -m prisma --quiosque --port 192.168.0.20:3333   # ponte do PC (scripts/ponte_tcp.py)
python -m prisma --quiosque --port COM3 --ligacao mono  # experimento monofásico (bi, tri); fica salvo
```

## O que muda em relação ao app normal

| | App normal | Quiosque |
| --- | --- | --- |
| Janela | Janela principal (código, gráficos, ferramentas) | Só o painel touch em tela cheia; `--screen N` escolhe o monitor |
| Sem placa | Demonstração com sinais sintéticos | Nada de dados sintéticos: o painel mostra "Sem conexão com a placa" |
| Conexão | Botão Conectar | Conecta sozinho na partida, com `--port` ou a última porta usada |
| Queda | Rede: reconecta. Serial: para | Reconecta sempre, inclusive na serial: cabo USB que sai e volta, ou porta COM que aparece depois do boot |
| Dados parados | — | Faixa amarela: "Sem dados novos da placa há 12 s: valores congelados". Aparece depois de 3 s sem dados; a placa manda um resumo por segundo |
| Tela | Apaga conforme o sistema | Windows: fica ligada enquanto o quiosque roda. Linux: ver abaixo |
| Cursor | Visível | Escondido (`--cursor` mantém) |
| Sair | Botão Sair ou Esc | **Segurar** "Sair" por 2 s (ou Esc no teclado). Abre a janela principal para manutenção, e F10 volta ao painel |

## Windows (PC ou mini-PC com tela touch)

1. Instale o PRISMA (README) e teste: `.\.venv\Scripts\python.exe -m prisma --quiosque --port prisma.local --screen 2`.
2. Crie o atalho de partida automática:

   ```powershell
   .\scripts\criar_atalho.ps1 -Argumentos "--quiosque --port prisma.local --screen 2" -Inicializacao
   ```

   O atalho vai para a pasta Inicializar do usuário. Para desfazer, apague `PRISMA.lnk` em `shell:startup`.
3. Ative o login automático do usuário (`netplwiz`) se a tela precisar voltar sozinha depois de faltar energia.

## Raspberry Pi (Raspberry Pi OS com área de trabalho) — não testado num Pi

1. Instale o projeto:

   ```bash
   sudo apt install python3-venv git
   git clone https://github.com/frahncky/PRISMA.git ~/PRISMA && cd ~/PRISMA
   python3 -m venv .venv && .venv/bin/pip install -e .
   .venv/bin/python -m prisma --quiosque --port prisma.local
   ```

   O PySide6 tem pacote para ARM 64 bits. Use o Raspberry Pi OS 64 bits (Bookworm ou mais novo, Python 3.11+).
2. Partida automática: copie `scripts/quiosque/prisma-quiosque.desktop` para `~/.config/autostart/` e ajuste o caminho e a porta. Se a sessão gráfica não ler `~/.config/autostart`, ponha a linha do `Exec=` em `~/.config/labwc/autostart` (Wayland/labwc) ou no autostart do LXDE.
3. Tela sempre ligada: `sudo raspi-config` → Display Options → Screen Blanking → No.
4. Rotação e toque: em Preferências → Screen Configuration. Para o PRISMA, a tela é só uma janela em tela cheia.

## Ligação recomendada

```text
DEMOEM ──UART──> ESP32-S3 (gateway) ──Wi-Fi──> tela (Windows ou Raspberry Pi) com --quiosque --port prisma.local
```

O ESP32-S3 fica junto da placa, e a tela pode ficar em outro lugar, só com alimentação. Sem o ESP, a ponte do PC faz o mesmo papel: `scripts/ponte_tcp.py COM3`.

## Limites

- Os valores seguem a calibração ativa do app na tela. Calibre uma vez na janela principal (manutenção); ela fica salva.
- Em Linux, o PRISMA não impede o apagamento da tela: isso é configuração do sistema (passo 3).
- A conexão de rede não tem senha nem criptografia (ver [protocolo](protocolo.md#pela-rede-tcp)): use só em LAN confiável.
