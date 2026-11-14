<#
.SYNOPSIS
  Cria um atalho "PRISMA" na área de trabalho, com o ícone do projeto.
.DESCRIPTION
  O atalho abre o PRISMA sem janela de terminal (pythonw) e reusa a última
  porta, perfil e monitor (--last). Remova o atalho para desfazer.
.EXAMPLE
  .\scripts\criar_atalho.ps1
  .\scripts\criar_atalho.ps1 -Argumentos "--port COM4 --profile examples\profiles\demoem-ch340.json --connect"
#>
param(
    [string]$Argumentos = '--last'
)
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..')
$pythonw = Join-Path $root '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $pythonw)) { throw "Ambiente não encontrado: $pythonw. Crie o .venv e instale o PRISMA antes." }
$icon = Join-Path $root 'src\prisma\ui\assets\prisma.ico'
$desktop = [Environment]::GetFolderPath('Desktop')
$link = Join-Path $desktop 'PRISMA.lnk'

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = "-m prisma $Argumentos"
$shortcut.WorkingDirectory = $root
$shortcut.IconLocation = "$icon,0"
$shortcut.Description = 'PRISMA · Programar, Medir, Analisar'
$shortcut.Save()
Write-Output "Atalho criado: $link"
