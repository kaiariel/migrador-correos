#!/usr/bin/env python3
"""Interfaz visual del migrador: sirve una página local y la abre como ventana.

Solo escucha en 127.0.0.1 y exige un token aleatorio por sesión, así que ninguna
otra página ni otro equipo puede usarla. Las claves quedan en memoria salvo que
se marque «Recordar claves».
"""

import hashlib
import json
import logging
import os
import queue
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import espacio
import migrador as m
import programador

UI = m.BASE / "ui"
TOKEN = secrets.token_urlsafe(24)
RUTA_ESTADO_APP = m.BASE / "estado_app.json"
TIPOS = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml"}


# ---------------------------------------------------------------- estado compartido

class Estado:
    def __init__(self):
        self.lock = threading.RLock()
        self.claves = {}       # correo -> {"clave_origen", "clave_destino"}, solo en memoria
        self.trabajo = {"accion": None, "estado": "libre", "inicio": None, "fin": None, "cuentas": []}
        self.cuentas = {}      # progreso por cuenta
        self.log = []
        self.sucias = set()
        self.clientes = []
        self.resultados = {}   # accion -> {correo: resultado}
        self.app = self._leer_app()
        self.puerto = None
        self.servidor = None

    def _leer_app(self):
        try:
            return json.loads(RUTA_ESTADO_APP.read_text(encoding="utf-8"))
        except Exception:
            return {"checklist": {}, "historial": []}

    def guardar_app(self):
        m.guardar_json(RUTA_ESTADO_APP, self.app)

    def emitir(self, evento):
        for q in list(self.clientes):
            try:
                q.put_nowait(evento)
            except queue.Full:
                pass

    def actualizar(self, correo, campos):
        with self.lock:
            c = self.cuentas.setdefault(correo, {"fase": "en_cola", "descarga": None, "subida": None})
            fase = campos.get("fase")
            if fase == "en_cola":
                c.update({"descarga": None, "subida": None, "error": None, "resultado": None, "carpeta": ""})
            if fase:
                c["fase"] = fase
            etapa = {"descargando": "descarga", "subiendo": "subida"}.get(c["fase"])
            if etapa and "total" in campos:
                c[etapa] = {"hechos": 0, "total": campos["total"], "bytes": 0, "t0": time.time()}
            for k in ("hechos", "bytes"):
                if k in campos and etapa and c.get(etapa):
                    c[etapa][k] = campos[k]
            for k in ("carpeta", "error", "resultado"):
                if k in campos:
                    c[k] = campos[k]
            self.sucias.add(correo)

    def instantanea(self):
        with self.lock:
            return json.loads(json.dumps(self.cuentas))


E = Estado()
m.al_reportar(E.actualizar)


class ManejadorUI(logging.Handler):
    def emit(self, record):
        linea = {"hora": datetime.fromtimestamp(record.created).strftime("%H:%M:%S"),
                 "nivel": record.levelname, "cuenta": getattr(record, "cuenta", "-"),
                 "texto": record.getMessage()}
        with E.lock:
            E.log.append(linea)
            del E.log[:-1500]
        E.emitir({"tipo": "log", "linea": linea})


m.LOG.addHandler(ManejadorUI())


def vaciar_progreso():
    with E.lock:
        if not E.sucias:
            return
        datos = {c: json.loads(json.dumps(E.cuentas[c])) for c in E.sucias}
        E.sucias.clear()
    E.emitir({"tipo": "cuentas", "datos": datos})


def difusor():
    """Envía el progreso acumulado cada 300 ms (evita inundar la página)."""
    while True:
        time.sleep(0.3)
        vaciar_progreso()


# ---------------------------------------------------------------- datos para la página

def cargar_claves_guardadas():
    E.claves = m.leer_claves()
    # Versiones anteriores guardaban las claves sin cifrar en cuentas.csv: se pasan al almacén cifrado.
    cuentas = m.leer_cuentas_dicts()
    viejas = {c["correo"]: {"clave_origen": c["clave_origen"], "clave_destino": c["clave_destino"]}
              for c in cuentas if c["clave_origen"] or c["clave_destino"]}
    if viejas:
        for correo, k in viejas.items():
            E.claves.setdefault(correo, k)
        if E.app.get("recordar") and m.CLAVES_CIFRABLES:
            m.guardar_claves(E.claves)
        m.escribir_cuentas_dicts(cuentas)


