"""Configuración de las herramientas de conocimiento (consulta y administración de la KB). Sin valores codificados.

Cada dato sale, por este orden, de:
  1. su variable de entorno (KORTEX_API_URL, KORTEX_COGNITO_REGION, KORTEX_COGNITO_POOL_ID, KORTEX_COGNITO_CLIENT_ID, …);
  2. el entorno elegido de %USERPROFILE%\\.kortex\\config.json (lo entrega el equipo de Kortex; otra ruta con KORTEX_CONFIG).

config.json admite una forma plana o varios entornos con nombre:
  {"api_url": "https://…", "cognito_pool_id": "…", "cognito_client_id": "…", "cognito_region": "…"}
  {"entorno": "prod", "entornos": {"dev": {…}, "prod": {…}}}
El entorno se elige con `kortex-mcp --entorno <nombre>`, la variable KORTEX_ENTORNO o la clave «entorno» del fichero; si el fichero
solo tiene uno, ese. La región, si no se indica, sale del id del pool («<región>_<id>»).

Rutas de la API oficial: ${KORTEX_API_URL}/knowledge/v1 (ingesta y consulta) y ${KORTEX_API_URL}/kb/v1 (KB). Los prefijos se pueden
cambiar (KORTEX_KNOWLEDGE_PREFIX, KORTEX_KB_PREFIX) para probar contra un servidor local con las rutas internas (/poc/v3 y /api).

Los datos locales (sesión cifrada, caché de la KB, fotos de «lo nuevo desde», fichas de revisión) van en una carpeta por entorno
dentro de %USERPROFILE%\\.kortex (KORTEX_HOME para otra), fuera de cualquier repositorio."""
import json
import os
from dataclasses import dataclass
from pathlib import Path

# campo de config.json → variable de entorno
CAMPOS = {
    "api_url": "KORTEX_API_URL",
    "cognito_region": "KORTEX_COGNITO_REGION",
    "cognito_pool_id": "KORTEX_COGNITO_POOL_ID",
    "cognito_client_id": "KORTEX_COGNITO_CLIENT_ID",
    "knowledge_prefix": "KORTEX_KNOWLEDGE_PREFIX",
    "kb_prefix": "KORTEX_KB_PREFIX",
    "kb_campana": "KORTEX_KB_CAMPANA",
    "grupo_admin": "KORTEX_GRUPO_ADMIN",
}
POR_DEFECTO = {"knowledge_prefix": "/knowledge/v1", "kb_prefix": "/kb/v1", "kb_campana": "KORTEX", "grupo_admin": "kb-admin"}
OBLIGATORIOS = ("api_url", "cognito_pool_id", "cognito_client_id", "cognito_region")
ENTORNO_SIN_NOMBRE = "predeterminado"


class ConfigIncompleta(Exception):
    """Falta configuración: el mensaje dice qué y cómo darla."""


