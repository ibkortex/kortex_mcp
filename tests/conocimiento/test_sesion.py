import sys

import pytest
import requests
from conftest import Resp, cifrar

from kortex_mcp import config, credenciales
from kortex_mcp.sesion import Cognito, ErrorKortex, RutaNoDisponible, SesionCaducada


# ---------------------------------------------------------------------- cuentas guardadas (sin contraseña: MFA, 23/11/2026)
def test_solo_se_guarda_el_usuario(home, monkeypatch):
    monkeypatch.setattr(config, "LOGIN_UNICO", False)                 # modo anterior: admin = tiene login propio de la KB
    credenciales.guardar("consulta", "ingesta", "persona1@ejemplo.test", "S3creta!", cifrar=cifrar)
    bruto = (home / "credenciales_consulta.json").read_text(encoding="utf-8")
    assert "S3creta!" not in bruto and "clave" not in bruto and "persona1@ejemplo.test" in bruto
    assert credenciales.cuentas("consulta") == ["ingesta"] and credenciales.usuario("consulta", "ingesta") == "persona1@ejemplo.test"
    assert credenciales.perfil_efectivo() == "consulta"
    credenciales.guardar("admin", "kb", "persona2@ejemplo.test")
    assert credenciales.perfil_efectivo() == "admin"


def test_se_borran_las_claves_de_versiones_anteriores(home):
    import json
    config.carpeta()
    (home / "credenciales_admin.json").write_text(json.dumps({"kb": {"usuario": "admin", "clave_dpapi": "QUJD"},
                                                              "ingesta": {"usuario": "x@ejemplo.test", "clave_dpapi": "REVG"}}), encoding="utf-8")
    assert credenciales.olvidar_claves() == 2
    assert "clave_dpapi" not in (home / "credenciales_admin.json").read_text(encoding="utf-8")
    assert credenciales.cuentas("admin") == ["ingesta", "kb"] and credenciales.olvidar_claves() == 0


def test_logout_borra_cuentas_y_sesiones(sesion, home):
    s, _, _ = sesion("ingesta")
    assert list(home.glob("sesion_consulta_*.json"))
    assert credenciales.borrar("consulta")
    assert not list(home.glob("*consulta*"))


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI solo en Windows")
def test_dpapi_real_ida_y_vuelta():
    c = credenciales.dpapi_cifrar("clave ñ €".encode())
    assert b"clave" not in c
    assert credenciales.dpapi_descifrar(c).decode() == "clave ñ €"


# ---------------------------------------------------------------------- tokens
def test_token_se_reutiliza_y_la_sesion_va_cifrada(sesion, home):
    s, _, cog = sesion("ingesta")
    t = s.token()
    assert s.token() == t and len(cog.logins) == 1 and not cog.refrescos
    assert b"acceso" not in (home / "sesion_consulta_ingesta.json").read_bytes()


def test_token_caducado_se_refresca_y_conserva_la_hora_de_entrada(sesion, reloj):
    s, _, cog = sesion("ingesta")
    entrada = s._t["entrada"]
    reloj.t += 3600
    s.token()
    assert cog.refrescos == ["R-1"] and len(cog.logins) == 1 and s._t["entrada"] == entrada


def test_refresco_caducado_pide_repetir_el_login_sin_reentrar_solo(sesion, reloj):
    s, _, cog = sesion("ingesta")
    cog.refresco_falla = True
    reloj.t += 9 * 3600
    with pytest.raises(SesionCaducada, match=r"kortex\.py login .*6 dígitos"):
        s.token()
    assert [x[0] for x in cog.logins] == ["srp"]                  # no vuelve a entrar con nada guardado


def test_sin_sesion_mensaje_en_espanol(sesion, home):
    s, _, _ = sesion("ingesta", login=False)
    with pytest.raises(SesionCaducada, match=r"ha caducado o no existe .*kortex\.py login"):
        s.token()


def test_sesion_antigua_del_login_gestionado_no_se_renueva(sesion, reloj):
    s, _, cog = sesion("kb", perfil="admin")
    s._t = {**s._t, "via": "gestionado"}
    reloj.t += 3600
    with pytest.raises(SesionCaducada):
        s.token()
    assert not cog.refrescos


def test_kb_entra_por_srp(sesion):
    s, _, cog = sesion("kb", perfil="admin")
    assert cog.logins == [("srp", "admin")]