_NOMBRES_POR_IP = {}


def nombre_por_ip(ip):
    """Nombre propio del servidor para huellas viejas que no lo guardaron (se consulta una sola vez)."""
    if ip and ip not in _NOMBRES_POR_IP:
        _NOMBRES_POR_IP[ip] = m.nombre_inverso(ip)
    return _NOMBRES_POR_IP.get(ip)


def resumen_local(cfg):
    res = {}
    for c in m.leer_cuentas_dicts():
        raiz = cfg.respaldo / m.segura(c["correo"])
        mensajes = bytes_ = carpetas = 0
        fecha = nombre_servidor = None
        if raiz.exists():
            carpetas = len(list(raiz.glob("*/_carpeta.json")))
            for ind in raiz.glob("*/indice.jsonl"):
                for e in m.leer_indice(ind.parent):
                    mensajes += 1
                    bytes_ += e.get("tamano", 0)
            try:
                fecha = json.loads((raiz / "_ultima_copia.json").read_text(encoding="utf-8"))["fecha"]
            except Exception:  # copias hechas con versiones anteriores: la fecha del índice más reciente
                indices = list(raiz.glob("*/indice.jsonl"))
                if mensajes and indices:
                    ultima = max(i.stat().st_mtime for i in indices)
                    fecha = datetime.fromtimestamp(ultima).isoformat(timespec="seconds")
            try:
                huella = json.loads((raiz / "_origen.json").read_text(encoding="utf-8"))
                nombre_servidor = huella.get("nombre_servidor") or nombre_por_ip(huella.get("ip"))
            except Exception:
                pass
        res[c["correo"]] = {"mensajes": mensajes, "bytes": bytes_, "carpetas": carpetas, "fecha": fecha,
                            "nombre_servidor": nombre_servidor}
    return res


AUTOMATICA_POR_DEFECTO = {"activa": False, "dias": ["domingo"], "hora": "22:00"}


def estado_automatica():
    conf = {**AUTOMATICA_POR_DEFECTO, **E.app.get("automatica", {})}
    try:
        ultima = json.loads(m.RUTA_AUTOMATICA.read_text(encoding="utf-8"))
    except Exception:
        ultima = None
    existe = programador.existe() if conf["activa"] else False
    prox = programador.proxima(conf["dias"], conf["hora"]) if conf["activa"] else None
    return {**conf, "disponible": programador.DISPONIBLE, "tarea_existe": existe,
            "proxima": prox.isoformat(timespec="minutes") if prox else None, "ultima": ultima}


def configurar_automatica(datos):
    activa = bool(datos.get("activa"))
    dias = [d for d in programador.DIAS if d in (datos.get("dias") or [])]
    hora = str(datos.get("hora") or "22:00")
    try:
        h, mi = (int(x) for x in hora.split(":"))
        assert 0 <= h < 24 and 0 <= mi < 60
        hora = f"{h:02d}:{mi:02d}"
    except Exception:
        return {"ok": False, "error": "La hora no es válida.", "automatica": estado_automatica()}
    if activa and not E.app.get("recordar"):
        return {"ok": False, "error": "Primero activá «Guardar las claves en este equipo» en el paso Cuentas: "
                                      "la copia automática las necesita.", "automatica": estado_automatica()}
    if activa:
        ok, error = programador.programar(dias, hora)
    else:
        ok, error = programador.desprogramar()
    with E.lock:
        E.app["automatica"] = {"activa": activa and ok, "dias": dias or ["domingo"], "hora": hora}
        E.guardar_app()
    return {"ok": ok, "error": error, "automatica": estado_automatica()}


