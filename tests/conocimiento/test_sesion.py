import json
import sys

import pytest
import requests
from conftest import API, Resp, cifrar, descifrar, jwt

from mcps.kortex_mcp.conocimiento import config, credenciales, sesion as S
from mcps.kortex_mcp.conocimiento.sesion import Cognito, ErrorKortex, RutaNoDisponible, SesionCaducada


# ---------------------------------------------------------------------- configuración por entorno, sin valores codificados
def test_sin_configuracion_no_hay_valores_por_defecto(sin_config):
    cfg = config.cargar()
    assert (cfg.api_url, cfg.pool, cfg.cliente, cfg.region) == ("", "", "", "")
    assert cfg.faltan() == ["KORTEX_API_URL", "KORTEX_COGNITO_POOL_ID", "KORTEX_COGNITO_CLIENT_ID", "KORTEX_COGNITO_REGION"]
    with pytest.raises(config.ConfigIncompleta, match="config.json"):
        cfg.exigir()


def test_variables_de_entorno_y_rutas_oficiales(home):
    cfg = config.cargar()
    assert cfg.entorno == "predeterminado" and cfg.region == "xx-region-1"          # la región sale del id del pool
    assert cfg.knowledge_url == API + "/knowledge/v1" and cfg.kb_url == API + "/kb/v1"
    assert cfg.campana == "KORTEX" and cfg.grupos_admin == ("kb-admin",) and not cfg.faltan()


def test_config_json_con_entornos_y_precedencia_de_las_variables(sin_config, monkeypatch):
    (sin_config).mkdir(parents=True, exist_ok=True)
    (sin_config / "config.json").write_text(json.dumps({"entorno": "dev", "entornos": {
        "dev": {"api_url": "https://dev.ejemplo.test/", "cognito_pool_id": "zz-1_DEV", "cognito_client_id": "c-dev"},
        "prod": {"api_url": "https://prod.ejemplo.test", "cognito_pool_id": "zz-2_PRO", "cognito_client_id": "c-pro",
                 "cognito_region": "zz-2", "kb_prefix": "/api"}}}), encoding="utf-8")
    cfg = config.cargar()
    assert (cfg.entorno, cfg.api_url, cfg.region, cfg.cliente) == ("dev", "https://dev.ejemplo.test", "zz-1", "c-dev")
    monkeypatch.setenv("KORTEX_ENTORNO", "prod")
    cfg = config.cargar()
    assert (cfg.entorno, cfg.pool, cfg.kb_url) == ("prod", "zz-2_PRO", "https://prod.ejemplo.test/api")
    monkeypatch.setenv("KORTEX_COGNITO_CLIENT_ID", "c-variable")
    assert config.cargar().cliente == "c-variable"                                    # la variable manda sobre el fichero
    assert config.carpeta() == sin_config / "prod"
    monkeypatch.setenv("KORTEX_ENTORNO", "otro")
    with pytest.raises(config.ConfigIncompleta, match="no está"):
        config.cargar()


def test_config_json_plano_y_nombre_de_entorno_seguro(sin_config, monkeypatch):
    sin_config.mkdir(parents=True, exist_ok=True)
    (sin_config / "config.json").write_text(json.dumps({"api_url": "https://x.ejemplo.test", "cognito_pool_id": "r-1_X",
                                                        "cognito_client_id": "c"}), encoding="utf-8")
    assert config.cargar().entorno == "predeterminado" and not config.cargar().faltan()
    monkeypatch.setenv("KORTEX_ENTORNO", "..\\fuera")
    with pytest.raises(config.ConfigIncompleta, match="no válido"):
        config.cargar()


# ---------------------------------------------------------------------- sesión guardada (sin contraseña: MFA)
def test_token_se_reutiliza_y_la_sesion_va_cifrada(sesion, home):
    s, _, cog = sesion("ingesta")
    t = s.token()
    assert s.token() == t and len(cog.logins) == 1 and not cog.refrescos
    bruto = (home / "predeterminado" / "sesion.dpapi").read_bytes()
    assert b"acceso" not in bruto and b"Clave-Buena-1" not in bruto


def test_la_kb_usa_la_misma_sesion_que_conocimiento(sesion, home):
    s, _, cog = sesion("ingesta")
    from mcps.kortex_mcp.conocimiento.sesion import Sesion
    k = Sesion("kb", cognito=cog, descifrar=descifrar)
    assert k._fichero == s._fichero and k.token() == s.token() and len(cog.logins) == 1


