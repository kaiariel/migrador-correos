# Arquitectura

## Vista general

```
 Migrador.bat ──► app.py ─────────────── servidor HTTP local (127.0.0.1:47615+, token)
                    │                      ├─ sirve ui/ (index.html, app.js, estilos.css, iconos.js)
                    │                      ├─ API JSON  /api/*
                    │                      └─ eventos en vivo  /api/eventos  (Server-Sent Events)
                    │
                    ├─ importa migrador.py ── motor IMAP: probar · respaldar · subir · migrar · verificar
                    └─ importa programador.py ─ crea/borra la tarea de Windows de la copia automática
                                                    │
   Programador de tareas de Windows ──► pythonw migrador.py respaldar --automatica
                                          └─ deja el resultado en automatica.json

 Servidor actual (IMAP, solo lectura) ──► copia local (.eml + índices) ──► servidor nuevo (IMAP APPEND)
                         └──────────── «migrar» = respaldar + subir ──────────────┘
```

Tres archivos de Python, sin dependencias externas:

| Archivo | Rol |
|---|---|
| `migrador.py` | Motor. Configuración, conexión IMAP con reintentos, copia local, subida, verificación, claves cifradas, bloqueo, modo terminal y modo automático. Se puede usar solo. |
| `app.py` | Servidor de la interfaz. Estado compartido en memoria, API, eventos en vivo, lanzamiento de tareas en un hilo, pausa y cancelación. |
| `programador.py` | Copia automática: arma el XML de la tarea, la registra con `schtasks` y calcula la próxima ejecución. |
| `espacio.py` | Liberar espacio: catálogo de la copia local, reglas de qué no se sube y exportación de adjuntos a carpetas comunes. |

## Liberar espacio (`espacio.py`)

- **Nunca borra.** Decide qué entradas de `plan_de_subida` se saltean al subir.
- `filtros.json` (junto al programa), por cuenta: `papelera`, `boletines`, `duplicados`, `desde`
  (`AAAA-MM-DD`), `excluir` y `incluir` (claves `"<carpeta en disco>/<archivo .eml>"`) y
  `limite_mb`. `incluir` gana sobre cualquier regla.
- `catalogo(cfg, correo)` lee cada `.eml` del plan (fecha del encabezado `Date`, remitente,
  asunto, si es boletín por `List-Unsubscribe`/`List-Id`/`Precedence` y adjuntos sin contar las
  firmas `imageNNN` chicas) y lo cachea en `<cuenta>/_resumen.jsonl`. La primera vez con 1 GB tarda
  unos 100 s; después, menos de 0,1 s. `respaldar_cuenta` lo actualiza al final de cada copia.
- `motivos()` asigna a cada correo `None` (se sube) o `papelera`, `boletin`, `duplicado`
  (mismo Message-ID o sha256 en la misma carpeta, se queda el más viejo), `fecha` o `manual`.