def base() -> Path:
    """%USERPROFILE%\\.kortex: config.json, la ficha local del modo HTTP y una carpeta por entorno."""
    p = Path(os.environ.get("KORTEX_HOME") or (Path.home() / ".kortex"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def fichero_config() -> Path:
    return Path(os.environ.get("KORTEX_CONFIG") or (base() / "config.json"))


def _leer_fichero() -> dict:
    f = fichero_config()
    if not f.exists():
        return {}
    try:
        datos = json.loads(f.read_text(encoding="utf-8-sig"))
    except ValueError as e:
        raise ConfigIncompleta(f"{f} no es un JSON válido ({e}).") from None
    return datos if isinstance(datos, dict) else {}


def _seguro(nombre: str) -> str:
    """El nombre del entorno se usa como carpeta: solo letras, cifras, guion y subrayado."""
    limpio = "".join(c for c in nombre if c.isalnum() or c in "-_")
    if not limpio or limpio != nombre:
        raise ConfigIncompleta(f"Nombre de entorno no válido: «{nombre}» (usa letras, cifras, «-» o «_»).")
    return limpio


def _entorno_y_fuente(datos: dict) -> tuple[str, dict]:
    nombre = (os.environ.get("KORTEX_ENTORNO") or str(datos.get("entorno") or "")).strip()
    entornos = datos.get("entornos")
    if isinstance(entornos, dict) and entornos:
        if not nombre and len(entornos) == 1:
            nombre = next(iter(entornos))
        if not nombre:
            raise ConfigIncompleta(f"{fichero_config()} tiene varios entornos ({', '.join(entornos)}): elige uno con "
                                   "«kortex-mcp --entorno <nombre>», KORTEX_ENTORNO o la clave «entorno» del fichero.")
        if nombre not in entornos:
            raise ConfigIncompleta(f"El entorno «{nombre}» no está en {fichero_config()} (hay: {', '.join(entornos)}).")
        fuente = entornos[nombre] if isinstance(entornos[nombre], dict) else {}
        return _seguro(nombre), fuente
    return _seguro(nombre or ENTORNO_SIN_NOMBRE), {k: v for k, v in datos.items() if k in CAMPOS}


@dataclass(frozen=True)
class Config:
    entorno: str
    api_url: str
    region: str
    pool: str
    cliente: str
    knowledge_prefix: str
    kb_prefix: str
    campana: str
    grupos_admin: tuple

    @staticmethod
    def _unir(base_url: str, prefijo: str) -> str:
        return base_url.rstrip("/") + "/" + prefijo.strip("/") if prefijo.strip("/") else base_url.rstrip("/")

    @property
    def knowledge_url(self) -> str:
        return self._unir(self.api_url, self.knowledge_prefix)

    @property
    def kb_url(self) -> str:
        return self._unir(self.api_url, self.kb_prefix)

    def faltan(self) -> list:
        """Variables que faltan para el login y las herramientas de conocimiento."""
        valores = {"api_url": self.api_url, "cognito_pool_id": self.pool, "cognito_client_id": self.cliente, "cognito_region": self.region}
        return [CAMPOS[k] for k in OBLIGATORIOS if not valores[k]]

    def exigir(self) -> "Config":
        f = self.faltan()
        if f:
            raise ConfigIncompleta(
                f"Falta configuración de Kortex para el entorno «{self.entorno}»: {', '.join(f)}. Pide al equipo de Kortex el "
                f"config.json y déjalo en {fichero_config()}, o define esas variables de entorno.")
        return self


def cargar() -> Config:
    datos = _leer_fichero()
    nombre, fuente = _entorno_y_fuente(datos)
    v = {}
    for campo, variable in CAMPOS.items():
        v[campo] = str(os.environ.get(variable) or fuente.get(campo) or POR_DEFECTO.get(campo) or "").strip()
    if not v["cognito_region"] and "_" in v["cognito_pool_id"]:
        v["cognito_region"] = v["cognito_pool_id"].split("_", 1)[0]
    return Config(entorno=nombre, api_url=v["api_url"].rstrip("/"), region=v["cognito_region"], pool=v["cognito_pool_id"],
                  cliente=v["cognito_client_id"], knowledge_prefix=v["knowledge_prefix"], kb_prefix=v["kb_prefix"],
                  campana=v["kb_campana"], grupos_admin=tuple(g.strip() for g in v["grupo_admin"].split(",") if g.strip()))


def api_url_configurada() -> str:
    """Base de la API (variable KORTEX_API_URL o config.json); vacía si no hay ninguna. La usan también list_collections/retrieve."""
    try:
        return cargar().api_url
    except ConfigIncompleta:
        return (os.environ.get("KORTEX_API_URL") or "").rstrip("/")


def carpeta() -> Path:
    """Datos locales del entorno activo: sesión cifrada, caché de la KB, fotos para «lo nuevo desde» y fichas de revisión."""
    p = base() / cargar().entorno
    p.mkdir(parents=True, exist_ok=True)
    return p


def descargas() -> Path:
    p = Path(os.environ.get("KORTEX_DESCARGAS") or (Path.home() / "Downloads" / "kortex"))
    p.mkdir(parents=True, exist_ok=True)
    return p
