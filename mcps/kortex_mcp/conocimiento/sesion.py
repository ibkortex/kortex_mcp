"""Sesión con cada web (Cognito) y llamadas HTTP con reintentos, renovación del token y errores en español.

23/11/2026: los dos pools tienen MFA OBLIGATORIO (aplicación de autenticación, TOTP). Las dos cuentas (ingesta y KB) entran igual:
SRP (USER_SRP_AUTH) + el código de 6 dígitos (reto SOFTWARE_TOKEN_MFA). La API de la KB acepta el ámbito de SRP
(«aws.cognito.signin.user.admin», kbweb/iac/api.tf), así que ya no se raspa la pantalla de login de Cognito.
Con MFA no se puede volver a entrar en silencio: la contraseña NO se guarda (solo el usuario) y la sesión vive del token de refresco
(30 días desde el login). Al caducar, la herramienta pide repetir el login (`py mcp\\kortex.py login`) con un código nuevo.
Si la cuenta aún no tiene dado de alta el TOTP (reto MFA_SETUP), se pide entrar antes en la web, donde Cognito enseña el código QR.
Los tokens se guardan cifrados con DPAPI en %USERPROFILE%\\.kortex\\sesion_<perfil>_<cuenta>.json; nunca se imprimen."""
import base64
import json
import re
import time

import requests

from . import config, credenciales

REFRESCO_S = 30 * 86400               # 24/11/2026: token de refresco del cliente del MCP, 30 días (iac/identity.tf «mcp»)
TIMEOUT = (10, 70)                    # conexión, lectura (la API Gateway corta a los 30 s; la KB puede tardar en la primera lectura)
REINTENTOS = 3
ESPERA = (0.6, 1.8, 4.0)


class ErrorKortex(Exception):
    """Error con un mensaje en español listo para enseñar."""
    def __init__(self, mensaje, estado=None, codigo=None):
        super().__init__(mensaje)
        self.estado, self.codigo = estado, codigo


class SesionCaducada(ErrorKortex):
    pass


class RutaNoDisponible(ErrorKortex):
    pass


ORDEN_LOGIN = "py mcp\\kortex.py login"          # desde la carpeta del MCP (la raíz del ZIP o el repositorio)
CODIGO = re.compile(r"\d{6}")
ALTA_TOTP = ("Tu cuenta todavía no tiene dada de alta la aplicación de autenticación. Entra primero en la web con este usuario: "
             "Cognito te enseñará un código QR para darla de alta. Después repite el login aquí.")


def _orden_login(perfil=None):
    return f"{ORDEN_LOGIN} (con el código de 6 dígitos de tu aplicación de autenticación)"


def caducidad(jwt: str) -> int:
    try:
        cuerpo = jwt.split(".")[1]
        return int(json.loads(base64.urlsafe_b64decode(cuerpo + "=" * (-len(cuerpo) % 4))).get("exp") or 0)
    except Exception:  # noqa: BLE001
        return 0


def reclamaciones(jwt: str) -> dict:
    try:
        cuerpo = jwt.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(cuerpo + "=" * (-len(cuerpo) % 4)))
    except Exception:  # noqa: BLE001
        return {}


