# Arranca en segundo plano el MCP de Kortex por HTTP local (127.0.0.1:8765). Desde el 23/11/2026 es UN SOLO MCP («kortex»): con el
# login de la ingesta da las herramientas de consulta; con el admin de la KB (equipo Kortex), todas. Hace de reinicio: para antes los
# servidores de Kortex que hubiera (también los antiguos, uno por perfil en 8765 y 8766), así que sirve para recargar tras un login.
# Uso: powershell -ExecutionPolicy Bypass -File mcp\arrancar.ps1   (al iniciar sesión: ver mcp\README.md)
# -Perfiles consulta,admin arranca a la antigua (un servidor por perfil); solo para pruebas.
# 20/11/2026: el servidor se crea DESVINCULADO (Win32_Process.Create, oculto): con Start-Process heredaba la salida de quien lo lanzaba
# y una herramienta que esperase esa salida (Claude Code, una tubería) no terminaba nunca.
param([string]$Perfiles)
$raiz = Split-Path -Parent $PSScriptRoot
$py = Join-Path $raiz ".venv\Scripts\python.exe"
$lanzador = Join-Path $PSScriptRoot "kortex.py"
$registros = Join-Path $env:USERPROFILE ".kortex"
New-Item -ItemType Directory -Force $registros | Out-Null
$oculto = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ ShowWindow = [uint16]0 }

function Lanzar($argumentos, $nombre, $puerto) {
    $log = Join-Path $registros "mcp_$nombre.log"
    $orden = "cmd.exe /d /c `"`"$py`" `"$lanzador`" servir $argumentos --puerto $puerto 1>`"$log.out`" 2>`"$log`"`""
    $r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $orden; CurrentDirectory = $raiz; ProcessStartupInformation = $oculto }
    if ($r.ReturnValue -ne 0) { Write-Host "MCP ${nombre}: no se pudo arrancar (código $($r.ReturnValue))"; return }
    Write-Host "MCP ${nombre}: arrancado en http://localhost:$puerto/mcp (registro: $log)"
}

# para los servidores de Kortex de ESTE usuario (solo los que lanza kortex.py servir)
Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'cmd.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match [regex]::Escape($lanzador) -and $_.CommandLine -match ' servir' } |
    ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch { } }
Start-Sleep -Seconds 1

$lista = @($Perfiles -split "[,; ]+" | Where-Object { $_ })
if ($lista) {
    $puertos = @{ admin = 8765; consulta = 8766 }
    foreach ($perfil in $lista) { if ($puertos[$perfil]) { Lanzar "--perfil $perfil" $perfil $puertos[$perfil] } else { Write-Host "Perfil desconocido: $perfil" } }
    exit 0
}
$hayLogin = @("admin", "consulta") | Where-Object { Test-Path (Join-Path $registros "credenciales_$_.json") }
if (-not $hayLogin) { Write-Host "No hay ningún login: ejecuta antes  & `"$py`" `"$lanzador`" login"; exit 3 }
Lanzar "" "kortex" 8765