# ---------------------------------------------------------------------- SRP + TOTP con un Cognito (boto3) falso
class _Error(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class _IdpFalso:
    """Lo justo para AWSSRP: el reto PASSWORD_VERIFIER y luego lo que se le diga (TOTP, alta del TOTP o tokens)."""

    def __init__(self, tras_clave, codigo_bueno="123456"):
        self.tras_clave, self.codigo_bueno, self.respuestas = tras_clave, codigo_bueno, []

    def initiate_auth(self, **k):
        return {"ChallengeName": "PASSWORD_VERIFIER", "ChallengeParameters": {}}

    def respond_to_auth_challenge(self, **k):
        self.respuestas.append(k)
        if k["ChallengeName"] == "PASSWORD_VERIFIER":
            return self.tras_clave
        if k["ChallengeResponses"]["SOFTWARE_TOKEN_MFA_CODE"] != self.codigo_bueno:
            raise _Error("CodeMismatchException")
        return {"AuthenticationResult": {"AccessToken": "A", "IdToken": "I", "RefreshToken": "R"}}


@pytest.fixture
def srp_sin_cripto(monkeypatch):
    import pycognito.aws_srp as m
    monkeypatch.setattr(m.AWSSRP, "get_auth_params", lambda self: {"USERNAME": self.username, "SRP_A": "x"})
    monkeypatch.setattr(m.AWSSRP, "process_challenge", lambda self, params, req: {"USERNAME": self.username})


RETO_TOTP = {"ChallengeName": "SOFTWARE_TOKEN_MFA", "Session": "S1", "ChallengeParameters": {"USER_ID_FOR_SRP": "uuid-1"}}


def test_srp_con_codigo_totp(srp_sin_cripto):
    idp = _IdpFalso(RETO_TOTP)
    t = Cognito(idp=idp).srp("persona2@ejemplo.test", "pw", config.INGESTA, lambda: "123 456")
    assert t == {"acceso": "A", "id": "I", "refresco": "R", "via": "srp"}
    r = idp.respuestas[-1]
    assert r["ChallengeName"] == "SOFTWARE_TOKEN_MFA" and r["Session"] == "S1"
    assert r["ChallengeResponses"] == {"USERNAME": "uuid-1", "SOFTWARE_TOKEN_MFA_CODE": "123456"}


def test_srp_codigo_incorrecto(srp_sin_cripto):
    with pytest.raises(ErrorKortex, match="Código incorrecto o caducado"):
        Cognito(idp=_IdpFalso(RETO_TOTP)).srp("a@ejemplo.test", "pw", config.KB, lambda: "000000")


def test_srp_codigo_mal_formado_no_llega_a_cognito(srp_sin_cripto):
    idp = _IdpFalso(RETO_TOTP)
    with pytest.raises(ErrorKortex, match="6 dígitos"):
        Cognito(idp=idp).srp("a@ejemplo.test", "pw", config.KB, lambda: "12ab")
    assert [r["ChallengeName"] for r in idp.respuestas] == ["PASSWORD_VERIFIER"]


def test_srp_sin_terminal_no_puede_pedir_el_codigo(srp_sin_cripto):
    with pytest.raises(ErrorKortex, match="haz el login en tu terminal"):
        Cognito(idp=_IdpFalso(RETO_TOTP)).srp("a@ejemplo.test", "pw", config.KB)


def test_srp_sin_totp_dado_de_alta_manda_a_la_web(srp_sin_cripto):
    with pytest.raises(ErrorKortex, match="Entra primero en la web"):
        Cognito(idp=_IdpFalso({"ChallengeName": "MFA_SETUP", "Session": "S"})).srp("a@ejemplo.test", "pw", config.INGESTA, lambda: "123456")


def test_srp_contrasena_temporal_manda_a_la_web(srp_sin_cripto):
    with pytest.raises(ErrorKortex, match="contraseña temporal"):
        Cognito(idp=_IdpFalso({"ChallengeName": "NEW_PASSWORD_REQUIRED", "Session": "S"})).srp("a@ejemplo.test", "pw", config.INGESTA)


# ---------------------------------------------------------------------- HTTP
def test_401_renueva_y_repite(sesion):
    s, http, cog = sesion("ingesta", rutas={("GET", "/me"): [Resp(401, {"message": "Unauthorized"}), Resp(200, {"ok": 1})]})
    assert s.pedir("GET", "me") == {"ok": 1}
    assert len(cog.refrescos) == 1 and len(http.llamadas) == 2
    assert http.llamadas[0]["headers"]["Authorization"].startswith("Bearer ")


def test_503_reintenta_get(sesion):
    s, http, _ = sesion("ingesta", rutas={("GET", "/me"): [Resp(503, {}), Resp(200, {"ok": 1})]})
    assert s.pedir("GET", "me") == {"ok": 1}


def test_post_con_timeout_no_se_repite(sesion):
    def lenta(_):
        raise requests.Timeout()
    s, http, _ = sesion("ingesta", rutas={("POST", "/chat"): lenta})
    with pytest.raises(ErrorKortex, match="no ha respondido a tiempo"):
        s.pedir("POST", "chat", cuerpo={})
    assert len(http.llamadas) == 1


def test_ruta_nueva_no_desplegada(sesion):
    s, _, _ = sesion("ingesta")
    with pytest.raises(RutaNoDisponible, match="todavía no está desplegada"):
        s.pedir("POST", "consulta", cuerpo={}, ruta_nueva=True)


def test_404_de_la_lambda_no_es_ruta_ausente(sesion):
    s, _, _ = sesion("ingesta", rutas={("GET", "/texto"): Resp(404, {"error": {"code": "NOT_FOUND", "message": "No existe o no lo puedes ver"}})})
    with pytest.raises(ErrorKortex) as e:
        s.pedir("GET", "documents/x/texto", ruta_nueva=True)
    assert not isinstance(e.value, RutaNoDisponible) and "No existe" in str(e.value)


def test_error_no_filtra_el_token(sesion):
    s, http, _ = sesion("ingesta", rutas={("GET", "/me"): Resp(500, {"error": "fallo"})})
    with pytest.raises(ErrorKortex) as e:
        s.pedir("GET", "me")
    assert http.llamadas[0]["headers"]["Authorization"][7:] not in str(e.value)