def liberar_espacio(datos):
    """Evalúa (y si viene `filtro`, guarda) qué correos de una cuenta no se suben al servidor nuevo."""
    correo = str(datos.get("correo") or "").strip()
    if not any(c["correo"].lower() == correo.lower() for c in m.leer_cuentas_dicts()):
        return {"ok": False, "error": "Esa cuenta no está en la lista."}
    cfg = m.config_desde_dict(m.leer_config_dict())
    if not (cfg.respaldo / m.segura(correo)).exists():
        return {"ok": False, "error": "Esta cuenta todavía no tiene copia local: hacela en el paso 3."}
    if isinstance(datos.get("filtro"), dict):
        espacio.guardar_filtro(correo, {**espacio.filtro_de(correo), **datos["filtro"]})
    r = espacio.evaluar(cfg, correo)
    if not r["filtro"]["limite_mb"]:  # sugerir el límite real si ya se probó el servidor nuevo
        prueba = (E.resultados.get("probar_destino") or E.resultados.get("probar") or {}).get(correo)
        limite_kb = prueba and prueba.get("ok") and (prueba["resultado"].get("destino") or {}).get("limite_kb")
        r["limite_sugerido_mb"] = round(limite_kb / 1024) if limite_kb else None
    return {"ok": True, **r}


def automatica_ahora(_):
    if not programador.existe():
        return {"ok": False, "error": "La copia automática no está activada."}
    ok, error = programador.ejecutar_ahora()
    return {"ok": ok, "error": error}


def cuentas_publicas():
    lista = []
    for c in m.leer_cuentas_dicts():
        k = E.claves.get(c["correo"], {})
        lista.append({"correo": c["correo"], "correo_destino": c["correo_destino"],
                      "tiene_clave_origen": bool(k.get("clave_origen")),
                      "tiene_clave_destino": bool(k.get("clave_destino")),
                      **{campo: c[campo] for campo in m.CAMPOS_SERVIDOR}})
    return lista


def estado_completo():
    cfg_dict = m.leer_config_dict()
    cfg = m.config_desde_dict(cfg_dict)
    automatica = estado_automatica()
    ultima = automatica.get("ultima") or {}
    with E.lock:
        # una copia automática exitosa también cuenta como «copia local completa»
        if ultima.get("ok") and ultima.get("cuentas") and ultima["fecha"] > E.app.get("ultima_copia", ""):
            E.app["ultima_copia"] = ultima["fecha"]
            E.guardar_app()
        return {
            "config": cfg_dict,
            "proveedores": m.PROVEEDORES,
            "cuentas": cuentas_publicas(),
            "recordar": bool(E.app.get("recordar")),
            "claves_cifrables": m.CLAVES_CIFRABLES,
            "trabajo": dict(E.trabajo),
            "progreso": E.instantanea(),
            "log": E.log[-300:],
            "resultados": E.resultados,
            "app": E.app,
            "local": resumen_local(cfg),
            "automatica": automatica,
            "filtros": espacio.leer_filtros(),
        }


# ---------------------------------------------------------------- acciones

def guardar_cuentas(datos):
    nuevas, vistos = [], set()
    previas = {c["correo"].lower(): c for c in m.leer_cuentas_dicts()}
    for c in datos.get("cuentas", []):
        correo = (c.get("correo") or "").strip()
        if not correo or correo.lower() in vistos:
            continue
        vistos.add(correo.lower())
        k = E.claves.setdefault(correo, {"clave_origen": "", "clave_destino": ""})
        for campo in ("clave_origen", "clave_destino"):
            if c.get(campo) is not None:  # None = sin cambios
                k[campo] = c[campo]
        # El servidor propio: si el pedido no lo trae, se conserva el que ya tenía (nunca se pierde sin querer)
        previa = previas.get(correo.lower(), {})
        servidor = {campo: (c[campo] if campo in c else previa.get(campo, "")) for campo in m.CAMPOS_SERVIDOR}
        nuevas.append({"correo": correo, "correo_destino": (c.get("correo_destino") or "").strip(), **k, **servidor})
    for correo in list(E.claves):
        if correo.lower() not in vistos:
            del E.claves[correo]
    E.app["recordar"] = bool(datos.get("recordar")) and m.CLAVES_CIFRABLES
    E.guardar_app()
    m.escribir_cuentas_dicts(nuevas)
    apagada = False
    if E.app["recordar"]:
        m.guardar_claves(E.claves)
    else:
        m.borrar_claves()
        if E.app.get("automatica", {}).get("activa"):
            programador.desprogramar()
            E.app["automatica"]["activa"] = False
            E.guardar_app()
            apagada = True
    return {"ok": True, "cuentas": cuentas_publicas(), "automatica_apagada": apagada,
            "automatica": estado_automatica()}


