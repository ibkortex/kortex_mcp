# Instalador del MCP local de Kortex para Claude Code (Windows). Lo lanza Claude Code siguiendo INSTALAR_CON_CLAUDE_CODE.md.
#   powershell -ExecutionPolicy Bypass -File instalar.ps1 -Paso preparar     → entorno de Python y dependencias
#   powershell -ExecutionPolicy Bypass -File instalar.ps1 -Paso activar      → arranca, registra en Claude Code y prueba
#   (añade -AlIniciarWindows para que arranque solo al iniciar sesión)
# 23/11/2026: UN SOLO MCP («kortex» desde el 24/11/2026, 127.0.0.1:8765). Con el login de la ingesta da las herramientas de consulta; si además se hace
# login con el admin de la KB (equipo Kortex), todas. -Perfil se acepta por compatibilidad y ya no cambia nada.
# El login NO lo hace este script: lo hace la persona en su terminal (la contraseña y el código no pasan por Claude Code).
# 23/11/2026: MFA obligatorio. El login pide usuario, contraseña y el código de 6 dígitos de la aplicación de autenticación; la
# contraseña no se guarda y la sesión dura 30 días (después se repite el login). La primera vez hay que entrar antes en la web, que pide
# cambiar la contraseña temporal y dar de alta la aplicación de autenticación (código QR).
param(
    [ValidateSet("preparar", "activar")][string]$Paso = "preparar",
    [string]$Perfil = "",
    [switch]$AlIniciarWindows
)
$ErrorActionPreference = "Continue"            # los códigos de salida se comprueban a mano ($LASTEXITCODE)
$raiz = $PSScriptRoot
$venv = Join-Path $raiz ".venv"
$py = Join-Path $venv "Scripts\python.exe"
$lanzador = Join-Path $raiz "mcp\kortex.py"
$kortex = Join-Path $env:USERPROFILE ".kortex"
$env:PYTHONIOENCODING = "utf-8"

function Buscar-Python {
    foreach ($c in @(@("py", "-3.13"), @("py", "-3.12"), @("py", "-3.11"), @("py", "-3"), @("python"), @("python3"))) {
        try {
            $v = & $c[0] $c[1..9] -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($LASTEXITCODE -eq 0 -and $v -and [version]$v -ge [version]"3.11") { return , $c }
        } catch { }
    }
    return $null
}

if ($Paso -eq "preparar") {
    if (-not (Test-Path $py)) {
        $base = Buscar-Python
        if (-not $base) { Write-Host "FALTA_PYTHON: hace falta Python 3.11 o superior (python.org o Portal de empresa)."; exit 10 }
        Write-Host "Creando el entorno con: $($base -join ' ')"
        & $base[0] $base[1..9] -m venv $venv
        if ($LASTEXITCODE -ne 0) { Write-Host "No se pudo crear el entorno .venv"; exit 11 }
    }
    & $py -m pip install --disable-pip-version-check -q -r (Join-Path $raiz "mcp\requirements-fijas.txt")
    if ($LASTEXITCODE -ne 0) { Write-Host "Falló la instalación de dependencias (¿proxy o sin acceso a PyPI?)"; exit 12 }
    & $py -c "import mcp, pycognito, requests, uvicorn; print('dependencias OK')"
    Write-Host ""
    Write-Host "SIGUIENTE (lo hace la persona en SU terminal PowerShell, no Claude Code):"
    Write-Host "  1) si es su primera vez: entrar en la web con la contraseña temporal, cambiarla y dar de alta la aplicación de autenticación"
    Write-Host "  2) & `"$py`" `"$lanzador`" login   (usuario, contraseña y código de 6 dígitos)"
    exit 0
}

# ---------------------------------------------------------------- activar
if (-not (Test-Path $py)) { Write-Host "Primero: instalar.ps1 -Paso preparar"; exit 20 }
$claude = Get-Command claude -ErrorAction SilentlyContinue      # 24/11/2026: sin la CLI (solo Claude de escritorio) se registra igual
# hay login si hay usuario guardado Y su sesión (credenciales_*.json ya no lleva contraseña: solo el usuario)
$hayLogin = @("consulta", "admin") | Where-Object {
    (Test-Path (Join-Path $kortex "credenciales_$_.json")) -and (Get-ChildItem -Path $kortex -Filter "sesion_$($_)_*.json" -ErrorAction SilentlyContinue) }
if (-not $hayLogin) {
    Write-Host "FALTA_LOGIN: no hay ningún login (o no terminó). La persona debe ejecutar en SU terminal (usuario, contraseña y código):"
    Write-Host "  & `"$py`" `"$lanzador`" login"
    exit 22
}
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $raiz "mcp\arrancar.ps1")
Start-Sleep -Seconds 6
$orden = (& $py $lanzador registro | Select-Object -Last 1)
$ficha = [regex]::Match($orden, 'Bearer ([A-Za-z0-9_\-]+)').Groups[1].Value
if ($claude) {
    foreach ($n in @("kortex", "kortex-poc", "kortex-poc-consulta")) { & claude mcp remove $n --scope user 2>$null | Out-Null }   # los nombres antiguos, fuera
    & claude mcp add --transport http kortex "http://localhost:8765/mcp" --scope user --header "Authorization: Bearer $ficha" | Out-Null   # su salida repite la ficha local
    if ($LASTEXITCODE -ne 0) { Write-Host "No se pudo registrar kortex en Claude Code"; exit 23 }
} else {
    & $py $lanzador registrar-escritorio      # Claude Code de escritorio: la misma entrada de usuario en ~/.claude.json, con copia previa
    if ($LASTEXITCODE -ne 0) { Write-Host "No se pudo registrar kortex en Claude Code"; exit 23 }
}
& $py $lanzador probar
if ($LASTEXITCODE -ne 0) { Write-Host "El MCP no responde bien (ver %USERPROFILE%\.kortex\mcp_kortex.log)"; exit 24 }
if ($AlIniciarWindows) {
    $tarea = "powershell -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$(Join-Path $raiz 'mcp\arrancar.ps1')`""
    schtasks /Create /F /SC ONLOGON /TN "Kortex MCP" /TR $tarea | Out-Null
    Write-Host "Tarea «Kortex MCP» creada: arranca al iniciar sesión en Windows."
}
if ($claude) { & claude mcp list 2>$null | Select-String "kortex" }
Write-Host "LISTO: abre una sesión NUEVA de Claude Code (en Claude de escritorio, pestaña Code) para ver las herramientas de Kortex."