# ====================================================================== cómo se obtienen los tokens
class Cognito:
    """SRP + TOTP contra el pool de cada web. Se sustituye en las pruebas por una falsa."""

    def __init__(self, idp=None):
        if idp is not None:
            self._idp = lambda: idp

    def _idp(self):
        import boto3
        from botocore import UNSIGNED
        from botocore.config import Config
        return boto3.client("cognito-idp", region_name=config.REGION, config=Config(signature_version=UNSIGNED, retries={"max_attempts": 3}))

    def srp(self, usuario, clave, cfg, pedir_codigo=None) -> dict:
        """pedir_codigo(): devuelve el código de 6 dígitos; se llama solo si Cognito lo pide (siempre, con MFA obligatorio)."""
        from pycognito.aws_srp import AWSSRP, ForceChangePasswordException
        from pycognito.exceptions import SMSMFAChallengeException, SoftwareTokenMFAChallengeException
        idp = self._idp()
        try:
            r = AWSSRP(username=usuario, password=clave, pool_id=cfg["pool"], client_id=cfg["cliente"], client=idp).authenticate_user()
        except ForceChangePasswordException:
            raise ErrorKortex("La cuenta tiene que cambiar la contraseña temporal: entra una vez en la web (allí también das de alta la "
                              "aplicación de autenticación) y vuelve a hacer login aquí.") from None
        except SoftwareTokenMFAChallengeException as e:
            r = self._codigo_totp(idp, usuario, cfg, e.get_tokens(), pedir_codigo)
        except SMSMFAChallengeException:
            raise ErrorKortex("Cognito pide un código por SMS, que no se usa en Kortex: avisa al equipo de Kortex.") from None
        except Exception as e:  # noqa: BLE001
            raise ErrorKortex(_motivo_cognito(e)) from None
        if r.get("ChallengeName") == "MFA_SETUP":
            raise ErrorKortex(ALTA_TOTP)
        a = r.get("AuthenticationResult") or {}
        if not a.get("AccessToken"):
            raise ErrorKortex(f"Cognito pide un paso extra ({r.get('ChallengeName')}); entra una vez en la web y vuelve a intentarlo.")
        return {"acceso": a["AccessToken"], "id": a.get("IdToken"), "refresco": a.get("RefreshToken"), "via": "srp"}

    @staticmethod
    def _codigo_totp(idp, usuario, cfg, reto, pedir_codigo) -> dict:
        if pedir_codigo is None:
            raise ErrorKortex("Cognito pide el código de tu aplicación de autenticación: haz el login en tu terminal. Ejecuta: " + ORDEN_LOGIN)
        codigo = str(pedir_codigo() or "").strip().replace(" ", "")
        if not CODIGO.fullmatch(codigo):
            raise ErrorKortex("El código son 6 dígitos de tu aplicación de autenticación.")
        nombre = (reto.get("ChallengeParameters") or {}).get("USER_ID_FOR_SRP") or usuario
        try:
            return idp.respond_to_auth_challenge(ClientId=cfg["cliente"], ChallengeName="SOFTWARE_TOKEN_MFA", Session=reto.get("Session"),
                                                 ChallengeResponses={"USERNAME": nombre, "SOFTWARE_TOKEN_MFA_CODE": codigo})
        except Exception as e:  # noqa: BLE001
            cod = getattr(e, "response", {}).get("Error", {}).get("Code") if hasattr(e, "response") else type(e).__name__
            if cod in ("CodeMismatchException", "ExpiredCodeException", "NotAuthorizedException"):
                raise ErrorKortex("Código incorrecto o caducado: espera al siguiente código de la aplicación y repite el login.") from None
            raise ErrorKortex(_motivo_cognito(e)) from None

    def refrescar_srp(self, refresco, cfg) -> dict:
        try:
            a = self._idp().initiate_auth(AuthFlow="REFRESH_TOKEN_AUTH", ClientId=cfg["cliente"],
                                          AuthParameters={"REFRESH_TOKEN": refresco})["AuthenticationResult"]
        except Exception as e:  # noqa: BLE001
            raise SesionCaducada(_motivo_cognito(e)) from None
        return {"acceso": a["AccessToken"], "id": a.get("IdToken"), "refresco": a.get("RefreshToken") or refresco, "via": "srp"}


def _motivo_cognito(e) -> str:
    cod = getattr(e, "response", {}).get("Error", {}).get("Code") if hasattr(e, "response") else type(e).__name__
    return {"NotAuthorizedException": "Usuario o contraseña incorrectos, o el token de refresco ya no vale.",
            "UserNotFoundException": "Usuario o contraseña incorrectos.",
            "PasswordResetRequiredException": "La cuenta tiene que restablecer la contraseña desde la web.",
            "TooManyRequestsException": "Cognito pide esperar: demasiados intentos seguidos."}.get(cod, f"Cognito ha respondido con un error ({cod}).")


