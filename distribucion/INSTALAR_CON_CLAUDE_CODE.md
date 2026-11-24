# Instalar el MCP de Kortex con Claude Code

**Para la persona:** descomprime este ZIP en una carpeta tuya (por ejemplo `C:\Users\<tu usuario>\KortexMCP`). Abre la app de
Claude de escritorio, pestaña **Code**, elige esa carpeta como carpeta de trabajo y pégale esto:

> Lee `INSTALAR_CON_CLAUDE_CODE.md` de esta carpeta y sigue las instrucciones para Claude Code para instalarme el MCP de Kortex.

Necesitas tu usuario de la web de ingesta de Kortex (tu correo; te lo da el equipo de Kortex) y una **aplicación de autenticación**
en el móvil (Microsoft Authenticator, Google Authenticator…): las webs de Kortex tienen verificación en dos pasos obligatoria.
**Antes de instalar, entra una vez en la web** con la contraseña temporal que te hayan dado: te pedirá una contraseña nueva y te
enseñará un código QR para dar de alta Kortex en la aplicación. La contraseña y los códigos los escribes tú en tu terminal: nunca se
los des a Claude Code ni los pegues en el chat.

---

## Instrucciones para Claude Code

Eres Claude Code (normalmente en la app de Claude de escritorio, pestaña Code) instalando en este equipo Windows el MCP local de
Kortex. Es **un único MCP, `kortex`**, con **un único login** (el usuario de la web de ingesta): da las herramientas de consulta, y
todas si ese usuario es administrador de la KB (grupo `kb-admin`; lo decide AWS, no la persona).
Sigue estos pasos en orden y no improvises otros. Ejecuta los scripts desde la carpeta donde está este fichero (la raíz del ZIP).

**Reglas**
- **Nunca pidas, leas ni escribas contraseñas ni códigos de verificación.** El login lo hace la persona en su propia terminal. No leas ni muestres el contenido de
  `%USERPROFILE%\.kortex\` (credenciales cifradas, sesiones y fichas locales).
- No edites `~/.claude.json` ni ficheros de configuración a mano: el registro lo hace el script (con `claude mcp add` si está la
  CLI; si no, `kortex.py registrar-escritorio`, que solo toca la entrada `kortex` y guarda una copia previa).
- No instales nada más que lo que hace `instalar.ps1`. Si algo falla, explica el error a la persona y para.
- El MCP se sirve por HTTP **solo en 127.0.0.1** porque la política corporativa no deja registrar MCP locales por stdio y sí los de
  `http://localhost`. No intentes registrarlo por stdio.
- **No arranques Docker ni Rancher Desktop** (la política los bloquea; aquí no hacen falta).

**Paso 1 · Preparar** (entorno de Python y dependencias; tarda uno o dos minutos):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\instalar.ps1 -Paso preparar
```

Si sale `FALTA_PYTHON`, dile a la persona que instale Python 3.11 o superior desde el Portal de empresa o python.org (marcando «Add
python.exe to PATH») y que te avise. Si falla `pip`, suele ser el proxy o la red: díselo tal cual.

**Paso 2 · Login (lo hace la persona).** Primero confirma que ya ha entrado una vez en la web y ha dado de alta la aplicación de
autenticación (si no, el login responde «Entra primero en la web…»). El paso 1 imprime la orden exacta. Pídele que abra **una
ventana de PowerShell aparte** (no en este chat), que la pegue y que escriba su usuario, su contraseña y el código de 6 dígitos que
le muestre la aplicación. No pide nada más: el mismo login vale para todo. Espera a que te diga que ha salido «✓ … entra».

**Paso 3 · Activar** (arranca el servidor local, lo registra en Claude Code y lo prueba):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\instalar.ps1 -Paso activar
```

Pregunta antes si quiere que arranque solo al iniciar Windows; si dice que sí, añade `-AlIniciarWindows`. Si no, tendrá que lanzar
`mcp\arrancar.ps1` después de cada reinicio.

Resultado esperado: «✓ http://127.0.0.1:8765/mcp: 7 herramientas» (consulta) o «… 53 herramientas» (admin), seguido de `quien_soy`
con su usuario y su equipo, y «LISTO». Errores:
- `FALTA_LOGIN`: el paso 2 no se hizo o no terminó bien; que lo repita.
- Otro error: muéstrale las últimas líneas de `%USERPROFILE%\.kortex\mcp_kortex.log` (no contienen secretos).

**Paso 4 · Cierre.** Dile que abra una **sesión nueva** de Claude Code (en esta no aparecerán las herramientas) y que pruebe, por
ejemplo: «Con kortex, ¿qué documentos tengo y de qué tratan?». Explícale en dos líneas:
- `consultar` busca en su documentación y añade lo que sabe la KB como contexto (no cuesta nada);
- `preguntar_chat_web` usa el chat de la web (gasta, es para comparar);
- la sesión dura 30 días desde el login (verificación en dos pasos): cuando caduque, la herramienta lo dirá; que repita el paso 2
  en su terminal con un código nuevo (no hace falta reiniciar el servidor).

## Desinstalar

```powershell
claude mcp remove kortex --scope user
```

```powershell
schtasks /Delete /TN "Kortex MCP" /F
```

Después, borrar esta carpeta y `%USERPROFILE%\.kortex` (usuario guardado y sesiones cifradas).
