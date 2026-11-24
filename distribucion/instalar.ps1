# Instalador del MCP de Kortex en modo HTTP local para Claude Code (Windows). Lo lanza Claude Code siguiendo
# distribucion\INSTALAR_CON_CLAUDE_CODE.md, desde la raíz del repositorio (o del ZIP de una versión publicada).
#   powershell -ExecutionPolicy Bypass -File distribucion\instalar.ps1 -Paso preparar [-Config <ruta del config.json>]
#   powershell -ExecutionPolicy Bypass -File distribucion\instalar.ps1 -Paso activar [-AlIniciarWindows] [-Puerto 8765] [-Entorno prod]
# El login NO lo hace este script: lo hace la persona en su terminal (la contraseña y el código no pasan por Claude Code).
# MFA obligatorio: el login pide usuario, contraseña y el código de 6 dígitos de la aplicación de autenticación; la contraseña no se
# guarda y la sesión dura 30 días (después se repite el login). La primera vez hay que entrar antes en la web de Kortex, que pide
# cambiar la contraseña temporal y dar de alta la aplicación de autenticación (código QR).
param(
    [ValidateSet("preparar", "activar")][string]$Paso = "preparar",
    [string]$Config = "",
    [string]$Entorno = "",
    [int]$Puerto = 8765,
    [switch]$AlIniciarWindows
)
$ErrorActionPreference = "Continue"            # los códigos de salida se comprueban a mano ($LASTEXITCODE)
$raiz = Split-Path -Parent $PSScriptRoot       # donde está pyproject.toml
$venv = Join-Path $raiz ".venv"
$py = Join-Path $venv "Scripts\python.exe"
$kortex = Join-Path $env:USERPROFILE ".kortex"
$cli = @("-m", "mcps.kortex_mcp.server")
$ent = @(); if ($Entorno) { $ent = @("--entorno", $Entorno); $env:KORTEX_ENTORNO = $Entorno }
$env:PYTHONIOENCODING = "utf-8"
$ordenLogin = "& `"$py`" -m mcps.kortex_mcp.server login" + $(if ($Entorno) { " --entorno $Entorno" } else { "" })

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
        if (-not $base) { Write-Host "FALTA_PYTHON: hace falta Python 3.11 o superior."; exit 10 }
        Write-Host "Creando el entorno con: $($base -join ' ')"
        & $base[0] $base[1..9] -m venv $venv
        if ($LASTEXITCODE -ne 0) { Write-Host "No se pudo crear el entorno .venv"; exit 11 }
    }
    & $py -m pip install --disable-pip-version-check -q $raiz
    if ($LASTEXITCODE -ne 0) { Write-Host "Falló la instalación de dependencias (¿proxy o sin acceso a PyPI?)"; exit 12 }
    & $py -c "import mcp, pycognito, requests, uvicorn, mcps.kortex_mcp.server; print('dependencias OK')"
    if ($Config) {
        if (-not (Test-Path $Config)) { Write-Host "No encuentro el config.json indicado: $Config"; exit 13 }
        New-Item -ItemType Directory -Force $kortex | Out-Null
        Copy-Item -Force $Config (Join-Path $kortex "config.json")
        Write-Host "config.json copiado a $kortex"
    }
    & $py @cli estado @ent
    & $py -c "import sys; from mcps.kortex_mcp.conocimiento import config; sys.exit(1 if config.cargar().faltan() else 0)" 2>$null
    if ($LASTEXITCODE -ne 0) { Write-Host "FALTA_CONFIG: pide al equipo de Kortex el config.json y repite con -Config <ruta>"; exit 14 }
    Write-Host ""
    Write-Host "SIGUIENTE (lo hace la persona en SU terminal PowerShell, no Claude Code):"
    Write-Host "  1) si es su primera vez: entrar en la web de Kortex con la contraseña temporal, cambiarla y dar de alta la aplicación de autenticación"
    Write-Host "  2) $ordenLogin   (usuario, contraseña y código de 6 dígitos)"
    exit 0
}

# ---------------------------------------------------------------- activar
if (-not (Test-Path $py)) { Write-Host "Primero: instalar.ps1 -Paso preparar"; exit 20 }
& $py -c "import sys; from mcps.kortex_mcp.conocimiento.sesion import perfil_actual; sys.exit(0 if perfil_actual() else 22)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "FALTA_LOGIN: no hay sesión de Kortex (o caducó). La persona debe ejecutar en SU terminal (usuario, contraseña y código):"
    Write-Host "  $ordenLogin"
    exit 22
}
$arrancar = Join-Path $PSScriptRoot "arrancar.ps1"
& powershell -NoProfile -ExecutionPolicy Bypass -File $arrancar -Puerto $Puerto -Entorno $Entorno
Start-Sleep -Seconds 6
$orden = (& $py @cli registro --port $Puerto | Select-Object -Last 1)
$ficha = [regex]::Match($orden, 'Bearer ([A-Za-z0-9_\-]+)').Groups[1].Value
$claude = Get-Command claude -ErrorAction SilentlyContinue      # sin la CLI (solo Claude de escritorio) se registra igual
if ($claude) {
    & claude mcp remove kortex --scope user 2>$null | Out-Null
    & claude mcp add --transport http kortex "http://localhost:$Puerto/mcp" --scope user --header "Authorization: Bearer $ficha" | Out-Null   # su salida repite la ficha local
    if ($LASTEXITCODE -ne 0) { Write-Host "No se pudo registrar kortex en Claude Code"; exit 23 }
} else {
    & $py @cli registrar-escritorio --port $Puerto      # la misma entrada de usuario en ~/.claude.json, con copia previa
    if ($LASTEXITCODE -ne 0) { Write-Host "No se pudo registrar kortex en Claude Code"; exit 23 }
}
& $py @cli probar --port $Puerto
if ($LASTEXITCODE -ne 0) { Write-Host "El MCP no responde bien (ver %USERPROFILE%\.kortex\mcp_kortex.log)"; exit 24 }
if ($AlIniciarWindows) {
    $extra = if ($Entorno) { " -Entorno $Entorno" } else { "" }
    $tarea = "powershell -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$arrancar`" -Puerto $Puerto$extra"
    schtasks /Create /F /SC ONLOGON /TN "Kortex MCP" /TR $tarea | Out-Null
    Write-Host "Tarea «Kortex MCP» creada: arranca al iniciar sesión en Windows."
}
if ($claude) { & claude mcp list 2>$null | Select-String "kortex" }
Write-Host "LISTO: abre una sesión NUEVA de Claude Code para ver las herramientas de Kortex."
