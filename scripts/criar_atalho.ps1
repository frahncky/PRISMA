<#
.SYNOPSIS
  Cria um atalho "PRISMA" na área de trabalho (ou na inicialização do Windows), com o ícone do projeto.
.DESCRIPTION
  O atalho abre o PRISMA sem janela de terminal (pythonw) e reusa a última
  porta, perfil e monitor (--last). Remova o atalho para desfazer.
  -Inicializacao põe o atalho na pasta Inicializar do usuário: o PRISMA abre
  sozinho depois do login. É o jeito de ligar o modo quiosque numa tela
  dedicada (docs/quiosque.md).
.EXAMPLE
  .\scripts\criar_atalho.ps1
.EXAMPLE
  .\scripts\criar_atalho.ps1 -Argumentos "--port COM4 --profile examples\profiles\demoem-ch340.json --connect"
.EXAMPLE
  .\scripts\criar_atalho.ps1 -Argumentos "--quiosque --port prisma.local --screen 2" -Inicializacao
#>
param(
    [string]$Argumentos = '--last',
    [switch]$Inicializacao,
    [string]$Nome = 'PRISMA'
)
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..')
$pythonw = Join-Path $root '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $pythonw)) { throw "Ambiente não encontrado: $pythonw. Crie o .venv e instale o PRISMA antes." }
$icon = Join-Path $root 'src\prisma\ui\assets\prisma.ico'
$folder = if ($Inicializacao) { [Environment]::GetFolderPath('Startup') } else { [Environment]::GetFolderPath('Desktop') }
$link = Join-Path $folder "$Nome.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = "-m prisma $Argumentos"
$shortcut.WorkingDirectory = $root
$shortcut.IconLocation = "$icon,0"
$shortcut.Description = 'PRISMA · Programar, Medir, Analisar'
$shortcut.Save()
Write-Output "Atalho criado: $link"
if ($Inicializacao) { Write-Output 'O PRISMA vai abrir sozinho no próximo login. Apague o atalho para desfazer.' }