- `subir_cuenta` y `verificar_cuenta` usan `claves_excluidas()` (vacío y sin analizar si la
  cuenta no tiene filtro). Antes de subir, `guardar_adjuntos(solo_excluidos=True)` exporta los
  adjuntos de lo excluido a `<carpeta_respaldo>\..\adjuntos\<correo>\<fecha> - <remitente> - <asunto>\`.
  Es idempotente: no reescribe un archivo igual.
- `evaluar()` devuelve totales, lo excluido por motivo, el `potencial` de cada regla por sí sola,
  los 60 correos más pesados con su motivo y el crecimiento mensual (promedio de 12 meses).
- Acciones del motor: `adjuntos` (los de lo excluido) y `adjuntos_todos`.

## Modelo de datos

### Configuración (junto al programa)

**`config.ini`**, que la interfaz reescribe al guardar:

```ini
[origen]                 ; servidor actual
proveedor = cpanel       ; clave de PROVEEDORES (cpanel, hostinger, gmail, zoho, ionos, titan, godaddy, yahoo, otro)
servidor = server123.tuhosting.com
puerto = 993
seguridad = ssl          ; ssl | starttls | ninguna
verificar_certificado = si
[destino]                ; servidor nuevo (solo para migrar)
...mismos campos...
[general]
carpeta_respaldo = C:\MigracionCorreos\respaldo
excluir_carpetas =       ; nombres separados por comas
cuentas_a_la_vez = 2     ; hilos, una cuenta por hilo
lote_mb = 20             ; tamaño máximo de cada FETCH de cuerpos
```

**`cuentas.csv`**: `correo,clave_origen,correo_destino,clave_destino,servidor,puerto,seguridad,verificar`.
La app **siempre** escribe las claves vacías. El motor todavía las lee si alguien las pone a mano, y
la app las pasa al almacén cifrado al arrancar (`cargar_claves_guardadas`). `correo_destino` vacío
significa «el mismo». Las cuatro últimas columnas (`CAMPOS_SERVIDOR`) son el **servidor propio de la
cuenta**: si `servidor` está vacío, la cuenta usa el `[origen]` general (`origen_de(cuenta, cfg)`).
Un CSV viejo de cuatro columnas se sigue leyendo igual. `guardar_cuentas` (app) conserva el servidor
guardado de cada cuenta si el pedido no trae esos campos, para que guardar desde la interfaz nunca lo
borre.

**`estado_app.json`**, preferencias y progreso del recorrido:

```json
{
  "recordar": true,
  "checklist": {"mx": "2026-10-14T09:30:12", "baja": null},
  "ultima_copia": "…", "ultima_migracion": "…",
  "ultima_verificacion": {"fecha": "…", "ok": true},
  "automatica": {"activa": false, "dias": ["domingo"], "hora": "22:00"},
  "historial": [{"fecha": "…", "accion": "migrar", "cuentas": 2, "resultado": "ok"}]
}
```

**`automatica.json`**: el resultado de la última copia automática. Lo escribe el proceso de la
tarea, **no** la app, para no competir con el `estado_app.json` que la app tiene en memoria:

```json
{"fecha": "…", "ok": true, "cuentas": 3, "nuevos": 12, "errores": {"correo": "mensaje"}, "registro": "ruta del .log"}
```

**Claves**: `%APPDATA%\MigradorCorreos\claves.bin` (o `MIGRADOR_CLAVES`). Contiene
`{"correo": {"clave_origen": "…", "clave_destino": "…"}}` en JSON, cifrado con
`CryptProtectData` (DPAPI, ámbito de usuario, entropía `b"MigradorCorreos"`). Solo ese usuario de
Windows, en ese equipo, puede descifrarlo. Si no se puede leer, `leer_claves()` devuelve `{}`.

### Copia local

```
<carpeta_respaldo>\
  .en_uso                              archivo del bloqueo entre procesos (ver «Bloqueo»)
  info@dominio.com\                    una carpeta por cuenta (segura(correo))
    _origen.json                       huella del servidor de la primera copia
    _ultima_copia.json                 {"fecha", "nuevos", "carpetas"}
    _subidos_<host>_<usuario>.json     estado de subida: {"carpeta de origen": ["sha256", …]}
    _errores.csv                       fecha;fase;carpeta;uid;detalle (separado por ;)
    INBOX\
      _carpeta.json                    metadatos de la carpeta IMAP
      indice.jsonl                     una línea JSON por mensaje (solo se agrega)
      _vistos.json                     {"uidvalidity": [uids]} que ya estaban en la copia (cambio de servidor)
      1791962943_0000001.eml           <uidvalidity>_<uid>.eml, el mensaje completo tal cual
    INBOX.Sent\ …
```

`_carpeta.json`:

```json
{"nombre": "INBOX.Sent", "delim": ".", "flags": ["\\HasNoChildren", "\\Sent"], "prefijo_origen": "INBOX.",
 "componentes": ["Sent"], "especial": "\\sent", "uidvalidity": 1791962943,
 "nombres_servidor": ["Enviados"]}
