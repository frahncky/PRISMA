<#
.SYNOPSIS
  Compila um firmware da DEMOEM no CodeWarrior 6.3, sem gravar.
  -Projeto: "EM256 Demo" (padrão, imagem independente), "EM256 App" (aplicação
  para o bootloader, em 0x20000) ou "EM256 Boot" (bootloader).
.DESCRIPTION
  O IDE do CodeWarrior 6.3 trava ao fechar sozinho depois de um build em lote
  (CmdIDE /b /q): "unhandled exception 0xc0000005" numa janela "CodeWarrior Error".
  O build já terminou quando isso acontece, mas a janela fica aberta. Por isso o
  build roda sem /q e o IDE aberto por ele é encerrado à força em seguida, sem
  passar pelo código de saída que trava. Um IDE que já estava aberto não é tocado.
.EXAMPLE
  .\scripts\compilar_demoem.ps1
.EXAMPLE
  .\scripts\compilar_demoem.ps1 -Projeto 'EM256 Boot'
#>
param(
    [ValidateSet('EM256 Demo', 'EM256 App', 'EM256 Boot')]
    [string]$Projeto = 'EM256 Demo',
    [string]$CodeWarrior = 'C:\Program Files (x86)\Freescale\CodeWarrior for Microcontrollers V6.3'
)
$ErrorActionPreference = 'Stop'
$project = Join-Path $PSScriptRoot "..\firmware\codewarrior\$Projeto" | Resolve-Path
$before = @(Get-Process ide -ErrorAction SilentlyContinue | ForEach-Object Id)
try {
    # O CmdIDE escreve o resultado em stderr; no Windows PowerShell 5 isso vira erro com 'Stop'.
    $ErrorActionPreference = 'Continue'
    $out = & (Join-Path $CodeWarrior 'bin\CmdIDE.exe') (Join-Path $project "$Projeto.mcp") /b 2>&1 |
        ForEach-Object { "$_" } | Out-String
    $code = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
} finally {
    Get-Process ide -ErrorAction SilentlyContinue | Where-Object { $before -notcontains $_.Id } |
        Stop-Process -Force -ErrorAction SilentlyContinue
}
Write-Output $out.Trim()
if ($code -ne 0) { throw "Build falhou (código $code)." }
$abs = Join-Path $project 'bin\Project.abs'
Write-Output ("Artefato {0} ({1:N0} bytes, {2})" -f $abs, (Get-Item $abs).Length, (Get-Item $abs).LastWriteTime)
