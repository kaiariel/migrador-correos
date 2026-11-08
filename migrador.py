#!/usr/bin/env python3
"""Migrador de correos por IMAP (motor).

Respalda en disco todas las carpetas de cada cuenta del servidor de origen
(con adjuntos, fechas y marcas de leído) y las sube al servidor de destino.
Se puede repetir las veces que haga falta: solo descarga y sube lo nuevo.

Interfaz visual:  python app.py   (o doble clic en Migrador.bat)
Terminal:         python migrador.py [probar|respaldar|subir|migrar|verificar] [--cuenta correo]
"""

import argparse
import base64
import configparser
import csv
import getpass
import hashlib
import imaplib
import json
import logging
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
TIMEOUT = 180
imaplib._MAXLINE = 50_000_000  # listados o cabeceras muy largas

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------- proveedores conocidos

PROVEEDORES = {
    "cpanel": {
        "nombre": "cPanel / hosting compartido", "servidor": "", "puerto": 993, "seguridad": "ssl",
        "ayuda": "En cPanel → Cuentas de correo → Connect Devices figura el servidor IMAP. "
                 "Si vas a cambiar el DNS en el medio, usá el nombre del servidor (p. ej. srv12.proveedor.com) "
                 "y no mail.tudominio.com: después del cambio, ese nombre apunta al hosting nuevo.",
    },
    "hostinger": {
        "nombre": "Hostinger", "servidor": "imap.hostinger.com", "puerto": 993, "seguridad": "ssl",
        "ayuda": "Creá antes las casillas en hPanel → Correos. Hostinger no acepta mensajes de más de 50 MB.",
    },
    "gmail": {
        "nombre": "Gmail / Google Workspace", "servidor": "imap.gmail.com", "puerto": 993, "seguridad": "ssl",
        "ayuda": "Activá IMAP en Gmail y usá una contraseña de aplicación (requiere verificación en dos "
                 "pasos). Las etiquetas pasan como carpetas; de «Todos» solo se copian los archivados.",
    },
    "zoho": {
        "nombre": "Zoho Mail", "servidor": "imap.zoho.com", "puerto": 993, "seguridad": "ssl",
        "ayuda": "Activá el acceso IMAP en la configuración de Zoho. Cuentas de la UE: imap.zoho.eu.",
    },
    "ionos": {
        "nombre": "IONOS", "servidor": "imap.ionos.es", "puerto": 993, "seguridad": "ssl",
        "ayuda": "Usuario: la dirección de correo completa.",
    },
    "titan": {
        "nombre": "Titan Mail", "servidor": "imap.titan.email", "puerto": 993, "seguridad": "ssl",
        "ayuda": "Lo usan varios hostings (Hostinger antiguo, Bluehost, etc.).",
    },
    "godaddy": {
        "nombre": "GoDaddy Workspace", "servidor": "imap.secureserver.net", "puerto": 993, "seguridad": "ssl",
        "ayuda": "Solo para el correo Workspace de GoDaddy (no para Microsoft 365 de GoDaddy).",
    },
    "yahoo": {
        "nombre": "Yahoo Mail", "servidor": "imap.mail.yahoo.com", "puerto": 993, "seguridad": "ssl",
        "ayuda": "Requiere una contraseña de aplicación generada en la seguridad de la cuenta.",
    },
    "otro": {
        "nombre": "Otro servidor", "servidor": "", "puerto": 993, "seguridad": "ssl",
        "ayuda": "Pedile a tu proveedor el servidor IMAP. Lo habitual: puerto 993 con SSL/TLS, "
                 "o 143 con STARTTLS.",
    },
}


# ---------------------------------------------------------------- configuración

@dataclass
class Servidor:
    host: str
    puerto: int
    seguridad: str  # ssl | starttls | ninguna
    verificar: bool
    proveedor: str = "otro"


@dataclass
class Cuenta:
    correo: str
    usuario_origen: str
    usuario_destino: str
    clave_origen: str
    clave_destino: str
    origen: Servidor | None = None  # servidor propio de la cuenta; None = el servidor actual general


@dataclass
class Config:
    origen: Servidor
    destino: Servidor
    respaldo: Path
    excluir: list
    hilos: int
    lote_mb: int


def si(valor):
    return str(valor).strip().lower() in ("si", "sí", "s", "yes", "y", "true", "1")


CONFIG_POR_DEFECTO = {
    "origen": {"proveedor": "cpanel", "servidor": "", "puerto": 993, "seguridad": "ssl", "verificar": True},
    "destino": {"proveedor": "hostinger", "servidor": "imap.hostinger.com", "puerto": 993, "seguridad": "ssl",
                "verificar": True},
    "general": {"carpeta_respaldo": r"C:\MigracionCorreos\respaldo", "excluir_carpetas": [],
                "cuentas_a_la_vez": 2, "lote_mb": 20},
}


def leer_config_dict():
    d = json.loads(json.dumps(CONFIG_POR_DEFECTO))
    ruta = BASE / "config.ini"
    if not ruta.exists():
        return d
    cp = configparser.ConfigParser()
    cp.read(ruta, encoding="utf-8-sig")
    for lado in ("origen", "destino"):
        if lado in cp:
            s = cp[lado]
            seguridad = s.get("seguridad") or ("ssl" if si(s.get("ssl", "si")) else "ninguna")
            d[lado].update({
                "proveedor": s.get("proveedor", d[lado]["proveedor"]),
                "servidor": s.get("servidor", "").strip(),
                "puerto": s.getint("puerto", 993),
                "seguridad": seguridad,
                "verificar": si(s.get("verificar_certificado", "si")),
            })
    if "general" in cp:
        g = cp["general"]
        d["general"].update({
            "carpeta_respaldo": g.get("carpeta_respaldo", d["general"]["carpeta_respaldo"]),
            "excluir_carpetas": [x.strip() for x in g.get("excluir_carpetas", "").split(",") if x.strip()],
            "cuentas_a_la_vez": g.getint("cuentas_a_la_vez", 2),
            "lote_mb": g.getint("lote_mb", 20),
        })
    return d


def escribir_config_dict(d):
    lineas = ["; Configuración del migrador (la interfaz la reescribe al guardar).", ""]
    for lado in ("origen", "destino"):
        s = d[lado]
        lineas += [f"[{lado}]", f"proveedor = {s['proveedor']}", f"servidor = {s['servidor']}",
                   f"puerto = {int(s['puerto'])}", f"seguridad = {s['seguridad']}",
                   f"verificar_certificado = {'si' if s['verificar'] else 'no'}", ""]
    g = d["general"]
    lineas += ["[general]", f"carpeta_respaldo = {g['carpeta_respaldo']}",
               f"excluir_carpetas = {', '.join(g['excluir_carpetas'])}",
               f"cuentas_a_la_vez = {int(g['cuentas_a_la_vez'])}", f"lote_mb = {int(g['lote_mb'])}", ""]
    (BASE / "config.ini").write_text("\n".join(lineas), encoding="utf-8")


def config_desde_dict(d):
    def servidor(s):
        return Servidor(host=s["servidor"].strip(), puerto=int(s["puerto"]), seguridad=s["seguridad"],
                        verificar=bool(s["verificar"]), proveedor=s.get("proveedor", "otro"))

    g = d["general"]
    return Config(
        origen=servidor(d["origen"]),
        destino=servidor(d["destino"]),
        respaldo=Path(os.path.expandvars(g["carpeta_respaldo"])).expanduser(),
        excluir=list(g["excluir_carpetas"]),
        hilos=max(1, int(g["cuentas_a_la_vez"])),
        lote_mb=max(1, int(g["lote_mb"])),
    )


def leer_cuentas_dicts():
    ruta = BASE / "cuentas.csv"
    if not ruta.exists():
        return []
    texto = ruta.read_text(encoding="utf-8-sig")
    primera = texto.splitlines()[0] if texto.strip() else ""
    separador = ";" if primera.count(";") > primera.count(",") else ","
    cuentas = []
    for fila in csv.DictReader(texto.splitlines(), delimiter=separador):
        fila = {(k or "").strip().lower(): (v or "").strip() for k, v in fila.items()}
        correo = fila.get("correo", "")
        if not correo or correo.startswith("#"):
            continue
        cuentas.append({
            "correo": correo,
            "clave_origen": fila.get("clave_origen", ""),
            "correo_destino": fila.get("correo_destino") or fila.get("usuario_destino", ""),
            "clave_destino": fila.get("clave_destino", ""),
            **servidor_de_fila(fila),
        })
    return cuentas


# Columnas del servidor propio de cada cuenta (opcionales: un CSV viejo sin ellas sigue andando)
CAMPOS_SERVIDOR = ("servidor", "puerto", "seguridad", "verificar")


