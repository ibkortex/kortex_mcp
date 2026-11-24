# Origen del código de conocimiento

Copia literal del MCP local de la PoC de Kortex (repositorio privado de la PoC, commit `e653f67`, carpeta `mcp/`, y
`kbweb/web/ficha.js`, que el MCP lee para generar las fichas HTML igual que la web de la KB).

La copia es literal salvo una limpieza mínima, obligatoria en un repositorio público: identificadores del entorno de la PoC
(URL de la API, dominios de las webs, pools y clientes de Cognito), una ruta de la máquina del autor, el nombre de la
organización, nombres de personas y nombres de sistemas y empresas del cliente usados como ejemplo o como datos de prueba.
Se sustituyen por marcadores o nombres ficticios coherentes (p. ej. un sistema de ejemplo pasa a llamarse `SIGMA`); la lógica no
cambia. Los commits siguientes adaptan el código al MCP oficial (configuración por entorno, login contra el pool oficial,
rutas `/knowledge/v1` y `/kb/v1`, registro condicional de herramientas, transporte stdio y HTTP local).

| Origen (`e653f67`) | Destino | sha256 origen | sha256 destino | Limpieza |
|---|---|---|---|---|
| `mcp/kortex_mcp/__init__.py` | `mcps/kortex_mcp/conocimiento/__init__.py` | `c3fdfe20499f45eff2756dce2f1ebfcc10d26d50e9df78f81cdbe622c371e011` | `= origen` | — |
| `mcp/kortex_mcp/__main__.py` | `mcps/kortex_mcp/conocimiento/__main__.py` | `611f0f7f0a49f1880010306c72b031b41823a111d204b24dd58bb66e35dcff0b` | `= origen` | — |
| `mcp/kortex_mcp/config.py` | `mcps/kortex_mcp/conocimiento/config.py` | `d5049ee9c6686f2867bcd0d09ff2a41e65d70c34545ce5c627c10a3d396600d9` | `1a2dc8bded5b245f273584c586c967373835ecc7a3aecc80d1c15d9d0047ac98` | entorno (9) |
| `mcp/kortex_mcp/credenciales.py` | `mcps/kortex_mcp/conocimiento/credenciales.py` | `789ddf01604066555829c5010e879e486218f8922e3a6743026ce9057ef216fd` | `= origen` | — |
| `mcp/kortex_mcp/ficha.py` | `mcps/kortex_mcp/conocimiento/ficha.py` | `394dd93829cf87aac1737da1a440c2015b9dec7ef020f96f0b486fcb0115e6f4` | `3d5bc7ffb61ab25111193ec0635b789238c16c2ca666bcc214e43667fa732f53` | personas (1) |
| `mcp/kortex_mcp/fichas_revision.py` | `mcps/kortex_mcp/conocimiento/fichas_revision.py` | `e33c92854b026da5f007453fed78898800d0e9fb58e2cb92bf318d27a75f3945` | `014cb0a9d3f8f0203d5ed4b6fc88a35a2560a24ff33b70819f8debfc636f79b2` | cliente (4) |
| `mcp/kortex_mcp/http_local.py` | `mcps/kortex_mcp/conocimiento/http_local.py` | `ef00e7c96ab60f8532f9101b66d1198d424dedec795715bff81810708fcf341e` | `d1ca728ad965f1c0a883989647eb84c153bea18520fad057590b1d37618155eb` | organización (1) |
| `mcp/kortex_mcp/ingesta.py` | `mcps/kortex_mcp/conocimiento/ingesta.py` | `be4a3b1228da89d675b36699ffc2094faf29c482f03408a3a2e0e8fdd38efc01` | `= origen` | — |
| `mcp/kortex_mcp/kb.py` | `mcps/kortex_mcp/conocimiento/kb.py` | `0050e9ab002967b4f609d80f668fff43334ae5d37e3c96981ee7050f6ad11b97` | `= origen` | — |
| `mcp/kortex_mcp/servidor.py` | `mcps/kortex_mcp/conocimiento/servidor.py` | `a2e419d89883205069b0bd692de5f2853f269a11ff5ff3870daf4bc75dc8c229` | `65a97f13dfa620306be46e6ba3cf9c9790bfb6e78e56624a0b01e8bf8a47921f` | cliente (2), personas (1) |
| `mcp/kortex_mcp/sesion.py` | `mcps/kortex_mcp/conocimiento/sesion.py` | `6ce44f4097c3d7f78920d96067d36ef48397e0eae5d489ac3e0ec37c92ccd63b` | `= origen` | — |
| `kbweb/web/ficha.js` | `mcps/kortex_mcp/conocimiento/recursos/ficha.js` | `c3326dd7815e4bdedfc887fe5bfab7b9196918bf7fb2626d0060c75973e39a9e` | `= origen` | — |
| `mcp/tests/conftest.py` | `tests/conocimiento/conftest.py` | `f5323ac527606d31d1d3c435a43af61433865bcf245138ae4c92f938aea3c833` | `= origen` | — |
| `mcp/tests/datos_fichas.py` | `tests/conocimiento/datos_fichas.py` | `540ee9b08d1201fa13691ffab30ffe494eaf0623436fa2094e9a03f4ade428bc` | `36c6c505aff4a6c0bb0c9eab02125ecaf667d2f248c72b3aa434d23a52a82ed1` | cliente (33) |
| `mcp/tests/ficha_node.mjs` | `tests/conocimiento/ficha_node.mjs` | `616d33cdc423b35b70fda6871c988b0c879fb5e5d69e2a8ed1813a0179f5df80` | `= origen` | — |
| `mcp/tests/test_ficha.py` | `tests/conocimiento/test_ficha.py` | `80d49ff0bd5d090c6492f95f491d29941662f548ef179bc08f201da121318a73` | `f36925ea4be4b5ab11dfaffb81ba917882e31ff36dfd594e7404c22f61a9b0c7` | cliente (2), personas (2), ruta local (1) |
| `mcp/tests/test_fichas_html_e2e.py` | `tests/conocimiento/test_fichas_html_e2e.py` | `0fe828baafc1afc2d1391606ab2b51a5d57397834802bd61f03379d613769e5b` | `143d8bc91999d8378a9b20c0904ad9b0bbaa08c8e6bfefb49e18962f18fc935d` | cliente (31) |
| `mcp/tests/test_fichas_revision.py` | `tests/conocimiento/test_fichas_revision.py` | `b56966b8a54d5687200a396868828795f8007ceeb21ec15932022095b5b157c5` | `16106e6a605f2720f7acf43d29d70eded8faa26fe2c305bd540dd603cf97be0b` | cliente (106), personas (5) |
| `mcp/tests/test_http_local.py` | `tests/conocimiento/test_http_local.py` | `2171d53864c67dd96797ca62c042d4100aea79f0ef63dfa648f9b872326532d0` | `a4dd15671336f7e5e06c29b0910a98e0a32c09ac878f721af8a258ca4fd8d9ba` | organización (1) |
| `mcp/tests/test_ingesta.py` | `tests/conocimiento/test_ingesta.py` | `4b422c1bd7bc6ba17a43056319e049ad094fde7af9da5039770633b3a600d2ed` | `7cf68a99cd38e58807fd417222270056c050199a3c0de63708cfc74b554e1a09` | cliente (7) |
| `mcp/tests/test_kb.py` | `tests/conocimiento/test_kb.py` | `e724092e8878c21126460926a17d1ca6974f6ec8d01f17f7f3ebc09e8e0f0088` | `2bcee141029f789800f5a6f3d5df550ab871483dad230ed41e10d2d09ea933df` | cliente (16) |
| `mcp/tests/test_login.py` | `tests/conocimiento/test_login.py` | `23784aa19d6cbbfb8812ec46786be86561a16f96cab90547b6031cba57594ba6` | `= origen` | — |
| `mcp/tests/test_servidor.py` | `tests/conocimiento/test_servidor.py` | `507154d4601be486795b1bb0fae2e282a9f5e74584b0db90ec16bc7bcb5f48c7` | `= origen` | — |
| `mcp/tests/test_sesion.py` | `tests/conocimiento/test_sesion.py` | `2f5e489a7ddfb9fd48df81328fa5747374d51e990a030104fe9ea38d8ef708b1` | `b762a7d079c4df23acb5d0ce7702685adef0989622669a9bde9fae3ab9002b43` | personas (5) |
| `mcp/arrancar.ps1` | `distribucion/arrancar.ps1` | `f390e4c654386526ce78dd19fa3dd62cb9acd28b051045a8acdc823e32980d0e` | `= origen` | — |
| `mcp/distribucion/instalar.ps1` | `distribucion/instalar.ps1` | `6977877c70967a63b1d74b8ddf431923b085938a932bc33d0a5632cd7282b3ce` | `= origen` | — |
| `mcp/distribucion/INSTALAR_CON_CLAUDE_CODE.md` | `distribucion/INSTALAR_CON_CLAUDE_CODE.md` | `ab9933e8e1462b01e32da67e0b94d25eae890f40d13df4a47f23245a98df1c31` | `4de9d3cbfe985684831bd292ce0e0aa4a6b625dbe9758ce53026da65fe6cc192` | organización (1) |

No se importan:

- `mcp/README.md`: su contenido útil pasa al README del repositorio (adaptado); nombra la PoC y su entorno.
- `mcp/kortex.py`: lanzador de la PoC; lo sustituye el script `kortex-mcp` del pyproject.
- `mcp/requirements.txt`: las dependencias van en pyproject.toml / uv.lock.
- `mcp/requirements-fijas.txt`: ídem.