# ====================================================================== sesión de una cuenta (ingesta o kb) dentro de un perfil
class Sesion:
    def __init__(self, perfil: str, cuenta: str, *, http=None, cognito=None, cifrar=None, descifrar=None, reloj=time.time, dormir=time.sleep):
        if cuenta not in ("ingesta", "kb"):
            raise ValueError(cuenta)
        self.perfil, self.cuenta = perfil, cuenta
        self.cfg = config.INGESTA if cuenta == "ingesta" else config.KB
        self.http = http or requests.Session()
        self.cognito = cognito or Cognito()
        self.cifrar = cifrar or credenciales.dpapi_cifrar
        self.descifrar = descifrar or credenciales.dpapi_descifrar
        self.reloj, self.dormir = reloj, dormir
        self._t = None

    # ---------------------------------------------------------------- tokens
    @property
    def _fichero(self):
        if config.LOGIN_UNICO and self.cuenta == "kb":                # 24/11/2026: la KB usa la MISMA sesión que la ingesta
            return config.carpeta() / f"sesion_{credenciales.perfil_de_cuenta('admin', 'ingesta')}_ingesta.json"
        return config.carpeta() / f"sesion_{self.perfil}_{self.cuenta}.json"

    def entrar(self, usuario: str, clave: str, pedir_codigo=None) -> dict:
        t = self.cognito.srp(usuario, clave, self.cfg, pedir_codigo)
        t["entrada"] = int(self.reloj())                          # el token de refresco dura 30 días desde aquí
        self._guardar(t)
        return {"usuario": usuario, "caduca_en": caducidad(t["acceso"]), "renovable_hasta": t["entrada"] + REFRESCO_S}

    def _guardar(self, t):
        self._t = t
        try:
            self._fichero.write_bytes(self.cifrar(json.dumps(t).encode("utf-8")))
        except credenciales.SinCredenciales:
            pass                                                  # fuera de Windows: solo en memoria

    def _cargar(self):
        if self._t is None and self._fichero.exists():
            try:
                self._t = json.loads(self.descifrar(self._fichero.read_bytes()).decode("utf-8"))
            except Exception:  # noqa: BLE001 — otra cuenta de Windows o fichero dañado: hay que repetir el login
                self._t = None
        return self._t

    def token(self, forzar=False) -> str:
        t = self._cargar()
        if t and not forzar and caducidad(t["acceso"]) - 60 > self.reloj():
            return t["acceso"]
        if t and t.get("refresco") and t.get("via") == "srp":         # las sesiones antiguas del login gestionado ya no se renuevan
            try:
                n = self.cognito.refrescar_srp(t["refresco"], self.cfg)
                n["entrada"] = t.get("entrada")
                self._guardar(n)
                return n["acceso"]
            except ErrorKortex:
                pass
        raise SesionCaducada(f"La sesión de {self._nombre()} ha caducado o no existe (dura 30 días desde el login). "
                             f"Ejecuta en tu terminal: {_orden_login()}")

    def usuario(self) -> str | None:
        t = self._cargar() or {}
        c = reclamaciones(t.get("id") or "") or reclamaciones(t.get("acceso") or "")
        return c.get("email") or c.get("cognito:username") or c.get("username") or credenciales.usuario(self.perfil, self.cuenta)

    # ---------------------------------------------------------------- HTTP
    def url(self, ruta: str) -> str:
        return self.cfg["api"].rstrip("/") + "/" + ruta.lstrip("/")

    def pedir(self, metodo: str, ruta: str, *, cuerpo=None, params=None, timeout=TIMEOUT, crudo=False, ruta_nueva=False):
        """JSON de la respuesta (o el objeto Response si crudo). ruta_nueva: una 404/403 de la pasarela significa que la ruta aún no
        está desplegada (rutas del fork A) y se dice así."""
        metodo = metodo.upper()
        renovado = False
        ultimo = None
        for intento in range(REINTENTOS):
            cab = {"Authorization": "Bearer " + self.token(), "Accept": "application/json"}
            try:
                r = self.http.request(metodo, self.url(ruta), json=cuerpo, params=params, headers=cab, timeout=timeout)
            except requests.Timeout:
                ultimo = ErrorKortex(f"La API de {self._nombre()} no ha respondido a tiempo.")
                if metodo != "GET":
                    raise ultimo from None                        # un POST puede haberse ejecutado: no se repite a ciegas
                self.dormir(ESPERA[intento])
                continue
            except requests.ConnectionError:
                ultimo = ErrorKortex(f"No hay conexión con la API de {self._nombre()}.")
                self.dormir(ESPERA[intento])
                continue
            if r.status_code == 401 and not renovado:
                renovado = True
                self.token(forzar=True)
                continue
            if r.status_code in (429, 503) or (metodo == "GET" and r.status_code in (502, 504)):
                ultimo = ErrorKortex(f"La API de {self._nombre()} está ocupada ({r.status_code}); vuelve a intentarlo en un momento.", r.status_code)
                self.dormir(ESPERA[intento])
                continue
            if r.status_code >= 400:
                raise self._error(r, ruta, ruta_nueva)
            if crudo:
                return r
            if not r.content:
                return {}
            try:
                return r.json()
            except ValueError:
                return {"texto": r.text}
        raise ultimo or ErrorKortex(f"La API de {self._nombre()} no ha respondido.")

    def _nombre(self):
        return "la ingesta" if self.cuenta == "ingesta" else "la KB"

    def _error(self, r, ruta, ruta_nueva):
        try:
            j = r.json()
        except ValueError:
            j = {}
        msg, cod = None, None
        if isinstance(j, dict):
            e = j.get("error")
            if isinstance(e, dict):
                msg, cod = e.get("message") or e.get("mensaje"), e.get("code") or e.get("codigo")
            elif isinstance(e, str):
                msg = e
            msg = msg or j.get("mensaje") or j.get("detail")
            cod = cod or j.get("code")
            pasarela = j.get("message") if set(j) <= {"message"} else None
        else:
            pasarela = None
        if r.status_code == 401:
            return SesionCaducada(f"La API de {self._nombre()} no acepta la sesión. Ejecuta en tu terminal: {_orden_login()}", 401)
        if ruta_nueva and (r.status_code == 404 and (pasarela or not msg) or r.status_code == 403 and pasarela):
            return RutaNoDisponible(f"La ruta {ruta.split('?')[0]} todavía no está desplegada en la API de {self._nombre()} "
                                    "(la añade el otro trabajo en curso). Cuando esté publicada, esta herramienta funcionará sin tocar nada.",
                                    r.status_code)
        if r.status_code == 403:
            return ErrorKortex(msg or f"Tu usuario no tiene permiso para esto en {self._nombre()}.", 403, cod)
        if r.status_code == 404:
            return ErrorKortex(msg or "No existe o no lo puedes ver.", 404, cod)
        if r.status_code == 413:
            return ErrorKortex(msg or "La petición es demasiado grande.", 413, cod)
        return ErrorKortex(f"{self._nombre().capitalize()} ha respondido {r.status_code}: {msg or pasarela or 'error sin detalle'}"
                           + (f" ({cod})" if cod else ""), r.status_code, cod)