def guardar_config(datos):
    d = m.leer_config_dict()
    for lado in ("origen", "destino"):
        if lado in datos:
            s = datos[lado]
            d[lado].update({
                "proveedor": s.get("proveedor", d[lado]["proveedor"]),
                "servidor": str(s.get("servidor", "")).strip(),
                "puerto": int(s.get("puerto") or 993),
                "seguridad": s.get("seguridad") if s.get("seguridad") in ("ssl", "starttls", "ninguna") else "ssl",
                "verificar": bool(s.get("verificar", True)),
            })
    if "general" in datos:
        g = datos["general"]
        excluir = g.get("excluir_carpetas", d["general"]["excluir_carpetas"])
        if isinstance(excluir, str):
            excluir = [x.strip() for x in excluir.split(",") if x.strip()]
        d["general"].update({
            "carpeta_respaldo": str(g.get("carpeta_respaldo") or d["general"]["carpeta_respaldo"]).strip(),
            "excluir_carpetas": excluir,
            "cuentas_a_la_vez": max(1, min(6, int(g.get("cuentas_a_la_vez") or 2))),
            "lote_mb": max(1, min(200, int(g.get("lote_mb") or 20))),
        })
    m.escribir_config_dict(d)
    return {"ok": True, "config": d}


def probar_servidor(datos):
    s = datos["servidor"]
    srv = m.Servidor(host=str(s.get("servidor", "")).strip(), puerto=int(s.get("puerto") or 993),
                     seguridad=s.get("seguridad", "ssl"), verificar=bool(s.get("verificar", True)))
    return m.probar_servidor(srv)


def detectar_servidor(datos):
    r = m.detectar_servidor(str(datos.get("correo", "")))
    return {"ok": bool(r and r.get("servidor")), **(r or {"aviso": "No pude averiguar el servidor de ese dominio."})}


def lanzar(datos):
    accion = datos.get("accion")
    if accion not in m.ACCIONES:
        return {"ok": False, "error": "Acción desconocida"}
    with E.lock:
        if E.trabajo["estado"] in ("corriendo", "pausado"):
            return {"ok": False, "error": "Ya hay una tarea en marcha."}
    cfg_dict = m.leer_config_dict()
    cfg = m.config_desde_dict(cfg_dict)
    _, usa_origen, usa_destino = m.ACCIONES[accion]
    if accion == "verificar":  # verificar puede comparar solo copia local contra destino
        usa_origen = False

    elegidas = set(x.lower() for x in datos.get("correos") or [])
    cuentas = []
    sin_clave = []
    for c in m.leer_cuentas_dicts():
        if elegidas and c["correo"].lower() not in elegidas:
            continue
        k = E.claves.get(c["correo"], {})
        c = {**c, "clave_origen": k.get("clave_origen", ""), "clave_destino": k.get("clave_destino", "")}
        if (usa_origen and not c["clave_origen"]) or (usa_destino and not (c["clave_destino"] or c["clave_origen"])):
            sin_clave.append(c["correo"])
        cuentas.append(m.cuenta_desde_dict(c))
    if not cuentas:
        return {"ok": False, "error": "No hay cuentas para procesar."}

    # cada cuenta usa su propio servidor o, si no tiene, el servidor actual general
    sin_servidor = [c.correo for c in cuentas if not m.origen_de(c, cfg).host]
    if m.ACCIONES[accion][1] and sin_servidor:
        return {"ok": False, "error": "Falta el servidor actual de: " + ", ".join(sin_servidor)
                + ". Configuralo en el paso 1 o en la cuenta."}
    if usa_destino and not cfg.destino.host:
        return {"ok": False, "error": "Falta configurar el servidor de destino."}
    if usa_destino and accion != "verificar":
        iguales = [c.correo for c in cuentas if m.mismo_servidor(m.origen_de(c, cfg).host, cfg.destino.host)]
        if iguales:
            return {"ok": False, "error": f"Estas cuentas ya están en el servidor nuevo ({cfg.destino.host}): "
                                          + ", ".join(iguales) + ". Sacalas de la selección; si el servidor nuevo "
                                          "está mal, cambialo en el paso 4."}
    if sin_clave:
        return {"ok": False, "error": "Falta la clave de: " + ", ".join(sin_clave)}

    m.CONTROL.reiniciar()
    with E.lock:
        for c in cuentas:
            E.cuentas.pop(c.correo, None)
        E.trabajo = {"accion": accion, "estado": "corriendo", "inicio": time.time(), "fin": None,
                     "cuentas": [c.correo for c in cuentas]}
    E.emitir({"tipo": "trabajo", "trabajo": dict(E.trabajo)})

    def correr():
        archivo = m.preparar_registro(accion, consola=True)
        log = m.log_de("-")
        log.info(f"{m.ACCIONES[accion][0]} · {len(cuentas)} cuenta(s)")
        try:
            res = m.ejecutar_cuentas(accion, cuentas, cfg)
        except Exception as e:  # no debería pasar: ejecutar_cuentas captura por cuenta
            res = {c.correo: {"ok": False, "error": m.explicar_error(e)} for c in cuentas}
        cancelado = m.CONTROL.cancelar.is_set()
        todo_ok = all(r["ok"] for r in res.values())
        ahora = datetime.now().isoformat(timespec="seconds")
        with E.lock:
            E.resultados.setdefault(accion, {}).update(res)
            E.trabajo.update({"estado": "cancelado" if cancelado else "terminado", "fin": time.time(),
                              "ok": todo_ok and not cancelado})
            completo = todo_ok and not cancelado
            if accion == "migrar" and completo:
                E.app["ultima_migracion"] = ahora
            if accion in ("respaldar", "migrar") and completo:
                E.app["ultima_copia"] = ahora
            if accion == "verificar" and not cancelado:
                bien = completo and all(r["resultado"]["ok"] for r in res.values())
                E.app["ultima_verificacion"] = {"fecha": ahora, "ok": bien}
            if not accion.startswith("probar"):
                E.app.setdefault("historial", []).append(
                    {"fecha": ahora, "accion": accion, "cuentas": len(cuentas),
                     "resultado": "cancelado" if cancelado else ("ok" if todo_ok else "con errores")})
                E.app["historial"] = E.app["historial"][-30:]
            E.guardar_app()
        log.info("Cancelado." if cancelado else ("Terminado sin errores." if todo_ok else "Terminado con errores."))
        log.info(f"Registro completo en {archivo}")
        vaciar_progreso()  # que la página reciba el último estado de cada cuenta antes del aviso de fin
        E.emitir({"tipo": "trabajo", "trabajo": dict(E.trabajo), "resultados": E.resultados, "app": E.app})

    threading.Thread(target=correr, daemon=True).start()
    return {"ok": True}