def test_urls_de_la_api_oficial(sesion):
    s, http, _ = sesion("ingesta", rutas={("POST", "/consulta"): Resp(200, {"fragmentos": []})})
    s.pedir("POST", "consulta", cuerpo={})
    assert http.llamadas[-1]["url"] == API + "/knowledge/v1/consulta"
    k, http, _ = sesion("kb", rutas={("GET", "/campanas/KORTEX/estado"): Resp(200, {})})
    k.pedir("GET", "campanas/KORTEX/estado")
    assert http.llamadas[-1]["url"] == API + "/kb/v1/campanas/KORTEX/estado"


def test_token_caducado_se_refresca_y_conserva_la_hora_de_entrada(sesion, reloj):
    s, _, cog = sesion("ingesta")
    entrada = s._t["entrada"]
    reloj.t += 3600
    s.token()
    assert cog.refrescos == ["R-1"] and len(cog.logins) == 1 and s._t["entrada"] == entrada


def test_otro_proceso_renovo_la_sesion_se_relee_sin_refrescar(sesion, reloj):
    s, _, cog = sesion("ingesta")
    reloj.t += 3600                                                   # el token en memoria caduca…
    nuevo = {**s._t, "acceso": jwt(reloj.t + 3600, username="equipo2@ejemplo.test")}
    s._fichero.write_bytes(cifrar(json.dumps(nuevo).encode()))        # …pero un login nuevo dejó otro en disco
    assert s.token() == nuevo["acceso"] and not cog.refrescos


def test_refresco_caducado_pide_repetir_el_login_sin_reentrar_solo(sesion, reloj):
    s, _, cog = sesion("ingesta")
    cog.refresco_falla = True
    reloj.t += 9 * 3600
    with pytest.raises(SesionCaducada, match=r"kortex-mcp login .*6 dígitos"):
        s.token()
    assert [x[0] for x in cog.logins] == ["srp"]                  # no vuelve a entrar con nada guardado


def test_sin_sesion_mensaje_en_espanol(sesion, home):
    s, _, _ = sesion("ingesta", login=False)
    with pytest.raises(SesionCaducada, match=r"ha caducado o no existe .*kortex-mcp login"):
        s.token()


def test_sin_configuracion_la_sesion_dice_que_falta(sin_config):
    from mcps.kortex_mcp.conocimiento.sesion import Sesion
    with pytest.raises(config.ConfigIncompleta, match="KORTEX_API_URL"):
        Sesion("ingesta")


def test_sesion_antigua_sin_srp_no_se_renueva(sesion, reloj):
    s, _, cog = sesion("kb")
    s._t = {**s._t, "via": "gestionado"}
    s._fichero.write_bytes(cifrar(json.dumps(s._t).encode()))
    reloj.t += 3600
    with pytest.raises(SesionCaducada):
        s.token()
    assert not cog.refrescos


# ---------------------------------------------------------------------- perfil por el grupo del token (sin red)
def test_perfil_actual_por_grupo(sesion, home, monkeypatch, reloj):
    monkeypatch.setattr(credenciales, "dpapi_descifrar", descifrar)
    assert S.perfil_actual(ahora=reloj.t) is None                     # sin login
    sesion("ingesta")
    assert S.perfil_actual(ahora=reloj.t) == "consulta"
    sesion("ingesta", grupos=["kb-admin"])
    assert S.perfil_actual(ahora=reloj.t) == "admin"
    assert S.perfil_actual(ahora=reloj.t + S.REFRESCO_S + 10) is None  # pasados los 30 días ya no hay sesión
    monkeypatch.setenv("KORTEX_GRUPO_ADMIN", "otro-grupo,admin")
    assert S.perfil_actual(ahora=reloj.t) == "consulta"


def test_perfil_actual_sin_configuracion_es_none(sin_config):
    assert S.perfil_actual() is None


def test_sesion_ilegible_es_sin_sesion(home, monkeypatch):
    config.carpeta().joinpath("sesion.dpapi").write_bytes(b"basura")
    monkeypatch.setattr(credenciales, "dpapi_descifrar", lambda b: (_ for _ in ()).throw(credenciales.SinCredenciales("x")))
    assert S.perfil_actual() is None and S.leer_tokens() is None


def test_logout_revoca_y_borra(sesion, home, monkeypatch):
    s, _, cog = sesion("ingesta")
    monkeypatch.setattr(credenciales, "dpapi_descifrar", descifrar)
    assert S.borrar_sesion(cognito=cog) is True
    assert cog.revocados == ["R-1"] and not s._fichero.exists()
    assert S.borrar_sesion(cognito=cog) is False


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI solo en Windows")
def test_dpapi_real_ida_y_vuelta():
    c = credenciales.dpapi_cifrar("clave ñ €".encode())
    assert b"clave" not in c
    assert credenciales.dpapi_descifrar(c).decode() == "clave ñ €"


