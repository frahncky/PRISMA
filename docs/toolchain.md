# Compilação, gravação e depuração

A aba **Build / depuração** executa comandos explicitamente configurados em um projeto JSON. Abrir o arquivo mostra os comandos e o alvo; a execução depende dos botões do usuário. O PRISMA não inclui CodeWarrior, drivers PEmicro, licenças ou um servidor BDM.

## Projeto executável de referência

Com GCC disponível no PATH, abra `examples/projects/host-gcc.json` e clique em **Compilar**. O projeto gera `prisma-host.exe` e `prisma-host.map` na raiz do repositório. Apesar da extensão `.exe`, o arquivo produzido é nativo do sistema usado para compilar. Execute-o no terminal para gerar telemetria sintética:

```powershell
.\prisma-host.exe > telemetria-host.jsonl
```

No Linux: `./prisma-host.exe > telemetria-host.jsonl`. O simulador emite 5000 amostras e cinco estados; não envia nada à placa. O GCC deve ser instalado separadamente; esse exemplo não usa o compilador ColdFire e não pode ser gravado na DEMOEM.

## Formato do projeto

- `version`: `1`.
- `name`, `target`: identificação do projeto e do alvo, exibida antes da gravação.
- `directory`: diretório de trabalho, relativo ao JSON.
- `build`: lista com executável e argumentos da compilação.
- `artifact`: arquivo de saída, relativo ao diretório de trabalho.
- `map_file`: mapa produzido pelo linker, opcional. A interface mostra até 2 MB de texto.
- `flash`: lista de argumentos do gravador. Vazia mantém a gravação desabilitada.
- `debugger`: executável GDB compatível com o alvo e seus argumentos. Vazia mantém a integração indisponível.
- `remote`: `host:porta` de um servidor GDB remoto já iniciado.

Cada elemento da lista é um argumento; não usar uma linha de shell, `&&`, redirecionamentos ou aspas adicionais para caminhos com espaços. Scripts de build existentes podem ser chamados pelo executável apropriado. Os comandos rodam com as permissões do usuário: carregar apenas projetos cujo conteúdo tenha sido revisado.

O arquivo `examples/projects/coldfire-template.json` é um template, com campos `CONFIGURAR_...`; ele não contém uma receita inventada para uma versão desconhecida do CodeWarrior. Substitua os campos pelos comandos documentados e já testados da instalação da bancada. Caminhos locais e configurações de licença não devem ser publicados.

## Build e gravação

A saída combinada da ferramenta aparece na aba, incluindo mensagens `arquivo:linha`, warnings e erros. A execução é assíncrona, tem limite de 120 segundos e pode ser cancelada; projetos maiores devem usar uma receita apropriada e ajustar esse limite no código, se necessário.

Um build só habilita o uso do artefato após saída normal com código zero e arquivo não vazio. O PRISMA calcula o SHA-256 e invalida a gravação quando o conteúdo muda. Isso verifica integridade, **não** verifica arquitetura da imagem, endereços Flash, MCU real ou adequação do linker: esses pontos exigem revisão da toolchain e da bancada.

A gravação requer um comando `flash`, aquisição serial desconectada e confirmação explícita contendo alvo, caminho, hash e comando. `{artifact}` é substituído pelo caminho do arquivo validado. Use somente o procedimento de linha de comando documentado para o modelo/versão do PEmicro disponível. Não há comando PEmicro padrão pré-configurado.

Não cancele uma gravação física em andamento sem conhecer o procedimento de recuperação do probe; cancelar encerra o processo externo, não desfaz operações já realizadas.

## GDB/MI

Quando a instalação fornecer GDB compatível com ColdFire e servidor remoto compatível, configure `debugger` e `remote`. Inicie o servidor separadamente e use **Iniciar depuração** após um build válido. O PRISMA abre `--interpreter=mi2` com o artefato e solicita a conexão remota.

Controles disponíveis:

- **Breakpoint:** solicita `arquivo:linha` e envia `-break-insert` com o argumento escapado.
- **Registradores:** solicita nomes e valores em hexadecimal.
- **Continuar / Pausar:** envia os comandos MI correspondentes.
- **Encerrar depuração:** encerra o processo cliente GDB.

As respostas MI e os erros ficam visíveis na aba. O cliente não grava firmware automaticamente. A compatibilidade específica CodeWarrior/PEmicro/ColdFire ainda não foi validada, e algumas versões podem não oferecer esse caminho GDB. Nesses casos, usar o depurador do fabricante até implementar o adaptador apropriado; não marcar a integração real como concluída.
