# Instalar el MCP de Kortex en modo HTTP local con Claude Code

Este modo es para equipos Windows cuya política de Claude Code no admite servidores MCP locales por stdio pero sí los servidos en
`http://localhost`. Si tu cliente admite stdio, usa la instalación con `uvx` del README: es más sencilla.

**Para la persona:** descarga o clona este repositorio en una carpeta tuya (por ejemplo `C:\Users\<tu usuario>\KortexMCP`) y deja
a mano el `config.json` que te dé el equipo de Kortex (dice a qué entorno de Kortex conectarse; no contiene secretos). Abre Claude
Code con esa carpeta como carpeta de trabajo y pégale esto:

> Lee `distribucion/INSTALAR_CON_CLAUDE_CODE.md` y sigue las instrucciones para Claude Code para instalarme el MCP de Kortex. El
> config.json está en `<ruta>`.

Necesitas tu usuario de Kortex (tu correo) y una **aplicación de autenticación** en el móvil: Kortex tiene verificación en dos pasos
obligatoria. **Antes de instalar, entra una vez en la web de Kortex** con la contraseña temporal que te hayan dado: te pedirá una
contraseña nueva y te enseñará un código QR para dar de alta Kortex en la aplicación. La contraseña y los códigos los escribes tú en
tu terminal: nunca se los des a Claude Code ni los pegues en el chat.

---

## Instrucciones para Claude Code

Estás instalando en este equipo Windows el MCP de Kortex en modo HTTP local. Es **un único MCP, `kortex`**, con **un único login**:
siempre da `list_collections` y `retrieve` (si hay clave personal), las herramientas de consulta con el login y, si el usuario es
administrador de la KB (grupo `kb-admin`; lo decide Kortex, no la persona), también las de administración.
Sigue estos pasos en orden y no improvises otros. Ejecuta los scripts desde la raíz del repositorio.

**Reglas**
- **Nunca pidas, leas ni escribas contraseñas ni códigos de verificación.** El login lo hace la persona en su propia terminal. No leas
  ni muestres el contenido de `%USERPROFILE%\.kortex\` (sesión cifrada, ficha local, caché).
- No edites `~/.claude.json` ni ficheros de configuración a mano: el registro lo hace el script (con `claude mcp add` si está la
  CLI; si no, `registrar-escritorio`, que solo toca la entrada `kortex` y guarda una copia previa).
- No instales nada más que lo que hace `instalar.ps1`. Si algo falla, explica el error a la persona y para.
- El MCP se sirve por HTTP **solo en 127.0.0.1** con una ficha local. No intentes registrarlo por stdio en este modo.

**Paso 1 · Preparar** (entorno de Python, dependencias y config.json; tarda uno o dos minutos):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\distribucion\instalar.ps1 -Paso preparar -Config "<ruta del config.json>"
```

Si el config.json tiene varios entornos, añade `-Entorno <nombre>` aquí y en el paso 3. Si sale `FALTA_PYTHON`, dile a la persona
que instale Python 3.11 o superior (marcando «Add python.exe to PATH») y que te avise. Si falla `pip`, suele ser el proxy o la red:
díselo tal cual. Si sale `FALTA_CONFIG`, falta el config.json.

**Paso 2 · Login (lo hace la persona).** Primero confirma que ya ha entrado una vez en la web y ha dado de alta la aplicación de
autenticación (si no, el login responde «Entra primero en la web…»). El paso 1 imprime la orden exacta. Pídele que abra **una
ventana de PowerShell aparte** (no en este chat), que la pegue y que escriba su usuario, su contraseña y el código de 6 dígitos.
Espera a que te diga que ha salido «✓ … entra».

**Paso 3 · Activar** (arranca el servidor local, lo registra en Claude Code y lo prueba):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\distribucion\instalar.ps1 -Paso activar
```

Pregunta antes si quiere que arranque solo al iniciar Windows; si dice que sí, añade `-AlIniciarWindows`. Si no, tendrá que lanzar
`distribucion\arrancar.ps1` después de cada reinicio.

Resultado esperado: «✓ http://127.0.0.1:8765/mcp: 8 herramientas» (consulta) o «… 54 herramientas» (administración de la KB),
seguido de `quien_soy` con su usuario y su equipo, y «LISTO». Errores:
- `FALTA_LOGIN`: el paso 2 no se hizo o no terminó bien; que lo repita.
- Otro error: muéstrale las últimas líneas de `%USERPROFILE%\.kortex\mcp_kortex.log` (no contienen secretos).

**Paso 4 · Cierre.** Dile que abra una **sesión nueva** de Claude Code (en esta no aparecerán las herramientas) y que pruebe, por
ejemplo: «Con kortex, ¿qué documentos tengo y de qué tratan?». Explícale en dos líneas:
- `consultar` busca en su documentación y añade lo que sabe la KB como contexto, incluidas notas de otros equipos ya redactadas
  por Kortex (sin el texto original ni de dónde vienen);
- la sesión dura 30 días desde el login: cuando caduque, la herramienta lo dirá; que repita el paso 2 en su terminal con un código
  nuevo (no hace falta reiniciar el servidor si ya tenía las herramientas).

## Desinstalar

```powershell
claude mcp remove kortex --scope user
schtasks /Delete /TN "Kortex MCP" /F
.\.venv\Scripts\python.exe -m mcps.kortex_mcp.server logout
```

Después, borrar la carpeta del repositorio y `%USERPROFILE%\.kortex` (config.json, sesión cifrada, ficha local y caché).