def pausar(_):
    with E.lock:
        if E.trabajo["estado"] != "corriendo":
            return {"ok": False}
        m.CONTROL.seguir.clear()
        E.trabajo["estado"] = "pausado"
    m.log_de("-").info("En pausa (termina la tanda en curso y espera).")
    E.emitir({"tipo": "trabajo", "trabajo": dict(E.trabajo)})
    return {"ok": True}


def reanudar(_):
    with E.lock:
        if E.trabajo["estado"] != "pausado":
            return {"ok": False}
        m.CONTROL.seguir.set()
        E.trabajo["estado"] = "corriendo"
    m.log_de("-").info("Reanudado.")
    E.emitir({"tipo": "trabajo", "trabajo": dict(E.trabajo)})
    return {"ok": True}


def cancelar(_):
    with E.lock:
        if E.trabajo["estado"] not in ("corriendo", "pausado"):
            return {"ok": False}
        m.CONTROL.cancelar.set()
        m.CONTROL.seguir.set()
        E.trabajo["estado"] = "cancelando"
    m.log_de("-").info("Cancelando… (lo descargado queda guardado; la próxima vez sigue desde ahí)")
    E.emitir({"tipo": "trabajo", "trabajo": dict(E.trabajo)})
    return {"ok": True}


def abrir(datos):
    cfg = m.config_desde_dict(m.leer_config_dict())
    ruta = {"respaldo": cfg.respaldo, "registros": m.BASE / "registros",
            "adjuntos": espacio.carpeta_adjuntos(cfg)}.get(datos.get("que"))
    if ruta is None:
        return {"ok": False}
    ruta.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(ruta)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(ruta)])
    return {"ok": True}


def marcar(datos):
    item = str(datos.get("item"))
    with E.lock:
        lista = E.app.setdefault("checklist", {})
        if datos.get("hecho"):
            lista[item] = datetime.now().isoformat(timespec="seconds")
        else:
            lista.pop(item, None)
        E.guardar_app()
    return {"ok": True, "app": E.app}


