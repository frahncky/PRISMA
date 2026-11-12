# Diagnóstico somente leitura do USB/BDM/serial no Windows.
param([string]$OutputPath = ".\diagnostico-prisma.json")
$ErrorActionPreference = "Stop"
$devices = @(Get-CimInstance Win32_PnPEntity |
  Where-Object { $_.Name -match 'BDM|PEmicro|Multilink|COM[0-9]' -or $_.PNPDeviceID -match 'VID_' } |
  Select-Object Name, Status, ConfigManagerErrorCode, PNPDeviceID)
$ports = @(Get-CimInstance Win32_SerialPort |
  Select-Object DeviceID, Name, PNPDeviceID)
$ids = @($devices | ForEach-Object { $_.PNPDeviceID })
$drivers = @(Get-CimInstance Win32_PnPSignedDriver |
  Where-Object { $ids -contains $_.DeviceID } |
  Select-Object DeviceName, DeviceID, DriverProviderName, DriverVersion, DriverDate, InfName)
$report = [ordered]@{
  captured_utc = [DateTime]::UtcNow.ToString("o")
  windows = (Get-CimInstance Win32_OperatingSystem).Caption
  devices = $devices
  serial_ports = $ports
  drivers = $drivers
  note = "Inventario observado. Nao comprova pinagem, funcionamento da COM ou compatibilidade BDM."
}
$report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
$devices | Format-Table -AutoSize
$ports | Format-Table -AutoSize
Write-Host "Diagnostico salvo em $OutputPath"
Write-Host "O comando nao instala drivers nem altera o firmware."