```

`nombres_servidor` (opcional) guarda los otros nombres con que esa carpeta aparece en un servidor
nuevo; `dir_para_carpeta` busca por nombre, después por esos nombres y, solo al adoptar un cambio de
servidor, por tipo especial si hay una única carpeta local de ese tipo.

Línea de `indice.jsonl`:

```json
{"uid": 17, "uidvalidity": 1791962943, "archivo": "1791962943_0000017.eml", "flags": ["\\Seen"],
 "fecha": "14-Oct-2026 07:32:00 +0200", "tamano": 48213, "sha256": "…", "message_id": "<…@…>"}
```

`_origen.json`:

```json
{"servidor": "mail.dominio.com", "ip": "203.0.113.10", "nombre_servidor": "server123.tuhosting.com",
 "nombres_certificado": ["…"], "uidvalidity_inbox": 1791962943, "fecha": "…",
 "cambio_pendiente": true, "anteriores": [{…huella del servidor anterior…}]}
```

`anteriores` y `cambio_pendiente` aparecen solo después de un cambio de servidor adoptado (ver
«Protección del origen»).

El nombre de la carpeta en disco sale de `segura()` (sin caracteres inválidos en Windows, máximo
80 caracteres). Si dos carpetas IMAP chocan, se agrega un sufijo con hash (`carpeta_local`). El
nombre IMAP real siempre está en `_carpeta.json`.

## Motor (`migrador.py`)

### Conexión

`Conexion` envuelve `imaplib`: SSL directo, STARTTLS o sin cifrar; verificación de certificado
opcional; login con `AUTHENTICATE PLAIN` si la clave tiene caracteres no ASCII. `cmd()` reintenta
hasta 5 veces si se cae la conexión (espera 5, 10, 15… segundos), vuelve a abrir y re-selecciona
la carpeta. Los nombres de carpeta viajan en UTF-7 modificado (`mutf7_encode`/`decode`, `wire()`
los pone entre comillas). `listar()` descarta `\Noselect`; `espacio_personal()` lee NAMESPACE
(prefijo `INBOX.` y separador `.` en cPanel/Dovecot); `cuota()` usa GETQUOTAROOT si existe.

### Copia local: `respaldar_cuenta` → `respaldar_carpeta`

1. `comprobar_origen()` compara la huella con `_origen.json`. Si cambió el UIDVALIDITY de INBOX con
   el mismo nombre de servidor, lanza `OrigenCambiado` y no copia nada; si cambió con otro nombre,
   adopta el servidor nuevo (ver «Protección del origen»).
2. `carpetas_a_copiar()` omite las excluidas y las virtuales de Gmail (`\Flagged`, `\Important`) y
   deja `\All` al final.
3. Por carpeta: `dir_para_carpeta` elige la carpeta local, después `STATUS` (UIDVALIDITY),
   `EXAMINE`, `UID SEARCH ALL`. Los pendientes son los `(uidvalidity, uid)` que no están en
   `indice.jsonl` ni en `_vistos.json`. Si el UIDVALIDITY es nuevo para esa carpeta y la cuenta
   viene de un cambio de servidor (o la carpeta ya tenía correos), trae solo las cabeceras
   (`MESSAGE-ID DATE FROM SUBJECT`) de a 300 y las compara con `ClavesLocales` (las claves de toda la
   cuenta): lo que ya está se anota en `_vistos.json` y no se baja.
4. `UID FETCH (UID FLAGS INTERNALDATE RFC822.SIZE)` de a 300, y después `UID FETCH (UID BODY.PEEK[])`
   en lotes de hasta `lote_mb` MB o 200 mensajes.
5. Cada mensaje se escribe en `.tmp` y se renombra (atómico), y después se agrega su línea al
   índice. `fsync` por lote. Un corte deja como mucho una línea a medias, que `leer_indice` ignora.
6. Al terminar escribe `_ultima_copia.json`.

### Subida: `subir_cuenta` → `subir_carpeta` → `subir_mensaje`

- `plan_de_subida(raiz)` arma `[(directorio, meta, entradas)]` sin los borrados (`\Deleted`). Para
  la carpeta `\All` de Gmail descarta lo que ya está en otras carpetas (por sha256 o Message-ID).
- `nombre_destino(meta, dest)` traduce la carpeta: INBOX → INBOX; las especiales (`\Sent`,
  `\Drafts`, `\Junk`, `\Trash`, `\Archive`, por marca SPECIAL-USE o por nombre conocido en inglés o
  español) van a la equivalente del destino. El resto se rearma con el prefijo y el separador del
  destino. `asegurar_carpeta` crea la carpeta y sus padres, y se suscribe.
- **Deduplicación**, en dos capas:
  1. Estado local `_subidos_<host>_<usuario>.json`, con el sha256 de cada mensaje ya subido.
  2. Lo que ya está en el destino: `ids_en_destino` trae `HEADER.FIELDS (MESSAGE-ID DATE FROM SUBJECT)`
     y `clave_mensaje()` usa el Message-ID o, si falta, `huella_cabecera` (sha1 de fecha|remitente|asunto).
- `APPEND` conserva las marcas `\Seen \Answered \Flagged \Draft` y la fecha de recepción original.
  Si se corta después del APPEND, al reconectar busca el Message-ID antes de reintentar (`subir_mensaje`).
- El estado se guarda cada 25 mensajes y al terminar cada carpeta.

### Verificación: `verificar_cuenta`

Por carpeta: mensajes en origen (STATUS), en la copia local (entradas del UIDVALIDITY actual) y en
destino. Una fila está OK si la copia tiene al menos lo del origen y el destino al menos los
«esperados» (sha256 únicos sin borrados). **Si el origen no responde**, usa las carpetas de la copia
local, deja «origen» en `None` y devuelve `error_origen`.

### Protección del origen

Problema: al mudar el DNS, `mail.dominio.com` pasa a apuntar al servidor nuevo, y una «copia del
servidor viejo» bajaría correos del nuevo. Solución: en la primera copia, `_origen.json` guarda el
UIDVALIDITY de INBOX, la IP, los nombres del certificado y el nombre inverso de la IP
(`nombre_inverso`, solo si resuelve de vuelta a la misma IP). Si en una copia posterior cambia el
UIDVALIDITY de INBOX, se lanza `OrigenCambiado` con la sugerencia del nombre propio del servidor
viejo (por ejemplo `server123.tuhosting.com`) o su IP. «Probar cuentas» muestra el mismo aviso sin bloquear.

**Cambio de servidor a propósito.** Si el UIDVALIDITY cambió pero el servidor configurado tiene
**otro nombre** que el de la huella (la cuenta pasó de un cPanel a `imap.hostinger.com`), no es el DNS:
`comprobar_origen` mueve la huella vieja a `anteriores`, guarda la nueva con `cambio_pendiente` y
sigue. Mientras haya `cambio_pendiente`, cada carpeta nueva se deduplica contra toda la copia (ver
paso 3 de la copia local); se borra cuando una copia completa termina sin carpetas con error, así que
una copia cancelada retoma sin duplicar. Los `.eml` existentes nunca se tocan.

**Detección del servidor** (`detectar_servidor(correo)`, `POST /api/detectar-servidor`): lee los MX
del dominio con `nslookup -type=mx` (la salida sale en inglés también en Windows en español). Si es
un proveedor conocido (`MX_CONOCIDOS`) devuelve su servidor IMAP; en un cPanel devuelve el nombre
inverso de la IP (el nombre real, que no cambia con el DNS). Outlook/Microsoft 365 se avisa como no
soportado.

### Bloqueo entre procesos

`bloqueo(cfg)` toma `msvcrt.locking` (o `fcntl.flock` en otros sistemas) sobre
`<respaldo>\.en_uso`. Lo usan `respaldar`, `subir` y `migrar`. Si otro proceso lo tiene (la app y la
copia automática a la vez), lanza `EnUso` y todas las cuentas de esa tarea terminan con ese error.
Si el proceso muere, el sistema operativo libera el bloqueo solo.

### Orquestación, control y avisos

- `ACCIONES`: `probar`, `probar_origen`, `probar_destino`, `respaldar`, `subir`, `migrar` y
  `verificar`, cada una con sus banderas (usa origen, usa destino).
- `ejecutar_cuentas(accion, cuentas, cfg)` corre una cuenta por hilo (`cuentas_a_la_vez`) y devuelve
  `{correo: {"ok": bool, "resultado" | "error"}}`.
- `CONTROL` (`Control`): `punto()` se llama entre lotes y entre mensajes. Espera si `seguir` está
  apagado (pausa) y lanza `Cancelado` si `cancelar` está prendido.
- `reportar(correo, **campos)` avisa el progreso al oyente que registra la app con `al_reportar`.
  Campos: `fase` (`en_cola`, `conectando`, `descargando`, `subiendo`, `probando`, `verificando`,
  `listo`, `error`, `cancelado`), `total`, `hechos`, `bytes`, `carpeta`, `error` y `resultado`.
- `explicar_error(e)` traduce las excepciones a mensajes para personas.
- Registro: `logging` con un adaptador por cuenta (`log_de`) y un archivo por tarea en `registros/`.

### Terminal y modo automático

```
python migrador.py                       menú interactivo
python migrador.py <acción> [--cuenta c] pide por teclado las claves que falten
python migrador.py respaldar --automatica   lo que corre la tarea programada
```

`ejecutar_automatica()` no pregunta nada: usa las claves de `cuentas.csv` o del almacén cifrado,
omite las cuentas sin clave (y lo anota como error), registra en `registros/*_auto_respaldar.log`
y escribe `automatica.json`. Devuelve código 1 si hubo errores, y entonces Windows reintenta.

## Copia automática (`programador.py`)

- Tarea `\MigradorCorreos\CopiaAutomatica` (o `MIGRADOR_TAREA`), registrada con
  `schtasks /create /xml` (XML en UTF-16).
- Disparador semanal con los días elegidos y la hora (`CalendarTrigger`/`ScheduleByWeek`).
- `LogonType=InteractiveToken`: corre con el usuario actual y solo con la sesión iniciada, que es
  lo que necesita DPAPI para leer las claves.
- `StartWhenAvailable=true` (si la computadora estaba apagada, corre al prenderla),
  `MultipleInstancesPolicy=IgnoreNew`, `RestartOnFailure` cada 15 minutos hasta 3 veces (por
  ejemplo, si la unidad sincronizada donde está el programa todavía no se montó), y funciona con batería.
- Acción: `pythonw.exe` (sin ventana) con `"<migrador.py>" respaldar --automatica` y la carpeta del
  programa como directorio de trabajo.
- La app guarda la preferencia en `estado_app.json → automatica`. Si se apaga «Guardar las
  claves», `guardar_cuentas` borra la tarea y la desactiva.

## Servidor de la interfaz (`app.py`)

### Seguridad

- Escucha solo en `127.0.0.1`, desde el puerto 47615 hacia arriba. `ServidorExclusivo` desactiva
  `SO_REUSEADDR` y usa `SO_EXCLUSIVEADDRUSE`, porque en Windows `SO_REUSEADDR` deja que dos
  programas compartan un puerto y la ventana terminaba mostrando otra app local. Además,
  `puerto_ocupado()` salta los puertos donde ya responde algo.
- Token aleatorio por sesión (`secrets.token_urlsafe`): en la URL para `/` y `/api/eventos`, y en
  la cabecera `X-Token` para el resto. Además se valida la cabecera `Host` (contra DNS rebinding).

### Una sola app abierta

Al arrancar, `main()` lee `%APPDATA%\MigradorCorreos\instancia.json` (`{puerto, token, pid, version}`,
o `MIGRADOR_INSTANCIA`) y consulta `/api/estado` de esa instancia:

- **Misma versión** (`version_codigo()` = hash de fecha y tamaño de los archivos del programa):
  abre la ventana de la que ya está y termina.
- **Versión anterior y libre**: le pide `POST /api/salir`, espera a que suelte el puerto y arranca
  la nueva.
- **Versión anterior con una tarea en curso**: abre esa y avisa, sin cortar la tarea.

Al cerrarse, la instancia borra su `instancia.json` (`olvidar_instancia`). Con `--puerto`, que se
usa en las pruebas, no se registra ni se buscan otras instancias.

### Estado compartido (`Estado`, instancia `E`)

`claves` (solo en memoria; se persiste cifrado si `recordar`), `trabajo` (`accion`, `estado`:
`libre`/`corriendo`/`pausado`/`cancelando`/`terminado`/`cancelado`, `inicio`, `fin`, `cuentas`, `ok`),
`cuentas` (progreso por cuenta, con `descarga` y `subida` = `{hechos, total, bytes, t0}`), `log` (las
últimas 1500 líneas), `resultados` (`{acción: {correo: resultado}}`) y `app` (el contenido de
`estado_app.json`). Un `difusor` manda el progreso acumulado cada 300 ms; `vaciar_progreso()` lo
fuerza antes del evento de fin de tarea.

### API

| Método y ruta | Cuerpo | Respuesta / efecto |
|---|---|---|
| `GET /?t=TOKEN` | — | `ui/index.html` con el token incrustado |
| `GET /ui/<archivo>` | — | archivos estáticos (sin token) |
| `GET /api/estado` | — | `config`, `proveedores`, `cuentas` (sin claves, con `tiene_clave_*`), `recordar`, `claves_cifrables`, `trabajo`, `progreso`, `log`, `resultados`, `app`, `local` (por cuenta: mensajes, bytes, carpetas, fecha de la última copia y `nombre_servidor`, el nombre propio del servidor de origen, sacado de `_origen.json` o del nombre inverso de su IP) y `automatica` |
| `GET /api/eventos?t=TOKEN` | — | Server-Sent Events (ver abajo), con latido cada 15 s |
| `POST /api/config` | `{origen, destino, general}` parciales | guarda `config.ini` |
| `POST /api/cuentas` | `{cuentas: [{correo, correo_destino, clave_origen, clave_destino, servidor?, puerto?, seguridad?, verificar?}], recordar}`; una clave `null` significa «sin cambios»; si faltan los campos del servidor se conserva el guardado | guarda el CSV y las claves cifradas; puede devolver `automatica_apagada` |
| `POST /api/probar-servidor` | `{servidor: {...}}` | conecta sin iniciar sesión: `{ok, ms, aviso}` o `{ok: false, error}` |
| `POST /api/detectar-servidor` | `{correo}` | `detectar_servidor()`: `{ok, servidor, puerto, seguridad, texto}` o un aviso |
| `POST /api/accion` | `{accion, correos}` | lanza la tarea en un hilo; valida por cuenta que tenga servidor (propio o general), claves, y que el destino no sea su mismo servidor |
| `POST /api/pausar` · `/api/reanudar` · `/api/cancelar` | `{}` | controla la tarea en curso |
| `POST /api/abrir` | `{que: "respaldo" | "registros"}` | abre la carpeta en el Explorador |
| `POST /api/checklist` | `{item, hecho}` | marca o desmarca los pasos manuales (`mx`, `baja`) |
| `POST /api/automatica` | `{activa, dias, hora}` | crea, actualiza o borra la tarea programada |
| `POST /api/automatica-ahora` | `{}` | `schtasks /run` de la tarea |
| `POST /api/espacio` | `{correo, filtro?}` | guarda el filtro (si viene) y devuelve `evaluar()` más `limite_sugerido_mb` (de la cuota probada del destino) |
| `POST /api/salir` | `{}` | cierra el servidor si no hay una tarea en curso (lo usa una versión nueva para reemplazar a esta) |

### Eventos en vivo

```json
{"tipo": "cuentas", "datos": {"correo": {"fase": "descargando", "descarga": {"hechos": 120, "total": 957, "bytes": 3400000, "t0": 1791962943.1}, "subida": null, "carpeta": "INBOX", "error": null, "resultado": null}}}
{"tipo": "log", "linea": {"hora": "09:41:52", "nivel": "INFO", "cuenta": "correo", "texto": "…"}}
{"tipo": "trabajo", "trabajo": {"accion": "migrar", "estado": "terminado", "cuentas": ["…"], "ok": true}, "resultados": {…}, "app": {…}}
```

## Interfaz (`ui/`)

- `index.html`: estructura fija (barra lateral, `<main id="vista">`, avisos y `<dialog>`); el
  token llega en `window.TOKEN`.
- `app.js` (módulo ES): estado `S`, una función por vista
  (`vistaInicio`, `vistaServidor`, `vistaCuentas`, `vistaCopia`, `vistaMigrar`, `vistaVerificar` en
  `VISTAS`) que devuelve HTML. **Inicio** es la vista de entrada (siempre se abre ahí; el logo y el
  primer ítem de la barra vuelven a ella). Se arma con los datos que ya trae `/api/estado`:
  `avisosInicio()` (reglas de «Para revisar»), `estadoCopiaCuenta()` (al día, más de 30 días, sin
  copia o error en la última copia manual o automática) y `actividadInicio()` (el `historial` sin
  las pruebas, más la última copia automática). «Actualizar copia» desde Inicio lanza `respaldar`
  solo para las cuentas con clave y avisa cuáles se saltean. En **Cuentas**, cada fila muestra su
  servidor (`lineaServidor`: el propio en negrita o «Servidor general») con «Cambiar», que abre el
  modal `servidor-cuenta`; al agregar una cuenta o cambiar su correo, `detectarServidorCuenta` lo
  completa solo si la cuenta no tiene uno. Hay eventos delegados en `document` (`data-accion`, `data-ir`, `data-c`,
  `data-servidor`, `data-general`, `data-dia`, `data-fuente`…).
- Refresco en vivo sin perder el foco ni las animaciones: `parchear(viejo, html)` compara
  `data-forma`; si coincide, solo actualiza los nodos `[data-k]` (texto, clase, ancho de barra
  `data-ancho`, anillo `data-offset`), y si no, reemplaza el nodo. `refrescarVivo` usa
  `setTimeout`, no `requestAnimationFrame`, porque este se congela con la ventana minimizada.
- Selección de cuentas (`S.excluidas`), paso actual, fuente de la migración, tema y paneles
  abiertos se guardan en `localStorage` (con try/catch).
- `estilos.css`: tokens en `:root`, modo oscuro con `prefers-color-scheme` y `data-theme`, y
  cortes a 1100, 900 y 560 px.
- `iconos.js`: los SVG de Phosphor (regular, MIT) que usa la interfaz. Para agregar uno, ver
  DESARROLLO.md.

## Invariantes (si alguno se rompe, es un error)

1. Nada escribe en el servidor de origen.
2. Repetir `respaldar` no baja nada que ya esté en el índice con el mismo UIDVALIDITY.
3. Repetir `subir` o `migrar` no crea mensajes duplicados en el destino, aunque falte el archivo
   de estado.
4. Un mensaje subido conserva los bytes, las marcas permitidas y la fecha de recepción.
5. Si el origen cambió de máquina con el mismo nombre (DNS), no se copia nada. Si la cuenta pasó a
   propósito a otro servidor, se sigue en la misma copia sin volver a bajar lo que ya estaba y sin
   tocar los `.eml` existentes.
6. Nunca corren dos procesos escribiendo la misma carpeta de respaldo.
7. Ninguna clave queda en texto plano en el disco ni en los registros.