def salir(_):
    with E.lock:
        if E.trabajo["estado"] in ("corriendo", "pausado", "cancelando"):
            return {"ok": False, "error": "Hay una tarea en curso."}
    threading.Thread(target=lambda: (time.sleep(0.3), E.servidor.shutdown()), daemon=True).start()
    return {"ok": True}


RUTAS_POST = {
    "/api/config": guardar_config, "/api/cuentas": guardar_cuentas, "/api/probar-servidor": probar_servidor,
    "/api/detectar-servidor": detectar_servidor,
    "/api/accion": lanzar, "/api/pausar": pausar, "/api/reanudar": reanudar, "/api/cancelar": cancelar,
    "/api/abrir": abrir, "/api/checklist": marcar,
    "/api/automatica": configurar_automatica, "/api/automatica-ahora": automatica_ahora,
    "/api/salir": salir, "/api/espacio": liberar_espacio,
}


# ---------------------------------------------------------------- servidor HTTP

class Manejador(BaseHTTPRequestHandler):
    server_version = "Migrador"

    def log_message(self, *args):
        pass

    def _host_valido(self):
        return self.headers.get("Host") in (f"127.0.0.1:{E.puerto}", f"localhost:{E.puerto}")

    def _token(self, qs):
        return secrets.compare_digest(self.headers.get("X-Token") or (qs.get("t") or [""])[0], TOKEN)

    def _responder(self, codigo, cuerpo, tipo="application/json; charset=utf-8"):
        datos = cuerpo if isinstance(cuerpo, bytes) else json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(datos)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(datos)

    def do_GET(self):
        if not self._host_valido():
            return self._responder(403, b"Acceso no permitido", "text/plain; charset=utf-8")
        url = urlparse(self.path)
        qs = parse_qs(url.query)
        if url.path == "/":
            if not self._token(qs):
                return self._responder(403, "Abrí el migrador desde Migrador.bat.".encode(), "text/plain; charset=utf-8")
            html = (UI / "index.html").read_text(encoding="utf-8").replace("{{TOKEN}}", TOKEN)
            return self._responder(200, html.encode("utf-8"), TIPOS[".html"])
        if url.path.startswith("/ui/"):
            ruta = (UI / url.path[4:]).resolve()
            if UI.resolve() not in ruta.parents or not ruta.is_file():
                return self._responder(404, b"No existe", "text/plain")
            return self._responder(200, ruta.read_bytes(), TIPOS.get(ruta.suffix, "application/octet-stream"))
        if not self._token(qs):
            return self._responder(403, {"error": "token"})
        if url.path == "/api/estado":
            return self._responder(200, estado_completo())
        if url.path == "/api/eventos":
            return self._eventos()
        self._responder(404, {"error": "no existe"})

    def do_POST(self):
        url = urlparse(self.path)
        if not self._host_valido() or not self._token({}):
            return self._responder(403, {"error": "acceso no permitido"})
        fn = RUTAS_POST.get(url.path)
        if not fn:
            return self._responder(404, {"error": "no existe"})
        largo = int(self.headers.get("Content-Length") or 0)
        try:
            datos = json.loads(self.rfile.read(largo) or b"{}")
            self._responder(200, fn(datos))
        except Exception as e:
            self._responder(200, {"ok": False, "error": m.explicar_error(e)})

    def _eventos(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        q = queue.Queue(maxsize=2000)
        E.clientes.append(q)
        try:
            while True:
                try:
                    ev = q.get(timeout=15)
                    trozo = f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                except queue.Empty:
                    trozo = ": latido\n\n"
                self.wfile.write(trozo.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            E.clientes.remove(q)


def abrir_ventana(url):
    """Abre como ventana de aplicación (Edge o Chrome en modo --app); si no, en el navegador."""
    candidatos = [
        shutil.which("msedge"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    for exe in candidatos:
        if exe and os.path.isfile(exe):
            subprocess.Popen([exe, f"--app={url}", "--window-size=1320,900"])
            return
    webbrowser.open(url)


class ServidorExclusivo(ThreadingHTTPServer):
    """No comparte el puerto: en Windows, SO_REUSEADDR deja «robar» un puerto que ya usa otra app."""
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def puerto_ocupado(puerto):
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", puerto)) == 0


PUERTO_INICIAL = 47615


# ---------------------------------------------------------------- una sola app abierta

RUTA_INSTANCIA = Path(os.environ.get("MIGRADOR_INSTANCIA")  # otra ubicación, solo para pruebas
                      or m.RUTA_CLAVES.parent / "instancia.json")


def version_codigo():
    """Cambia cuando se actualiza cualquier archivo del programa (para reemplazar una app vieja abierta)."""
    archivos = [m.BASE / "app.py", m.BASE / "migrador.py", m.BASE / "programador.py", *sorted(UI.glob("*"))]
    return hashlib.sha1("|".join(f"{a.name}:{a.stat().st_mtime_ns}:{a.stat().st_size}"
                                 for a in archivos if a.is_file()).encode()).hexdigest()[:12]


def pedir_a_instancia(info, ruta, datos=None):
    req = urllib.request.Request(f"http://127.0.0.1:{info['puerto']}{ruta}",
                                 data=None if datos is None else json.dumps(datos).encode(),
                                 headers={"X-Token": info["token"], "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3) as r:
        return json.loads(r.read() or b"{}")


def instancia_abierta(version):
    """Si ya hay una app abierta, abre su ventana y devuelve True. Si es de una versión anterior y
    está libre, le pide que se cierre y devuelve False (para arrancar la nueva)."""
    try:
        info = json.loads(RUTA_INSTANCIA.read_text(encoding="utf-8"))
        estado = pedir_a_instancia(info, "/api/estado")
    except Exception:
        return False
    url = f"http://127.0.0.1:{info['puerto']}/?t={info['token']}"
    ocupada = estado.get("trabajo", {}).get("estado") in ("corriendo", "pausado", "cancelando")
    if info.get("version") == version or ocupada:
        if ocupada and info.get("version") != version:
            print("Hay una tarea en curso en la versión anterior de la app: abro esa. "
                  "Cuando termine, cerrala y volvé a abrir para usar la versión nueva.")
        abrir_ventana(url)
        return True
    try:
        pedir_a_instancia(info, "/api/salir", {})
    except Exception:
        pass
    for _ in range(30):  # esperar a que suelte el puerto
        if not puerto_ocupado(info["puerto"]):
            break
        time.sleep(0.2)
    return False


def registrar_instancia(version):
    RUTA_INSTANCIA.parent.mkdir(parents=True, exist_ok=True)
    m.guardar_json(RUTA_INSTANCIA, {"puerto": E.puerto, "token": TOKEN, "pid": os.getpid(), "version": version})


def olvidar_instancia():
    try:
        if json.loads(RUTA_INSTANCIA.read_text(encoding="utf-8")).get("pid") == os.getpid():
            RUTA_INSTANCIA.unlink()
    except Exception:
        pass


def main():
    cargar_claves_guardadas()
    version = version_codigo()
    if "--puerto" not in sys.argv and instancia_abierta(version):
        return
    servidor = None
    puertos = range(PUERTO_INICIAL, PUERTO_INICIAL + 40)
    if "--puerto" in sys.argv:
        fijo = int(sys.argv[sys.argv.index("--puerto") + 1])
        puertos = range(fijo, fijo + 1)
    for puerto in puertos:
        if puerto_ocupado(puerto):  # doble control: si algo ya responde ahí, ni lo intento
            continue
        try:
            servidor = ServidorExclusivo(("127.0.0.1", puerto), Manejador)
            break
        except OSError:
            continue
    if servidor is None:
        print(f"No encontré un puerto libre entre {puertos.start} y {puertos.stop - 1}.")
        sys.exit(1)
    servidor.daemon_threads = True
    E.puerto = servidor.server_address[1]
    url = f"http://127.0.0.1:{E.puerto}/?t={TOKEN}"
    threading.Thread(target=difusor, daemon=True).start()
    print("Migrador de correo en marcha.")
    print(f"Si no se abrió la ventana, entrá a: {url}")
    print("Para salir, cerrá esta ventana.\n", flush=True)
    if "--puerto" not in sys.argv:
        registrar_instancia(version)
    E.servidor = servidor
    if "--sin-ventana" not in sys.argv:
        abrir_ventana(url)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        olvidar_instancia()


if __name__ == "__main__":
    main()