# ---------------------------------------------------------------------- SRP + TOTP con un Cognito (boto3) falso
class _Error(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class _IdpFalso:
    """Lo justo para AWSSRP: el reto PASSWORD_VERIFIER y luego lo que se le diga (TOTP, alta del TOTP o tokens)."""

    def __init__(self, tras_clave, codigo_bueno="123456"):
        self.tras_clave, self.codigo_bueno, self.respuestas, self.revocados = tras_clave, codigo_bueno, [], []

    def initiate_auth(self, **k):
        return {"ChallengeName": "PASSWORD_VERIFIER", "ChallengeParameters": {}}

    def respond_to_auth_challenge(self, **k):
        self.respuestas.append(k)
        if k["ChallengeName"] == "PASSWORD_VERIFIER":
            return self.tras_clave
        if k["ChallengeResponses"]["SOFTWARE_TOKEN_MFA_CODE"] != self.codigo_bueno:
            raise _Error("CodeMismatchException")
        return {"AuthenticationResult": {"AccessToken": "A", "IdToken": "I", "RefreshToken": "R"}}

    def revoke_token(self, **k):
        self.revocados.append(k)


@pytest.fixture
def srp_sin_cripto(monkeypatch):
    import pycognito.aws_srp as m
    monkeypatch.setattr(m.AWSSRP, "get_auth_params", lambda self: {"USERNAME": self.username, "SRP_A": "x"})
    monkeypatch.setattr(m.AWSSRP, "process_challenge", lambda self, params, req: {"USERNAME": self.username})


@pytest.fixture
def cfg(home):
    return config.cargar()


RETO_TOTP = {"ChallengeName": "SOFTWARE_TOKEN_MFA", "Session": "S1", "ChallengeParameters": {"USER_ID_FOR_SRP": "uuid-1"}}


def test_srp_con_codigo_totp_contra_el_cliente_configurado(srp_sin_cripto, cfg):
    idp = _IdpFalso(RETO_TOTP)
    t = Cognito(idp=idp).srp("persona2@ejemplo.test", "pw", cfg, lambda: "123 456")
    assert t == {"acceso": "A", "id": "I", "refresco": "R", "via": "srp"}
    r = idp.respuestas[-1]
    assert r["ClientId"] == "cliente-prueba" and r["ChallengeName"] == "SOFTWARE_TOKEN_MFA" and r["Session"] == "S1"
    assert r["ChallengeResponses"] == {"USERNAME": "uuid-1", "SOFTWARE_TOKEN_MFA_CODE": "123456"}


def test_srp_codigo_incorrecto(srp_sin_cripto, cfg):
    with pytest.raises(ErrorKortex, match="Código incorrecto o caducado"):
        Cognito(idp=_IdpFalso(RETO_TOTP)).srp("a@ejemplo.test", "pw", cfg, lambda: "000000")


def test_srp_codigo_mal_formado_no_llega_a_cognito(srp_sin_cripto, cfg):
    idp = _IdpFalso(RETO_TOTP)
    with pytest.raises(ErrorKortex, match="6 dígitos"):
        Cognito(idp=idp).srp("a@ejemplo.test", "pw", cfg, lambda: "12ab")
    assert [r["ChallengeName"] for r in idp.respuestas] == ["PASSWORD_VERIFIER"]


def test_srp_sin_terminal_no_puede_pedir_el_codigo(srp_sin_cripto, cfg):
    with pytest.raises(ErrorKortex, match="haz el login en tu terminal"):
        Cognito(idp=_IdpFalso(RETO_TOTP)).srp("a@ejemplo.test", "pw", cfg)


def test_srp_sin_totp_dado_de_alta_manda_a_la_web(srp_sin_cripto, cfg):
    with pytest.raises(ErrorKortex, match="Entra primero en la web"):
        Cognito(idp=_IdpFalso({"ChallengeName": "MFA_SETUP", "Session": "S"})).srp("a@ejemplo.test", "pw", cfg, lambda: "123456")


def test_srp_contrasena_temporal_manda_a_la_web(srp_sin_cripto, cfg):
    with pytest.raises(ErrorKortex, match="contraseña temporal"):
        Cognito(idp=_IdpFalso({"ChallengeName": "NEW_PASSWORD_REQUIRED", "Session": "S"})).srp("a@ejemplo.test", "pw", cfg)


def test_revocar_usa_el_cliente_publico(cfg):
    idp = _IdpFalso({})
    Cognito(idp=idp).revocar("R", cfg)
    assert idp.revocados == [{"Token": "R", "ClientId": "cliente-prueba"}]


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


def test_ruta_no_expuesta_en_el_entorno(sesion):
    s, _, _ = sesion("ingesta")
    with pytest.raises(RutaNoDisponible, match="no está disponible .*knowledge/v1"):
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
    assert "La API de conocimiento ha respondido 500" in str(e.value)
