# Diagnóstico somente leitura do USB/BDM/serial no Windows.
Write-Host "=== Interfaces BDM/PEmicro/COM detectadas ==="
Get-CimInstance Win32_PnPEntity |
  Where-Object { $_.Name -match 'BDM|PEmicro|Multilink|COM[0-9]' -or $_.PNPDeviceID -match 'VID_' } |
  Select-Object Name, Status, ConfigManagerErrorCode, PNPDeviceID |
  Format-Table -AutoSize
Write-Host "=== Portas seriais ==="
Get-CimInstance Win32_SerialPort |
  Select-Object DeviceID, Name, PNPDeviceID |
  Format-Table -AutoSize
Write-Host "O comando não instala drivers nem altera o firmware."
