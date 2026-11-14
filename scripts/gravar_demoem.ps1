<#
.SYNOPSIS
  Compila (opcional) e grava o firmware da DEMOEM pelo HI-WAVE/PEmicro, sem interação.
.DESCRIPTION
  Usa a configuração CFV1_BDM_P&E_Multilink_CyclonePro.ini do projeto "EM256 Demo":
  LOAD com VERIFYALL, GO e encerra o HI-WAVE. Feche qualquer sessão HI-WAVE aberta antes.
.EXAMPLE
  .\scripts\gravar_demoem.ps1 -Build
#>
param(
    [switch]$Build,
    [int]$TimeoutSeconds = 180,
    [string]$CodeWarrior = 'C:\Program Files (x86)\Freescale\CodeWarrior for Microcontrollers V6.3'
)
$ErrorActionPreference = 'Stop'
$project = Join-Path $PSScriptRoot '..\firmware\codewarrior\EM256 Demo' | Resolve-Path
$abs = Join-Path $project 'bin\Project.abs'

if ($Build) {
    $out = & (Join-Path $CodeWarrior 'bin\CmdIDE.exe') (Join-Path $project 'EM256 Demo.mcp') /b /q 2>&1 | Out-String
    Write-Output $out.Trim()
    if ($LASTEXITCODE -ne 0) { throw "Build falhou (código $LASTEXITCODE)." }
}
if (-not (Test-Path $abs)) { throw "Artefato inexistente: $abs" }
$hash = (Get-FileHash $abs -Algorithm SHA256).Hash
Write-Output "Gravando $abs`nSHA-256 $hash"

$log = Join-Path $project 'bin\gravacao.log'
$cmd = Join-Path $project 'bin\prisma_auto_flash.cmd'
@(
    "LF `"$log`""
    'FLASH'
    'FLASH SELECT'
    'FLASH ERASE'
    'FLASH ARM'
    'LOAD "bin\Project.abs" VERIFYALL NOPROGRESSBAR'
    'FLASH DISARM'
    'FLASH UNSELECT'
    'RESET'
    'GO'
    'WAIT 20'
    'NOLF'
    'EXIT'
) | Set-Content -Path $cmd -Encoding ascii
if (Test-Path $log) { Remove-Item $log -Force }

$hiwave = Join-Path $CodeWarrior 'prog\hiwave.exe'
$ini = Join-Path $project 'CFV1_BDM_P&E_Multilink_CyclonePro.ini'
$proc = Start-Process -FilePath $hiwave -WorkingDirectory $project -PassThru `
    -ArgumentList @("-Prod=`"$ini`"", "-Cmd=`"call \`"$cmd\`"`"")
if (-not $proc.WaitForExit($TimeoutSeconds * 1000)) {
    Stop-Process -Id $proc.Id -Force
    throw "HI-WAVE não terminou em $TimeoutSeconds s (diálogo de conexão aberto?). Gravação não confirmada."
}
if (Test-Path $log) { Get-Content $log }
$text = if (Test-Path $log) { Get-Content $log -Raw } else { '' }
if ($text -notmatch '(?i)load') { throw 'Sem registro de LOAD no log; gravação não confirmada.' }
if ($text -match '(?i)error|fail|erro') { throw 'O log do HI-WAVE contém erro; ver acima.' }
Write-Output 'Gravação concluída e alvo em execução.'
