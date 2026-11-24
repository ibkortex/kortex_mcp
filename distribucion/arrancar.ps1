# Arranca en segundo plano el MCP de Kortex por HTTP local (127.0.0.1, puerto 8765 por defecto). Hace de reinicio: para antes el
# servidor HTTP local de Kortex que hubiera de este usuario, así que sirve para recargar las herramientas tras un login.
# Uso: powershell -ExecutionPolicy Bypass -File distribucion\arrancar.ps1 [-Puerto 8765] [-Entorno prod]
# El servidor se crea DESVINCULADO (Win32_Process.Create, oculto): con Start-Process heredaba la salida de quien lo lanzaba y una
# herramienta que esperase esa salida (Claude Code, una tubería) no terminaba nunca.
param([int]$Puerto = 8765, [string]$Entorno = "")
$raiz = Split-Path -Parent $PSScriptRoot
$py = Join-Path $raiz ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Host "Falta el entorno de Python: ejecuta antes distribucion\instalar.ps1 -Paso preparar"; exit 2 }
$registros = Join-Path $env:USERPROFILE ".kortex"
New-Item -ItemType Directory -Force $registros | Out-Null
$oculto = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ ShowWindow = [uint16]0 }

# para los servidores HTTP locales de Kortex de ESTE usuario (solo los lanzados como «mcps.kortex_mcp.server serve --http-local»)
Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'cmd.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match 'mcps\.kortex_mcp\.server' -and $_.CommandLine -match '--http-local' } |
    ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch { } }
Start-Sleep -Seconds 1

$entorno = if ($Entorno) { " --entorno $Entorno" } else { "" }
$log = Join-Path $registros "mcp_kortex.log"
$orden = "cmd.exe /d /c `"`"$py`" -m mcps.kortex_mcp.server serve --http-local --port $Puerto$entorno 1>`"$log.out`" 2>`"$log`"`""
$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $orden; CurrentDirectory = $raiz; ProcessStartupInformation = $oculto }
if ($r.ReturnValue -ne 0) { Write-Host "MCP kortex: no se pudo arrancar (código $($r.ReturnValue))"; exit 1 }
Write-Host "MCP kortex: arrancado en http://localhost:$Puerto/mcp (registro: $log)"