def servidor_de_fila(fila):
    servidor = (fila.get("servidor") or "").strip()
    if not servidor:
        return {"servidor": "", "puerto": "", "seguridad": "", "verificar": ""}
    seguridad = (str(fila.get("seguridad") or "ssl")).strip().lower()
    puerto = str(fila.get("puerto") or "").strip()
    v = fila.get("verificar")  # puede venir del CSV ("si"/"no") o ya normalizado (True/False)
    verificar = v if isinstance(v, bool) else si(v) if str(v or "").strip() else True
    return {
        "servidor": servidor,
        "puerto": int(puerto) if puerto.isdigit() else (143 if seguridad != "ssl" else 993),
        "seguridad": seguridad if seguridad in ("ssl", "starttls", "ninguna") else "ssl",
        "verificar": verificar,
    }


def escribir_cuentas_dicts(cuentas):
    with open(BASE / "cuentas.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["correo", "clave_origen", "correo_destino", "clave_destino", *CAMPOS_SERVIDOR])
        for c in cuentas:  # las claves nunca van al CSV: se guardan cifradas aparte (guardar_claves)
            s = servidor_de_fila(c)
            propio = [s["servidor"], s["puerto"], s["seguridad"], "si" if s["verificar"] else "no"] if s["servidor"] else ["", "", "", ""]
            w.writerow([c["correo"], "", c.get("correo_destino", ""), "", *propio])


# ---------------------------------------------------------------- claves guardadas (cifradas con el usuario de Windows)

RUTA_CLAVES = Path(os.environ.get("MIGRADOR_CLAVES")  # otra ubicación, solo para pruebas
                   or Path(os.environ.get("APPDATA") or Path.home()) / "MigradorCorreos" / "claves.bin")
CLAVES_CIFRABLES = sys.platform == "win32"


def _dpapi(datos, cifrar):
    """Cifra o descifra con DPAPI: solo este usuario de Windows, en este equipo, puede leerlo."""
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(b):
        buf = ctypes.create_string_buffer(b, len(b))
        return Blob(len(b), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    entrada, _b1 = blob(datos)
    entropia, _b2 = blob(b"MigradorCorreos")
    salida = Blob()
    crypt32 = ctypes.windll.crypt32
    if cifrar:
        ok = crypt32.CryptProtectData(ctypes.byref(entrada), "MigradorCorreos", ctypes.byref(entropia),
                                      None, None, 0x01, ctypes.byref(salida))
    else:
        ok = crypt32.CryptUnprotectData(ctypes.byref(entrada), None, ctypes.byref(entropia),
                                        None, None, 0x01, ctypes.byref(salida))
    if not ok:
        raise OSError("No se pudieron " + ("cifrar" if cifrar else "descifrar") + " las claves guardadas.")
    try:
        return ctypes.string_at(salida.pbData, salida.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(salida.pbData)


def leer_claves():
    """{correo: {"clave_origen", "clave_destino"}} guardadas, o {} si no hay o no se pueden leer."""
    if not CLAVES_CIFRABLES or not RUTA_CLAVES.exists():
        return {}
    try:
        return json.loads(_dpapi(RUTA_CLAVES.read_bytes(), cifrar=False).decode("utf-8"))
    except Exception:
        return {}


def guardar_claves(claves):
    if not CLAVES_CIFRABLES:
        raise OSError("Guardar claves cifradas solo funciona en Windows.")
    RUTA_CLAVES.parent.mkdir(parents=True, exist_ok=True)
    datos = {c: k for c, k in claves.items() if k.get("clave_origen") or k.get("clave_destino")}
    tmp = RUTA_CLAVES.with_suffix(".tmp")
    tmp.write_bytes(_dpapi(json.dumps(datos).encode("utf-8"), cifrar=True))
    os.replace(tmp, RUTA_CLAVES)


def borrar_claves():
    if RUTA_CLAVES.exists():
        RUTA_CLAVES.unlink()


def cuenta_desde_dict(c):
    destino = c.get("correo_destino") or c["correo"]
    s = servidor_de_fila(c)
    origen = (Servidor(host=s["servidor"], puerto=s["puerto"], seguridad=s["seguridad"], verificar=s["verificar"])
              if s["servidor"] else None)
    return Cuenta(correo=c["correo"], usuario_origen=c["correo"], usuario_destino=destino,
                  clave_origen=c.get("clave_origen", ""),
                  clave_destino=c.get("clave_destino") or c.get("clave_origen", ""), origen=origen)


def origen_de(cuenta, cfg):
    """El servidor actual de esta cuenta: el suyo propio o, si no tiene, el general."""
    return cuenta.origen or cfg.origen


def cargar_config():
    """Para la terminal: si falta la configuración, crea los archivos de ejemplo."""
    faltan = []
    for real, ejemplo in (("config.ini", "config.ejemplo.ini"), ("cuentas.csv", "cuentas.ejemplo.csv")):
        if not (BASE / real).exists():
            shutil.copy(BASE / ejemplo, BASE / real)
            faltan.append(real)
    if faltan:
        print(f"\nCreé {' y '.join(faltan)} a partir de los ejemplos.")
        print("Completalos con tus datos (o usá la interfaz: python app.py) y volvé a ejecutar.\n")
        sys.exit(1)
    return config_desde_dict(leer_config_dict())


def cargar_cuentas(filtro=None):
    guardadas = leer_claves()
    cuentas = [cuenta_desde_dict({**c, **{k: v for k, v in guardadas.get(c["correo"], {}).items() if v and not c.get(k)}})
               for c in leer_cuentas_dicts()
               if not filtro or c["correo"].lower() == filtro.lower()]
    if not cuentas:
        print("No hay cuentas para procesar en cuentas.csv" + (f" que coincidan con {filtro}" if filtro else ""))
        sys.exit(1)
    return cuentas


def pedir_claves(cuentas, necesita_origen, necesita_destino):
    """Pide por teclado las claves que no estén en el CSV (no se guardan)."""
    for c in cuentas:
        if necesita_origen and not c.clave_origen:
            c.clave_origen = getpass.getpass(f"Clave de {c.correo} en el servidor de ORIGEN: ")
        if necesita_destino and not c.clave_destino:
            if c.clave_origen:
                c.clave_destino = c.clave_origen
            else:
                c.clave_destino = getpass.getpass(f"Clave de {c.usuario_destino} en el servidor de DESTINO: ")


# ---------------------------------------------------------------- avisos de progreso y control (para la interfaz)

class Cancelado(Exception):
    pass


class EnUso(Exception):
    """Otra copia o migración (de la app o la copia automática) está usando la carpeta de respaldo."""


class OrigenCambiado(Exception):
    """El servidor de origen ya no es el de la primera copia (típico: el DNS ya apunta al hosting nuevo)."""


class Control:
    def __init__(self):
        self.cancelar = threading.Event()
        self.seguir = threading.Event()
        self.seguir.set()

    def reiniciar(self):
        self.cancelar.clear()
        self.seguir.set()

    def punto(self):
        """Se llama entre tandas: espera si está en pausa y corta si se canceló."""
        while not self.seguir.wait(0.5):
            if self.cancelar.is_set():
                break
        if self.cancelar.is_set():
            raise Cancelado()


CONTROL = Control()
_oyente = None


def al_reportar(fn):
    global _oyente
    _oyente = fn


def reportar(correo, **campos):
    if _oyente:
        _oyente(correo, campos)


def explicar_error(e):
    t = str(e)
    if isinstance(e, Cancelado):
        return "Cancelado"
    if isinstance(e, (OrigenCambiado, EnUso)):
        return t
    if isinstance(e, socket.gaierror):
        return "No se encontró el servidor. Revisá que el nombre esté bien escrito."
    if isinstance(e, ssl.SSLCertVerificationError):
        return ("El certificado del servidor no corresponde a ese nombre. Usá el nombre real del servidor "
                "(el que muestra el panel) o desactivá «Verificar certificado».")
    if isinstance(e, ConnectionRefusedError):
        return "El servidor rechazó la conexión en ese puerto."
    if isinstance(e, (socket.timeout, TimeoutError)):
        return "El servidor no responde (tiempo agotado). Revisá el servidor y el puerto."
    if isinstance(e, ssl.SSLError):
        return "Falló la conexión segura. Probá SSL/TLS con el puerto 993 o STARTTLS con el 143."
    if isinstance(e, imaplib.IMAP4.error) and re.search(r"auth|login|credential|password|invalid|denied", t, re.I):
        return "Usuario o clave incorrectos, o el acceso IMAP está desactivado en esa cuenta."
    if isinstance(e, OSError) and not t:
        return "Se perdió la conexión con el servidor."
    return t.replace("b'", "").replace("'", "") or e.__class__.__name__


# ---------------------------------------------------------------- registro

LOG = logging.getLogger("migrador")
LOG.setLevel(logging.INFO)


def preparar_registro(accion, consola=True):
    carpeta = BASE / "registros"
    carpeta.mkdir(exist_ok=True)
    archivo = carpeta / f"{datetime.now():%Y%m%d_%H%M%S}_{accion}.log"
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s [%(cuenta)s] %(message)s", "%H:%M:%S")
    for h in [h for h in LOG.handlers if getattr(h, "_propio", False)]:
        LOG.removeHandler(h)
        h.close()
    nuevos = [logging.FileHandler(archivo, encoding="utf-8")]
    if consola:
        nuevos.append(logging.StreamHandler(sys.stdout))
    for h in nuevos:
        h.setFormatter(fmt)
        h._propio = True
        LOG.addHandler(h)
    return archivo


def log_de(correo):
    return logging.LoggerAdapter(LOG, {"cuenta": correo})


def anotar_error(raiz, fase, carpeta, detalle, uid=""):
    raiz.mkdir(parents=True, exist_ok=True)
    ruta = raiz / "_errores.csv"
    nuevo = not ruta.exists()
    with open(ruta, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        if nuevo:
            w.writerow(["fecha", "fase", "carpeta", "uid", "detalle"])
        w.writerow([datetime.now().isoformat(timespec="seconds"), fase, carpeta, uid, detalle])


# ---------------------------------------------------------------- nombres de carpeta (UTF-7 modificado, RFC 3501)

def mutf7_decode(s):
    res, i = [], 0
    while i < len(s):
        if s[i] == "&":
            j = s.index("-", i)
            if j == i + 1:
                res.append("&")
            else:
                b64 = s[i + 1:j].replace(",", "/")
                b64 += "=" * (-len(b64) % 4)
                res.append(base64.b64decode(b64).decode("utf-16-be"))
            i = j + 1
        else:
            res.append(s[i])
            i += 1
    return "".join(res)


def mutf7_encode(s):
    res, buf = [], []

    def vaciar():
        if buf:
            b = "".join(buf).encode("utf-16-be")
            res.append("&" + base64.b64encode(b).decode().rstrip("=").replace("/", ",") + "-")
            buf.clear()

    for ch in s:
        if 0x20 <= ord(ch) <= 0x7E:
            vaciar()
            res.append("&-" if ch == "&" else ch)
        else:
            buf.append(ch)
    vaciar()
    return "".join(res)


def sin_comillas(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return re.sub(r"\\(.)", r"\1", s[1:-1])
    return s


def wire(nombre):
    """Nombre legible -> forma que viaja en el comando IMAP."""
    enc = mutf7_encode(nombre)
    return '"' + enc.replace("\\", "\\\\").replace('"', '\\"') + '"'


ESPECIALES = {
    "\\sent": {"sent", "sent items", "sent messages", "sent mail", "enviados", "elementos enviados",
               "mensajes enviados", "enviado"},
    "\\drafts": {"drafts", "draft", "borradores", "borrador"},
    "\\junk": {"junk", "spam", "junk e-mail", "junk email", "correo no deseado", "bulk mail"},
    "\\trash": {"trash", "deleted", "deleted items", "deleted messages", "papelera", "elementos eliminados",
                "eliminados"},
    "\\archive": {"archive", "archives", "archivo", "archivados"},
}
# Carpetas que no guardan correos propios sino vistas de otras (Gmail «Destacados», «Importantes»)
VIRTUALES = {"\\flagged", "\\important"}


def componentes(nombre, delim, prefijo):
    if nombre.upper() == "INBOX":
        return ["INBOX"]
    if prefijo and nombre.startswith(prefijo):
        nombre = nombre[len(prefijo):]
    return nombre.split(delim) if delim else [nombre]


def tipo_especial(flags, comps):
    bajas = [f.lower() for f in flags]
    if "\\all" in bajas:
        return "\\all"
    if any(f in VIRTUALES for f in bajas):
        return "virtual"
    for f in bajas:
        if f in ESPECIALES:
            return f
    if len(comps) == 1:
        for tipo, nombres in ESPECIALES.items():
            if comps[0].lower() in nombres:
                return tipo
    return None


def segura(texto, largo=80):
    t = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", texto).strip(" .") or "_"
    if t.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)),
                                   *(f"LPT{i}" for i in range(10))}:
        t = "_" + t
    return t[:largo].rstrip(" .") or "_"  # Windows no admite nombres que terminan en espacio o punto


# ---------------------------------------------------------------- conexión IMAP con reconexión

class Conexion:
    def __init__(self, srv, usuario, clave, log):
        self.srv, self.usuario, self.clave, self.log = srv, usuario, clave, log
        self.imap = None
        self.seleccion = None  # (nombre_wire, solo_lectura)

    def _contexto(self):
        ctx = ssl.create_default_context()
        if not self.srv.verificar:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        return ctx

    def conectar_sin_login(self):
        if not self.srv.host:
            raise ValueError("Falta el nombre del servidor.")
        if self.srv.seguridad == "ssl":
            return imaplib.IMAP4_SSL(self.srv.host, self.srv.puerto, ssl_context=self._contexto(), timeout=TIMEOUT)
        imap = imaplib.IMAP4(self.srv.host, self.srv.puerto, timeout=TIMEOUT)
        if self.srv.seguridad == "starttls" or "STARTTLS" in imap.capabilities:
            imap.starttls(ssl_context=self._contexto())
        return imap

    def abrir(self):
        self.cerrar()
        imap = self.conectar_sin_login()
        try:
            imap.login(self.usuario, self.clave)
        except UnicodeEncodeError:  # clave con tildes o ñ
            imap.authenticate("PLAIN", lambda _: f"\0{self.usuario}\0{self.clave}".encode("utf-8"))
        self.imap = imap
        if self.seleccion:
            imap.select(*self.seleccion)

    def cerrar(self):
        if self.imap is not None:
            try:
                self.imap.logout()
            except Exception:
                pass
        self.imap = None

    def cmd(self, fn, reintentos=5):
        for intento in range(1, reintentos + 1):
            try:
                if self.imap is None:
                    self.abrir()
                return fn(self.imap)
            except (imaplib.IMAP4.abort, OSError) as e:
                self.imap = None
                if intento == reintentos:
                    raise
                espera = 5 * intento
                self.log.warning(f"Se cortó la conexión ({e}). Reintento {intento} en {espera} s…")
                CONTROL.punto()
                time.sleep(espera)

    def seleccionar(self, nombre_wire, solo_lectura=True):
        self.seleccion = (nombre_wire, solo_lectura)
        typ, data = self.cmd(lambda i: i.select(nombre_wire, readonly=solo_lectura))
        if typ != "OK":
            self.seleccion = None
        return typ, data

    def listar(self):
        typ, data = self.cmd(lambda i: i.list())
        carpetas = []
        patron = re.compile(r'\((?P<flags>[^)]*)\)\s+(?P<delim>"(?:[^"\\]|\\.)*"|NIL)\s+(?P<nombre>.*)$', re.S)
        for item in data or []:
            if item is None:
                continue
            if isinstance(item, tuple):
                linea, literal = item[0].decode("utf-8", "replace"), item[1].decode("utf-8", "replace")
            else:
                linea, literal = item.decode("utf-8", "replace"), None
            m = patron.match(linea)
            if not m:
                continue
            flags = m["flags"].split()
            if any(f.lower() in ("\\noselect", "\\nonexistent") for f in flags):
                continue
            delim = None if m["delim"] == "NIL" else sin_comillas(m["delim"])
            crudo = literal if literal is not None else sin_comillas(m["nombre"])
            carpetas.append({"nombre": mutf7_decode(crudo), "delim": delim, "flags": flags})
        return carpetas

    def espacio_personal(self, carpetas):
        """Prefijo y separador de las carpetas personales (p. ej. 'INBOX.' y '.')."""
        try:
            typ, data = self.cmd(lambda i: i.namespace())
            if typ == "OK" and data and data[0]:
                m = re.match(r'\(\("((?:[^"\\]|\\.)*)"\s+(?:"((?:[^"\\]|\\.)*)"|NIL)\)', data[0].decode())
                if m:
                    return mutf7_decode(sin_comillas(f'"{m[1]}"')), (sin_comillas(f'"{m[2]}"') if m[2] else None)
        except imaplib.IMAP4.error:
            pass
        delim = next((c["delim"] for c in carpetas if c["delim"]), "/")
        return "", delim

    def contar(self, nombre):
        typ, data = self.cmd(lambda i: i.status(wire(nombre), "(MESSAGES UIDVALIDITY)"))
        if typ != "OK" or not data or not data[0]:
            return None, None
        txt = data[0].decode("utf-8", "replace")
        m1, m2 = re.search(r"MESSAGES (\d+)", txt), re.search(r"UIDVALIDITY (\d+)", txt)
        return (int(m1[1]) if m1 else None), (int(m2[1]) if m2 else None)

    def cuota(self):
        """(usado_kb, limite_kb) de la casilla, si el servidor lo informa."""
        if self.imap is None or "QUOTA" not in self.imap.capabilities:
            return None
        try:
            typ, data = self.cmd(lambda i: i.getquotaroot("INBOX"))
        except imaplib.IMAP4.error:
            return None
        if typ != "OK":
            return None
        for grupo in data:
            for item in grupo if isinstance(grupo, list) else [grupo]:
                if isinstance(item, bytes):
                    m = re.search(rb"STORAGE (\d+) (\d+)", item)
                    if m:
                        return int(m[1]), int(m[2])
        return None


def conectar(srv, usuario, clave, log):
    c = Conexion(srv, usuario, clave, log)
    c.abrir()
    return c


# ---------------------------------------------------------------- utilidades de mensajes

RE_UID = re.compile(rb"UID (\d+)")
RE_FLAGS = re.compile(rb"FLAGS \(([^)]*)\)")
RE_FECHA = re.compile(rb'INTERNALDATE "([^"]+)"')
RE_TAM = re.compile(rb"RFC822\.SIZE (\d+)")
RE_MSGID = re.compile(rb"^message-id:[ \t]*(.*?)\s*$", re.I | re.M)


def extraer_message_id(raw):
    cabecera = re.split(rb"\r?\n\r?\n", raw, maxsplit=1)[0]
    cabecera = re.sub(rb"\r?\n[ \t]+", b" ", cabecera)  # desplegar líneas continuadas
    m = RE_MSGID.search(cabecera)
    return m[1].decode("utf-8", "replace").strip() if m and m[1].strip() else None


def huella_cabecera(raw):
    """Para mensajes sin Message-ID: fecha + remitente + asunto."""
    cabecera = re.split(rb"\r?\n\r?\n", raw, maxsplit=1)[0]
    cabecera = re.sub(rb"\r?\n[ \t]+", b" ", cabecera)
    partes = []
    for campo in (rb"date", rb"from", rb"subject"):
        m = re.search(rb"^" + campo + rb":[ \t]*(.*?)\s*$", cabecera, re.I | re.M)
        partes.append(m[1].strip() if m else b"")
    return "sin-id:" + hashlib.sha1(b"|".join(partes)).hexdigest()


def clave_mensaje(raw):
    return extraer_message_id(raw) or huella_cabecera(raw)


def trozos(lista, n):
    for i in range(0, len(lista), n):
        yield lista[i:i + n]


def conjunto_uid(uids):
    return ",".join(str(u) for u in uids)


def leer_indice(carpeta):
    ruta = carpeta / "indice.jsonl"
    if not ruta.exists():
        return []
    entradas = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        if linea.strip():
            try:
                entradas.append(json.loads(linea))
            except json.JSONDecodeError:
                pass  # línea a medio escribir por un corte
    return entradas


def guardar_json(ruta, datos):
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, ruta)


def carpeta_local(raiz, nombre):
    """Directorio del respaldo para una carpeta IMAP (evita choques de nombres)."""
    d = raiz / segura(nombre)
    meta = d / "_carpeta.json"
    if meta.exists() and json.loads(meta.read_text(encoding="utf-8")).get("nombre") != nombre:
        d = raiz / (segura(nombre, 70) + "_" + hashlib.sha1(nombre.encode()).hexdigest()[:6])
    return d


def excluida(nombre, comps, cfg):
    return any(x.lower() in (nombre.lower(), comps[-1].lower()) for x in cfg.excluir)


def borrado(e):
    return "\\deleted" in (f.lower() for f in e["flags"])


def carpetas_a_copiar(conn, cfg, log):
    """Carpetas del origen con sus componentes, sin excluidas ni virtuales; «Todos» de Gmail al final."""
    carpetas = conn.listar()
    prefijo, delim_ns = conn.espacio_personal(carpetas)
    elegidas = []
    for c in carpetas:
        comps = componentes(c["nombre"], c["delim"] or delim_ns, prefijo)
        especial = tipo_especial(c["flags"], comps)
        if excluida(c["nombre"], comps, cfg):
            log.info(f"{c['nombre']}: excluida por configuración")
            continue
        if especial == "virtual":
            log.info(f"{c['nombre']}: carpeta virtual (sus correos están en otras carpetas), se omite")
            continue
        elegidas.append({**c, "componentes": comps, "especial": especial, "prefijo": prefijo})
    elegidas.sort(key=lambda c: c["especial"] == "\\all")
    return elegidas


# ---------------------------------------------------------------- respaldar (origen -> disco)

def huella_origen(conn, srv):
    """Datos para reconocer más adelante que seguimos hablando con el mismo servidor."""
    sock = conn.imap.sock
    try:
        ip = sock.getpeername()[0]
    except OSError:
        ip = None
    nombres = []
    if isinstance(sock, ssl.SSLSocket):
        cert = sock.getpeercert() or {}
        nombres = [v for k, v in cert.get("subjectAltName", ()) if k == "DNS"]
    _, uidvalidity = conn.contar("INBOX")
    return {"servidor": srv.host, "ip": ip, "nombre_servidor": nombre_inverso(ip),
            "nombres_certificado": nombres, "uidvalidity_inbox": uidvalidity}


def nombre_inverso(ip):
    """Nombre propio de la máquina (p. ej. server123.tuhosting.com), solo si apunta de vuelta a la misma IP.
    A diferencia de mail.tudominio.com, ese nombre no cambia cuando se muda el DNS del dominio."""
    if not ip:
        return None
    try:
        nombre = socket.gethostbyaddr(ip)[0]
        return nombre if socket.gethostbyname(nombre) == ip else None
    except OSError:
        return None


def comprobar_origen(conn, cfg, cuenta, guardar, log=None):
    """Compara el origen con la huella de la copia. Devuelve un aviso (y no se copia) o None.

    Si el servidor cambió pero con OTRO nombre (la cuenta pasó a propósito a otro servidor, por ejemplo
    de un cPanel a imap.hostinger.com), lo adopta: la huella vieja pasa a «anteriores» y queda
    «cambio_pendiente» para que la copia no vuelva a bajar lo que ya está en el disco. Si el nombre
    es el MISMO y la máquina otra, casi seguro el DNS ya apunta al hosting nuevo: ahí se frena."""
    srv = origen_de(cuenta, cfg)
    raiz = cfg.respaldo / segura(cuenta.correo)
    ruta = raiz / "_origen.json"
    actual = huella_origen(conn, srv)
    ahora = datetime.now().isoformat(timespec="seconds")
    if not ruta.exists():
        if guardar:
            raiz.mkdir(parents=True, exist_ok=True)
            guardar_json(ruta, {**actual, "fecha": ahora})
        return None
    previo = json.loads(ruta.read_text(encoding="utf-8"))
    if not previo.get("uidvalidity_inbox") or not actual["uidvalidity_inbox"] \
            or previo["uidvalidity_inbox"] == actual["uidvalidity_inbox"]:
        return None
    if srv.host.strip().lower() != (previo.get("servidor") or "").strip().lower():
        if guardar:
            anteriores = previo.pop("anteriores", [])
            previo.pop("cambio_pendiente", None)
            guardar_json(ruta, {**actual, "fecha": ahora, "cambio_pendiente": True, "anteriores": [previo, *anteriores]})
            if log:
                log.info(f"Cambio de servidor: de {previo.get('servidor')} a {srv.host}. La copia sigue en la misma "
                         "carpeta y no vuelve a bajar los correos que ya tiene.")
        return None
    sugerido = previo.get("nombre_servidor") or nombre_inverso(previo.get("ip"))
    if sugerido and sugerido.lower() == srv.host.lower():
        sugerido = None
    if sugerido:
        como = f"el nombre del servidor viejo, {sugerido}"
    elif previo.get("ip"):
        como = f"la IP del servidor viejo, {previo['ip']} (y desactivá «Verificar el certificado»)"
    else:
        como = "el nombre real del servidor viejo (el que muestra su panel)"
    donde = "En Cuentas, poné como servidor de esta cuenta" if cuenta.origen else "En Servidores, poné como origen"
    return (f"El servidor de origen ya no es el mismo de la primera copia ({previo.get('fecha', '')[:10]}): "
            f"seguramente el dominio ya apunta al hosting nuevo. {donde} {como}, "
            f"o el servidor nuevo si ya terminaste de migrar. No se copió nada para no mezclar correos.")


def respaldar_cuenta(cuenta, cfg):
    log = log_de(cuenta.correo)
    raiz = cfg.respaldo / segura(cuenta.correo)
    raiz.mkdir(parents=True, exist_ok=True)
    reportar(cuenta.correo, fase="conectando", carpeta="")
    conn = conectar(origen_de(cuenta, cfg), cuenta.usuario_origen, cuenta.clave_origen, log)
    try:
        aviso = comprobar_origen(conn, cfg, cuenta, guardar=True, log=log)
        if aviso:
            raise OrigenCambiado(aviso)
        ruta_huella = raiz / "_origen.json"
        huella = json.loads(ruta_huella.read_text(encoding="utf-8")) if ruta_huella.exists() else {}
        adoptar = bool(huella.get("cambio_pendiente"))
        carpetas = carpetas_a_copiar(conn, cfg, log)
        conteos = {c["nombre"]: conn.contar(c["nombre"])[0] or 0 for c in carpetas}
        prog = {"hechos": 0, "bytes": 0}
        reportar(cuenta.correo, fase="descargando", total=sum(conteos.values()), hechos=0, bytes=0)
        log.info(f"Origen: {len(carpetas)} carpetas, {sum(conteos.values())} mensajes")
        nuevos, fallaron = 0, 0
        claves = ClavesLocales(raiz)
        for c in carpetas:
            CONTROL.punto()
            try:
                nuevos += respaldar_carpeta(conn, c, raiz, cfg, log, cuenta.correo, prog, adoptar, claves)
            except imaplib.IMAP4.error as e:
                fallaron += 1
                log.error(f"{c['nombre']}: {e}")
                anotar_error(raiz, "respaldar", c["nombre"], str(e))
        if adoptar and not fallaron:  # el cambio de servidor ya quedó asentado en todas las carpetas
            huella = json.loads(ruta_huella.read_text(encoding="utf-8"))
            huella.pop("cambio_pendiente", None)
            guardar_json(ruta_huella, huella)
        guardar_json(raiz / "_ultima_copia.json", {
            "fecha": datetime.now().isoformat(timespec="seconds"), "nuevos": nuevos, "carpetas": len(carpetas)})
        log.info(f"Copia local terminada: {nuevos} mensajes nuevos descargados")
        try:  # deja listo el análisis de «Liberar espacio» (solo procesa los correos nuevos)
            import espacio
            espacio.catalogo(cfg, cuenta.correo)
        except Exception as e:
            log.warning(f"No se pudo actualizar el análisis de espacio: {e}")
        return nuevos
    finally:
        conn.cerrar()


class ClavesLocales:
    """Message-ID (o huella, si no tiene) de cada correo que ya está en la copia de una cuenta.
    Se arma una sola vez por copia y solo si hace falta (cuando la cuenta cambió de servidor)."""

    def __init__(self, raiz):
        self.raiz = raiz
        self._claves = None

    def todas(self):
        if self._claves is None:
            claves = set()
            for ind in self.raiz.glob("*/indice.jsonl"):
                for e in leer_indice(ind.parent):
                    if e.get("message_id"):
                        claves.add(e["message_id"])
                        continue
                    try:
                        with open(ind.parent / e["archivo"], "rb") as f:
                            claves.add(huella_cabecera(f.read(262144)))  # la cabecera alcanza
                    except OSError:
                        pass
            self._claves = claves
        return self._claves


def dir_para_carpeta(raiz, c, por_tipo=False):
    """Directorio local de una carpeta del servidor (no lo crea).

    1) la carpeta local con ese nombre, o la que ya se emparejó antes con él (`nombres_servidor`);
    2) con `por_tipo` (al cambiar de servidor): la única carpeta local del mismo tipo, para que
       «Sent» del servidor nuevo siga en «INBOX.Sent» del viejo y no se arme otra carpeta;
    3) una carpeta nueva."""
    nombre = c["nombre"]
    existentes = []
    for ruta in raiz.glob("*/_carpeta.json") if raiz.exists() else []:
        try:
            existentes.append((ruta.parent, json.loads(ruta.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError):
            continue
    for d, meta in existentes:
        if meta.get("nombre") == nombre or nombre in meta.get("nombres_servidor", []):
            return d
    especial = c.get("especial")
    if por_tipo and especial and especial not in ("virtual", "\\all"):
        iguales = [d for d, meta in existentes if meta.get("especial") == especial]
        if len(iguales) == 1:
            return iguales[0]
    return carpeta_local(raiz, nombre)


def leer_vistos(d):
    """{uidvalidity: {uid, …}} de los correos del servidor que ya estaban en la copia y no se bajaron."""
    try:
        return {int(uv): set(uids) for uv, uids in json.loads((d / "_vistos.json").read_text(encoding="utf-8")).items()}
    except (OSError, ValueError, AttributeError):
        return {}


def respaldar_carpeta(conn, c, raiz, cfg, log, correo, prog, adoptar=False, claves=None):
    nombre = c["nombre"]
    w = wire(nombre)
    _, uidvalidity = conn.contar(nombre)
    typ, _ = conn.seleccionar(w, solo_lectura=True)
    if typ != "OK":
        log.warning(f"{nombre}: no se pudo abrir")
        anotar_error(raiz, "respaldar", nombre, "no se pudo abrir la carpeta")
        return 0
    if uidvalidity is None:
        uidvalidity = 0
    reportar(correo, carpeta=nombre)

    d = dir_para_carpeta(raiz, c, por_tipo=adoptar)
    d.mkdir(parents=True, exist_ok=True)
    try:
        previa = json.loads((d / "_carpeta.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        previa = None
    if previa and previa.get("nombre") != nombre:
        # carpeta local de otro servidor (otro nombre): se conservan sus datos y se anota el nombre nuevo
        meta = {**previa, "uidvalidity": uidvalidity}
        if nombre not in meta.get("nombres_servidor", []):
            meta["nombres_servidor"] = [*meta.get("nombres_servidor", []), nombre]
    else:
        meta = {"nombre": nombre, "delim": c["delim"], "flags": c["flags"], "prefijo_origen": c["prefijo"],
                "componentes": c["componentes"], "especial": c["especial"], "uidvalidity": uidvalidity}
        if previa and previa.get("nombres_servidor"):
            meta["nombres_servidor"] = previa["nombres_servidor"]
    guardar_json(d / "_carpeta.json", meta)

    typ, data = conn.cmd(lambda i: i.uid("SEARCH", "ALL"))
    uids = [int(x) for x in (data[0] or b"").split()] if typ == "OK" and data else []
    entradas = leer_indice(d)
    vistos = leer_vistos(d)
    tengo = {(e["uidvalidity"], e["uid"]) for e in entradas} | {(uv, u) for uv, us in vistos.items() for u in us}
    pendientes = [u for u in uids if (uidvalidity, u) not in tengo]
    prog["hechos"] += len(uids) - len(pendientes)

    # Primera vez que se lee esta carpeta desde este servidor (cambio de servidor o UIDVALIDITY nuevo):
    # antes de bajar, se compara la cabecera de cada correo con toda la copia local y los que ya están
    # se anotan como vistos. Así no se duplica ni se vuelve a bajar nada.
    uv_conocido = uidvalidity in vistos or any(e["uidvalidity"] == uidvalidity for e in entradas)
    if pendientes and claves is not None and not uv_conocido and (adoptar or entradas) and claves.todas():
        ya = set()
        for grupo in trozos(pendientes, 300):
            CONTROL.punto()
            typ, data = conn.cmd(lambda i: i.uid("FETCH", conjunto_uid(grupo),
                                                 "(UID BODY.PEEK[HEADER.FIELDS (MESSAGE-ID DATE FROM SUBJECT)])"))
            for item in data or []:
                if isinstance(item, tuple):
                    mu = RE_UID.search(item[0])
                    if mu and clave_mensaje(item[1] + b"\r\n\r\n") in claves.todas():
                        ya.add(int(mu[1]))
        if ya:
            vistos.setdefault(uidvalidity, set()).update(ya)
            guardar_json(d / "_vistos.json", {str(uv): sorted(us) for uv, us in vistos.items()})
            pendientes = [u for u in pendientes if u not in ya]
            prog["hechos"] += len(ya)
            log.info(f"{nombre}: {len(ya)} correos ya estaban en la copia (no se vuelven a bajar)")
    reportar(correo, hechos=prog["hechos"])
    if not pendientes:
        log.info(f"{nombre}: {len(uids)} mensajes, nada nuevo")
        return 0
    log.info(f"{nombre}: {len(uids)} mensajes, {len(pendientes)} por descargar")

    # 1) Datos de cada mensaje: marcas, fecha de recepción y tamaño
    meta = {}
    for grupo in trozos(pendientes, 300):
        typ, data = conn.cmd(lambda i: i.uid("FETCH", conjunto_uid(grupo), "(UID FLAGS INTERNALDATE RFC822.SIZE)"))
        for item in data or []:
            linea = item[0] if isinstance(item, tuple) else item
            if not isinstance(linea, bytes):
                continue
            mu = RE_UID.search(linea)
            if not mu:
                continue
            mf, md, mt = RE_FLAGS.search(linea), RE_FECHA.search(linea), RE_TAM.search(linea)
            meta[int(mu[1])] = {
                "flags": mf[1].decode().split() if mf else [],
                "fecha": md[1].decode() if md else None,
                "tamano": int(mt[1]) if mt else 0,
            }

    # 2) Mensajes completos, en lotes de hasta lote_mb
    lotes, actual, peso = [], [], 0
    for u in pendientes:
        t = meta.get(u, {}).get("tamano", 0)
        if actual and (peso + t > cfg.lote_mb * 1_000_000 or len(actual) >= 200):
            lotes.append(actual)
            actual, peso = [], 0
        actual.append(u)
        peso += t
    if actual:
        lotes.append(actual)

    hechos = 0
    with open(d / "indice.jsonl", "a", encoding="utf-8") as indice:
        for lote in lotes:
            CONTROL.punto()
            typ, data = conn.cmd(lambda i: i.uid("FETCH", conjunto_uid(lote), "(UID BODY.PEEK[])"))
            cuerpos, pendiente = {}, None
            for item in data or []:
                if isinstance(item, tuple):
                    mu = RE_UID.search(item[0])
                    if mu:
                        cuerpos[int(mu[1])], pendiente = item[1], None
                    else:
                        pendiente = item[1]
                elif isinstance(item, bytes) and pendiente is not None:
                    mu = RE_UID.search(item)
                    if mu:
                        cuerpos[int(mu[1])] = pendiente
                    pendiente = None
            for u in lote:
                raw = cuerpos.get(u)
                if raw is None:
                    log.warning(f"{nombre}: el servidor no devolvió el mensaje UID {u}")
                    anotar_error(raiz, "respaldar", nombre, "el servidor no devolvió el mensaje", u)
                    continue
                archivo = f"{uidvalidity}_{u:07d}.eml"
                tmp = d / (archivo + ".tmp")
                tmp.write_bytes(raw)
                os.replace(tmp, d / archivo)
                m = meta.get(u, {})
                indice.write(json.dumps({
                    "uid": u, "uidvalidity": uidvalidity, "archivo": archivo,
                    "flags": m.get("flags", []), "fecha": m.get("fecha"), "tamano": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(), "message_id": extraer_message_id(raw),
                }, ensure_ascii=False) + "\n")
                hechos += 1
                prog["hechos"] += 1
                prog["bytes"] += len(raw)
            indice.flush()
            os.fsync(indice.fileno())
            reportar(correo, hechos=prog["hechos"], bytes=prog["bytes"])
            log.info(f"{nombre}: {hechos}/{len(pendientes)} descargados")
    return hechos


# ---------------------------------------------------------------- subir (disco -> destino)

FLAGS_SUBIBLES = {"\\seen", "\\answered", "\\flagged", "\\draft"}


def info_destino(conn):
    carpetas = conn.listar()
    prefijo, delim = conn.espacio_personal(carpetas)
    delim = delim or next((c["delim"] for c in carpetas if c["delim"]), "/")
    especiales = {}
    for c in carpetas:
        t = tipo_especial(c["flags"], componentes(c["nombre"], c["delim"] or delim, prefijo))
        if t and t not in especiales:
            especiales[t] = c["nombre"]
    return {"prefijo": prefijo, "delim": delim, "especiales": especiales,
            "existentes": {c["nombre"] for c in carpetas}}


def nombre_destino(meta, dest):
    comps = list(meta["componentes"])
    if comps == ["INBOX"]:
        return "INBOX"
    tipo = meta.get("especial")
    if tipo == "\\all":  # «Todos» de Gmail: lo que quede (los archivados) va a Archivo
        return dest["especiales"].get("\\archive") or dest["prefijo"] + "Archivo"
    if tipo and tipo in dest["especiales"]:
        return dest["especiales"][tipo]
    d = dest["delim"]
    comps = [x.replace(d, "-") for x in comps]
    if len(comps) > 1 and comps[0].upper() == "INBOX" and dest["prefijo"].upper().startswith("INBOX"):
        comps = comps[1:]
    return dest["prefijo"] + d.join(comps)


def existe(nombre, dest):
    return nombre in dest["existentes"] or (nombre.upper() == "INBOX")


def asegurar_carpeta(conn, nombre, dest, log):
    if existe(nombre, dest):
        return
    d, pre = dest["delim"], dest["prefijo"]
    partes = nombre[len(pre):].split(d) if nombre.startswith(pre) else nombre.split(d)
    for i in range(1, len(partes) + 1):
        parcial = (pre if nombre.startswith(pre) else "") + d.join(partes[:i])
        if existe(parcial, dest):
            continue
        typ, data = conn.cmd(lambda imap: imap.create(wire(parcial)))
        if typ == "OK":
            log.info(f"Carpeta creada en destino: {parcial}")
        conn.cmd(lambda imap: imap.subscribe(wire(parcial)))
        dest["existentes"].add(parcial)


def ids_en_destino(conn, nombre):
    typ, data = conn.seleccionar(wire(nombre), solo_lectura=True)
    if typ != "OK" or not data or int(data[0] or 0) == 0:
        return set()
    typ, data = conn.cmd(lambda i: i.uid("FETCH", "1:*", "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID DATE FROM SUBJECT)])"))
    return {clave_mensaje(item[1] + b"\r\n\r\n") for item in data or [] if isinstance(item, tuple)}


def plan_de_subida(raiz, excluidos=frozenset()):
    """[(directorio, meta, entradas_a_subir)] de una cuenta, con «Todos» de Gmail depurado.
    `excluidos` son claves "<carpeta en disco>/<archivo>" que «Liberar espacio» deja afuera."""
    dirs = sorted(p.parent for p in raiz.glob("*/_carpeta.json")) if raiz.exists() else []
    plan, en_otras = [], set()
    for d in dirs:
        meta = json.loads((d / "_carpeta.json").read_text(encoding="utf-8"))
        if meta.get("especial") == "virtual":
            continue
        entradas = [e for e in leer_indice(d) if not borrado(e) and f"{d.name}/{e['archivo']}" not in excluidos]
        plan.append((d, meta, entradas))
        if meta.get("especial") != "\\all":
            for e in entradas:
                en_otras.add(e["sha256"])
                if e.get("message_id"):
                    en_otras.add(e["message_id"])
    final = []
    for d, meta, entradas in plan:
        if meta.get("especial") == "\\all":
            entradas = [e for e in entradas
                        if e["sha256"] not in en_otras and (e.get("message_id") or "") not in en_otras]
        final.append((d, meta, entradas))
    final.sort(key=lambda x: x[1].get("especial") == "\\all")
    return final


def subir_cuenta(cuenta, cfg):
    import espacio
    log = log_de(cuenta.correo)
    raiz = cfg.respaldo / segura(cuenta.correo)
    excluidos = espacio.claves_excluidas(cfg, cuenta.correo) if raiz.exists() else frozenset()
    if excluidos:
        log.info(f"Liberar espacio: {len(excluidos)} correos no se suben (quedan en la copia local)")
        espacio.guardar_adjuntos(cfg, cuenta.correo, solo_excluidos=True, log=log)
    plan = plan_de_subida(raiz, excluidos)
    if not plan:
        log.warning("No hay respaldo local de esta cuenta. Ejecutá primero «respaldar».")
        return 0
    reportar(cuenta.correo, fase="conectando", carpeta="")
    conn = conectar(cfg.destino, cuenta.usuario_destino, cuenta.clave_destino, log)
    try:
        dest = info_destino(conn)
        ruta_estado = raiz / f"_subidos_{segura(cfg.destino.host)}_{segura(cuenta.usuario_destino)}.json"
        estado = json.loads(ruta_estado.read_text(encoding="utf-8")) if ruta_estado.exists() else {}
        prog = {"hechos": 0, "bytes": 0}
        reportar(cuenta.correo, fase="subiendo", total=sum(len(p[2]) for p in plan), hechos=0, bytes=0)
        total = 0
        for d, meta, entradas in plan:
            CONTROL.punto()
            try:
                total += subir_carpeta(conn, d, meta, entradas, dest, estado, ruta_estado, raiz, log,
                                       cuenta.correo, prog)
            except imaplib.IMAP4.error as e:
                log.error(f"{meta['nombre']}: {e}")
                anotar_error(raiz, "subir", meta["nombre"], str(e))
            finally:
                guardar_json(ruta_estado, estado)
        log.info(f"Subida terminada: {total} mensajes nuevos en destino")
        return total
    finally:
        conn.cerrar()


def subir_carpeta(conn, d, meta, entradas, dest, estado, ruta_estado, raiz, log, correo, prog):
    nombre_o = meta["nombre"]
    nombre_d = nombre_destino(meta, dest)
    subidos = set(estado.get(nombre_o, []))
    faltan = [e for e in entradas if e["sha256"] not in subidos]
    prog["hechos"] += len(entradas) - len(faltan)
    reportar(correo, hechos=prog["hechos"], carpeta=nombre_o)
    if not faltan:
        log.info(f"{nombre_o} → {nombre_d}: todo subido")
        return 0
    asegurar_carpeta(conn, nombre_d, dest, log)
    ya_estan = ids_en_destino(conn, nombre_d)
    log.info(f"{nombre_o} → {nombre_d}: {len(faltan)} por revisar")

    hechos = vistos = 0
    for e in faltan:
        CONTROL.punto()
        prog["hechos"] += 1
        sha = e["sha256"]
        if sha in subidos:  # copia idéntica dentro de la misma carpeta
            continue
        raw = (d / e["archivo"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != sha:
            log.error(f"{nombre_o}: {e['archivo']} está dañado en el disco, se omite")
            anotar_error(raiz, "subir", nombre_o, "archivo local dañado", e["uid"])
            continue
        if clave_mensaje(raw) in ya_estan:
            subidos.add(sha)
            vistos += 1
            continue
        flags = " ".join(f for f in e["flags"] if f.lower() in FLAGS_SUBIBLES)
        ok, detalle = subir_mensaje(conn, nombre_d, raw, flags, e.get("fecha"), e.get("message_id"), log)
        if ok:
            subidos.add(sha)
            hechos += 1
            prog["bytes"] += len(raw)
            if hechos % 25 == 0:
                estado[nombre_o] = sorted(subidos)
                guardar_json(ruta_estado, estado)
                log.info(f"{nombre_o} → {nombre_d}: {hechos} subidos")
        else:
            log.error(f"{nombre_o}: no se pudo subir {e['archivo']} ({detalle})")
            anotar_error(raiz, "subir", nombre_o, detalle, e["uid"])
        reportar(correo, hechos=prog["hechos"], bytes=prog["bytes"])
    estado[nombre_o] = sorted(subidos)
    extra = f" ({vistos} ya estaban en destino)" if vistos else ""
    log.info(f"{nombre_o} → {nombre_d}: {hechos} subidos{extra}")
    return hechos


def subir_mensaje(conn, carpeta, raw, flags, fecha, message_id, log):
    w = wire(carpeta)
    args = (w, f"({flags})" if flags else None, f'"{fecha}"' if fecha else None, raw)
    for intento in range(1, 4):
        try:
            if conn.imap is None:
                conn.abrir()
                # Si el corte fue después de que el servidor lo guardó, no duplicarlo
                if message_id and intento > 1:
                    conn.cmd(lambda i: i.select(w, readonly=True))
                    typ, data = conn.cmd(lambda i: i.uid("SEARCH", "HEADER", "Message-ID", f'"{message_id}"'))
                    if typ == "OK" and data and data[0] and data[0].strip():
                        return True, ""
            typ, data = conn.imap.append(*args)
            if typ == "OK":
                return True, ""
            return False, (data[0] or b"").decode("utf-8", "replace") if data else typ
        except (imaplib.IMAP4.abort, OSError) as e:
            conn.imap = None
            log.warning(f"Se cortó la conexión al subir ({e}). Reintento {intento}…")
            time.sleep(5 * intento)
        except imaplib.IMAP4.error as e:
            return False, str(e)
    return False, "falló tras 3 intentos"


# ---------------------------------------------------------------- probar y verificar

def mismo_servidor(a, b):
    """True si los dos nombres apuntan a la misma máquina (mismo nombre o misma IP)."""
    if not a or not b:
        return False
    if a.strip().lower() == b.strip().lower():
        return True
    try:
        return socket.gethostbyname(a.strip()) == socket.gethostbyname(b.strip())
    except OSError:
        return False


# Fragmentos del registro MX que delatan al proveedor del correo
MX_CONOCIDOS = (("hostinger", "hostinger"), ("google", "gmail"), ("zoho", "zoho"), ("titan.email", "titan"),
                ("secureserver", "godaddy"), ("ionos", "ionos"), ("kundenserver", "ionos"), ("yahoo", "yahoo"))


def registros_mx(dominio):
    """Servidores de correo (MX) del dominio, con el nslookup del sistema (sin dependencias)."""
    try:
        r = subprocess.run(["nslookup", "-type=mx", dominio], capture_output=True, text=True, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [h.rstrip(".").lower() for h in re.findall(r"mail exchanger\s*=\s*(\S+)", r.stdout or "", re.I)]


def detectar_servidor(correo):
    """Sugiere el servidor IMAP de una casilla mirando a dónde va el correo de su dominio.
    En un hosting propio (cPanel u otro) devuelve el nombre real de la máquina, que no cambia
    cuando se muda el DNS. Devuelve None si no se pudo averiguar."""
    dominio = correo.rsplit("@", 1)[-1].strip().lower()
    if not dominio or "." not in dominio:
        return None
    mx = registros_mx(dominio)
    for host in mx:
        if "outlook.com" in host:
            return {"aviso": f"El correo de {dominio} está en Microsoft 365, que esta app todavía no puede copiar."}
        for fragmento, proveedor in MX_CONOCIDOS:
            if fragmento in host:
                p = PROVEEDORES[proveedor]
                return {"servidor": p["servidor"], "puerto": p["puerto"], "seguridad": p["seguridad"], "verificar": True,
                        "proveedor": proveedor, "como": f"El correo de {dominio} llega a {p['nombre']}."}
    for host in [*mx, f"mail.{dominio}"]:
        try:
            ip = socket.gethostbyname(host)
        except OSError:
            continue
        propio = nombre_inverso(ip)
        return {"servidor": propio or host, "puerto": 993, "seguridad": "ssl", "verificar": True, "proveedor": "cpanel",
                "como": (f"El correo de {dominio} está en {propio}, el nombre real de su servidor (no cambia si se "
                         f"muda el DNS)." if propio else f"El correo de {dominio} llega a {host}.")}
    return None


def probar_servidor(srv):
    """Comprueba que el servidor responde (sin iniciar sesión)."""
    t0 = time.time()
    try:
        imap = Conexion(srv, "", "", None).conectar_sin_login()
        caps = [c for c in imap.capabilities]
        segura_ok = srv.seguridad != "ninguna" or "STARTTLS" in caps
        try:
            imap.logout()
        except Exception:
            pass
        aviso = "" if segura_ok else "La conexión no está cifrada."
        return {"ok": True, "ms": int((time.time() - t0) * 1000), "aviso": aviso}
    except Exception as e:
        return {"ok": False, "error": explicar_error(e)}


def probar_cuenta(cuenta, cfg, origen=True, destino=True):
    log = log_de(cuenta.correo)
    reportar(cuenta.correo, fase="probando")
    res = {"origen": None, "destino": None}
    if origen:
        res["origen"] = probar_lado_origen(cuenta, cfg, log)
    if destino:
        res["destino"] = probar_lado_destino(cuenta, cfg, log)
    return res


def probar_lado_origen(cuenta, cfg, log):
    try:
        conn = conectar(origen_de(cuenta, cfg), cuenta.usuario_origen, cuenta.clave_origen, log)
        try:
            carpetas = carpetas_a_copiar(conn, cfg, log)
            lista = [{"nombre": c["nombre"], "mensajes": conn.contar(c["nombre"])[0] or 0} for c in carpetas]
            cuota = conn.cuota()
            aviso = comprobar_origen(conn, cfg, cuenta, guardar=False)
        finally:
            conn.cerrar()
        if aviso:
            log.warning(aviso)
        total = sum(c["mensajes"] for c in lista)
        log.info(f"Origen OK: {len(lista)} carpetas, {total} mensajes")
        return {"ok": True, "carpetas": lista, "mensajes": total,
                "usado_kb": cuota[0] if cuota else None, "aviso": aviso}
    except Exception as e:
        error = explicar_error(e)
        log.error(f"Origen: {error}")
        return {"ok": False, "error": error}


def probar_lado_destino(cuenta, cfg, log):
    try:
        conn = conectar(cfg.destino, cuenta.usuario_destino, cuenta.clave_destino, log)
        try:
            dest = info_destino(conn)
            cuota = conn.cuota()
        finally:
            conn.cerrar()
        log.info("Destino OK")
        return {"ok": True, "carpetas": len(dest["existentes"]),
                "usado_kb": cuota[0] if cuota else None, "limite_kb": cuota[1] if cuota else None}
    except Exception as e:
        error = explicar_error(e)
        log.error(f"Destino: {error}")
        return {"ok": False, "error": error}


def verificar_cuenta(cuenta, cfg):
    log = log_de(cuenta.correo)
    reportar(cuenta.correo, fase="verificando")
    raiz = cfg.respaldo / segura(cuenta.correo)
    import espacio
    excluidos = espacio.claves_excluidas(cfg, cuenta.correo) if raiz.exists() else frozenset()
    a_subir = {meta["nombre"]: entradas for _, meta, entradas in plan_de_subida(raiz, excluidos)}
    filas = []
    conn_o = conn_d = None
    error_origen = None
    srv = origen_de(cuenta, cfg)
    try:
        # sin el servidor viejo (misma máquina que el nuevo o sin su clave) se compara copia local contra destino
        if mismo_servidor(srv.host, cfg.destino.host):
            raise ValueError("el servidor actual es el mismo que el nuevo")
        if not cuenta.clave_origen:
            raise ValueError("no está la clave del servidor actual")
        conn_o = conectar(srv, cuenta.usuario_origen, cuenta.clave_origen, log)
        carpetas = carpetas_a_copiar(conn_o, cfg, log)
    except Exception as e:
        if not isinstance(e, (imaplib.IMAP4.error, OSError, ValueError)):
            raise
        error_origen = explicar_error(e)
        log.warning(f"No se pudo entrar al servidor actual ({error_origen}). Comparo la copia local con el destino.")
        carpetas = [json.loads((d / "_carpeta.json").read_text(encoding="utf-8"))
                    for d in sorted(p.parent for p in raiz.glob("*/_carpeta.json"))]
        carpetas = [c for c in carpetas if c.get("especial") != "virtual"]
    try:
        conn_d = conectar(cfg.destino, cuenta.usuario_destino, cuenta.clave_destino, log)
        dest = info_destino(conn_d)
        for c in carpetas:
            CONTROL.punto()
            if conn_o:
                n_origen, uidvalidity = conn_o.contar(c["nombre"])
            else:
                n_origen, uidvalidity = None, c.get("uidvalidity")
            d = dir_para_carpeta(raiz, c)
            try:
                nombre_local = json.loads((d / "_carpeta.json").read_text(encoding="utf-8")).get("nombre", c["nombre"])
            except (OSError, json.JSONDecodeError):
                nombre_local = c["nombre"]
            # en la copia están los bajados de este servidor y los que ya estaban (vistos, sin volver a bajar)
            n_locales = sum(1 for e in leer_indice(d) if e["uidvalidity"] == uidvalidity) \
                + len(leer_vistos(d).get(uidvalidity, ()))
            esperados = len({e["sha256"] for e in a_subir.get(nombre_local, []) if e["uidvalidity"] == uidvalidity})
            nombre_d = nombre_destino(c, dest)
            n_dest = (conn_d.contar(nombre_d)[0] or 0) if existe(nombre_d, dest) else 0
            ok = (n_origen is None or n_locales >= n_origen) and n_dest >= esperados
            filas.append({"carpeta": c["nombre"], "origen": n_origen, "local": n_locales,
                          "destino_nombre": nombre_d, "destino": n_dest, "esperados": esperados, "ok": ok})
    finally:
        if conn_o:
            conn_o.cerrar()
        if conn_d:
            conn_d.cerrar()
    ancho = max([len(f["carpeta"]) for f in filas] + [7])
    lineas = [f"{'Carpeta':<{ancho}}  {'Origen':>7}  {'Local':>7}  {'Destino':>7}  Estado"]
    for f in filas:
        lineas.append(f"{f['carpeta']:<{ancho}}  {f['origen'] if f['origen'] is not None else '?':>7}  "
                      f"{f['local']:>7}  {f['destino']:>7}  {'OK' if f['ok'] else 'FALTA'}")
    log.info("Comparación de conteos:\n" + "\n".join(lineas))
    return {"filas": filas, "ok": all(f["ok"] for f in filas), "error_origen": error_origen}


# ---------------------------------------------------------------- orquestación

ACCIONES = {
    "probar": ("Probar conexiones", True, True),
    "probar_origen": ("Probar el servidor actual", True, False),
    "probar_destino": ("Probar el servidor nuevo", False, True),
    "respaldar": ("Copia local (respaldar origen en disco)", True, False),
    "subir": ("Subir respaldo a destino", False, True),
    "migrar": ("Migrar todo (respaldar + subir)", True, True),
    "verificar": ("Verificar conteos", True, True),
    "adjuntos": ("Guardar aparte los adjuntos de lo que no se sube", False, False),
    "adjuntos_todos": ("Guardar aparte todos los adjuntos", False, False),
}


def procesar(cuenta, cfg, accion):
    CONTROL.punto()
    if accion == "probar":
        return probar_cuenta(cuenta, cfg)
    if accion == "probar_origen":
        return probar_cuenta(cuenta, cfg, destino=False)
    if accion == "probar_destino":
        return probar_cuenta(cuenta, cfg, origen=False)
    if accion == "respaldar":
        return {"descargados": respaldar_cuenta(cuenta, cfg)}
    if accion == "subir":
        return {"subidos": subir_cuenta(cuenta, cfg)}
    if accion == "migrar":
        bajados = respaldar_cuenta(cuenta, cfg)
        return {"descargados": bajados, "subidos": subir_cuenta(cuenta, cfg)}
    if accion == "verificar":
        return verificar_cuenta(cuenta, cfg)
    if accion in ("adjuntos", "adjuntos_todos"):
        import espacio
        reportar(cuenta.correo, fase="probando")
        return espacio.guardar_adjuntos(cfg, cuenta.correo, solo_excluidos=accion == "adjuntos", log=log_de(cuenta.correo))


@contextmanager
def bloqueo(cfg):
    """Impide que dos procesos escriban la copia local a la vez (la app y la copia automática).
    Usa un bloqueo del sistema sobre un archivo: si el proceso muere, Windows lo libera solo."""
    cfg.respaldo.mkdir(parents=True, exist_ok=True)
    f = open(cfg.respaldo / ".en_uso", "a+")
    try:
        f.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise EnUso("Ya hay otra copia o migración en marcha (puede ser la copia automática). "
                        "Esperá a que termine y volvé a intentar.") from None
        yield
    finally:
        f.close()


def ejecutar_cuentas(accion, cuentas, cfg):
    """Corre la acción para cada cuenta en paralelo. Devuelve {correo: {ok, resultado|error}}."""
    resultados = {}
    for c in cuentas:
        reportar(c.correo, fase="en_cola", hechos=0, total=0, bytes=0, carpeta="", error=None, resultado=None)
    if accion in ("respaldar", "subir", "migrar"):
        try:
            with bloqueo(cfg):
                return _ejecutar_en_paralelo(accion, cuentas, cfg, resultados)
        except EnUso as e:
            for c in cuentas:
                resultados[c.correo] = {"ok": False, "error": str(e)}
                reportar(c.correo, fase="error", error=str(e))
            log_de("-").error(str(e))
            return resultados
    return _ejecutar_en_paralelo(accion, cuentas, cfg, resultados)


def _ejecutar_en_paralelo(accion, cuentas, cfg, resultados):
    with ThreadPoolExecutor(max_workers=cfg.hilos) as pool:
        futuros = {pool.submit(procesar, c, cfg, accion): c for c in cuentas}
        for fut in as_completed(futuros):
            c = futuros[fut]
            try:
                r = fut.result()
                resultados[c.correo] = {"ok": True, "resultado": r}
                reportar(c.correo, fase="listo", resultado=r)
            except Cancelado:
                resultados[c.correo] = {"ok": False, "error": "Cancelado"}
                reportar(c.correo, fase="cancelado")
            except Exception as e:
                msg = explicar_error(e)
                resultados[c.correo] = {"ok": False, "error": msg}
                log_de(c.correo).error(f"Falló: {msg}")
                reportar(c.correo, fase="error", error=msg)
    return resultados


RUTA_AUTOMATICA = BASE / "automatica.json"


def ejecutar_automatica():
    """La corre la tarea programada: copia local de todas las cuentas, sin ventanas ni preguntas.
    Deja el resultado en automatica.json para que la app lo muestre."""
    archivo = preparar_registro("auto_respaldar", consola=False)
    general = log_de("-")
    errores, nuevos, cuentas = {}, 0, []
    try:
        cfg = config_desde_dict(leer_config_dict())
        guardadas = leer_claves()
        for c in leer_cuentas_dicts():
            clave = c.get("clave_origen") or guardadas.get(c["correo"], {}).get("clave_origen")
            if clave:
                cuentas.append(cuenta_desde_dict({**c, "clave_origen": clave}))
            else:
                errores[c["correo"]] = "No hay clave guardada para esta cuenta."
        general.info(f"Copia automática · {len(cuentas)} cuenta(s) · respaldo en {cfg.respaldo}")
        if cuentas:
            for correo, r in ejecutar_cuentas("respaldar", cuentas, cfg).items():
                if r["ok"]:
                    nuevos += r["resultado"].get("descargados", 0)
                else:
                    errores[correo] = r["error"]
    except Exception as e:
        errores["-"] = explicar_error(e)
        general.error(f"La copia automática falló: {errores['-']}")
    resumen = {"fecha": datetime.now().isoformat(timespec="seconds"), "ok": not errores,
               "cuentas": len(cuentas), "nuevos": nuevos, "errores": errores, "registro": str(archivo)}
    guardar_json(RUTA_AUTOMATICA, resumen)
    general.info("Copia automática terminada sin errores." if not errores else f"Copia automática con errores: {errores}")
    return not errores


def ejecutar(accion, filtro=None):
    cfg = cargar_config()
    cuentas = cargar_cuentas(filtro)
    _, origen, destino = ACCIONES[accion]
    pedir_claves(cuentas, origen, destino)
    archivo = preparar_registro(accion)
    general = log_de("-")
    general.info(f"{ACCIONES[accion][0]} · {len(cuentas)} cuenta(s) · respaldo en {cfg.respaldo}")
    resultados = ejecutar_cuentas(accion, cuentas, cfg)
    errores = [c for c, r in resultados.items() if not r["ok"]]
    if errores:
        general.error(f"Terminó con errores en: {', '.join(errores)}")
    else:
        general.info("Terminado sin errores.")
    general.info(f"Registro completo en {archivo}")
    return not errores


def menu():
    opciones = list(ACCIONES)
    while True:
        print("\n=== Migrador de correos IMAP ===")
        for i, a in enumerate(opciones, 1):
            print(f"  {i}. {ACCIONES[a][0]}")
        print("  0. Salir")
        elegido = input("Opción: ").strip()
        if elegido == "0":
            return
        if elegido.isdigit() and 1 <= int(elegido) <= len(opciones):
            filtro = input("¿Solo una cuenta? Escribí el correo o dejalo vacío para todas: ").strip() or None
            ejecutar(opciones[int(elegido) - 1], filtro)


def main():
    p = argparse.ArgumentParser(description="Migra cuentas de correo de un servidor IMAP a otro.")
    p.add_argument("accion", nargs="?", choices=list(ACCIONES))
    p.add_argument("--cuenta", help="procesar solo esta cuenta")
    p.add_argument("--automatica", action="store_true",
                   help="modo de la copia automática programada: sin preguntas ni ventana, usa las claves guardadas")
    a = p.parse_args()
    if a.automatica:
        sys.exit(0 if ejecutar_automatica() else 1)
    if a.accion:
        sys.exit(0 if ejecutar(a.accion, a.cuenta) else 1)
    menu()


if __name__ == "__main__":
    main()
