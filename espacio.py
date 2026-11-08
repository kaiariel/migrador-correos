"""Liberar espacio: elegir qué correos de la copia local NO se suben al servidor nuevo y guardar
sus adjuntos aparte. Nunca se borra nada: lo que no se sube sigue en la copia local.

Filtros por cuenta en filtros.json (junto al programa):
    {"correo": {"papelera": bool, "boletines": bool, "duplicados": bool, "desde": "2025-07-01" | null,
                "excluir": [clave, …], "incluir": [clave, …], "limite_mb": 1024 | null}}
La «clave» de un correo es "<carpeta en disco>/<archivo .eml>", única dentro de la cuenta.
`incluir` gana sobre cualquier regla; `excluir` deja afuera ese correo puntual.
"""

import email
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta
from email import policy
from email.utils import parseaddr, parsedate_to_datetime

import migrador as m

RUTA_FILTROS = m.BASE / "filtros.json"
FILTRO_VACIO = {"papelera": False, "boletines": False, "duplicados": False, "desde": None,
                "excluir": [], "incluir": [], "limite_mb": None}
CARPETAS_PAPELERA = {"\\trash", "\\junk"}
MOTIVOS = {"papelera": "Papelera o spam", "boletin": "Boletín o publicidad", "duplicado": "Duplicado",
           "fecha": "Anterior a la fecha", "manual": "Lo dejaste afuera"}
FIRMA_MAX = 60_000  # imágenes más chicas que esto con nombre image001.png… son firmas, no adjuntos


# ---------------------------------------------------------------- filtros

def leer_filtros():
    try:
        return json.loads(RUTA_FILTROS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def filtro_de(correo):
    return {**FILTRO_VACIO, **leer_filtros().get(correo.lower(), {})}


def guardar_filtro(correo, filtro):
    todos = leer_filtros()
    limpio = {k: filtro.get(k, v) for k, v in FILTRO_VACIO.items()}
    limpio["excluir"] = sorted(set(limpio["excluir"] or []))
    limpio["incluir"] = sorted(set(limpio["incluir"] or []))
    todos[correo.lower()] = limpio
    m.guardar_json(RUTA_FILTROS, todos)
    return limpio


def filtro_activo(f):
    return bool(f["papelera"] or f["boletines"] or f["duplicados"] or f["desde"] or f["excluir"])


# ---------------------------------------------------------------- catálogo de la copia local

def _fecha(msg, entrada):
    try:
        if msg["Date"]:
            return parsedate_to_datetime(str(msg["Date"])).date().isoformat()
    except Exception:
        pass
    try:
        return datetime.strptime(entrada.get("fecha") or "", "%d-%b-%Y %H:%M:%S %z").date().isoformat()
    except Exception:
        return None


def es_adjunto(parte):
    nombre = parte.get_filename()
    if parte.is_multipart() or not nombre:
        return False
    if parte.get_content_maintype() == "image" and re.match(r"(?i)image\d+\.", nombre) \
            and len(parte.get_payload(decode=True) or b"") < FIRMA_MAX:
        return False
    return True


def _resumir(raw, entrada, carpeta, especial, clave):
    msg = email.message_from_bytes(raw, policy=policy.default)
    nombre, direccion = parseaddr(str(msg.get("From", "")))
    adjuntos = []
    for parte in msg.walk():
        if es_adjunto(parte):
            adjuntos.append({"nombre": parte.get_filename(), "bytes": len(parte.get_payload(decode=True) or b"")})
    return {
        "clave": clave, "sha256": entrada["sha256"], "carpeta": carpeta, "especial": especial,
        "bytes": entrada.get("tamano") or len(raw), "fecha": _fecha(msg, entrada),
        "de": direccion.lower(), "de_nombre": nombre, "asunto": str(msg.get("Subject", ""))[:140],
        "boletin": bool(msg.get("List-Unsubscribe") or msg.get("List-Id")
                        or str(msg.get("Precedence", "")).lower() in ("bulk", "list")),
        "message_id": entrada.get("message_id"), "adjuntos": adjuntos,
    }


def catalogo(cfg, correo):
    """Los correos que se subirían (plan_de_subida), con sus datos. Se cachea en _resumen.jsonl."""
    raiz = cfg.respaldo / m.segura(correo)
    cache_ruta = raiz / "_resumen.jsonl"
    cache = {}
    if cache_ruta.exists():
        for linea in cache_ruta.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(linea)
                cache[r["clave"]] = r
            except Exception:
                pass
    items, nuevos = [], []
    for d, meta, entradas in m.plan_de_subida(raiz):
        for e in entradas:
            clave = f"{d.name}/{e['archivo']}"
            r = cache.get(clave)
            if r is None or r.get("sha256") != e["sha256"]:
                r = _resumir((d / e["archivo"]).read_bytes(), e, meta["nombre"], meta.get("especial"), clave)
                nuevos.append(r)
            items.append(r)
    if nuevos:
        with open(cache_ruta, "a", encoding="utf-8") as f:
            for r in nuevos:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return items


# ---------------------------------------------------------------- reglas

def _es_papelera(it):
    ultimo = it["carpeta"].replace("/", ".").split(".")[-1].lower()
    return it.get("especial") in CARPETAS_PAPELERA or ultimo in m.ESPECIALES["\\trash"] | m.ESPECIALES["\\junk"]


def motivos(items, filtro):
    """{clave: motivo o None}. None = se sube."""
    excluir, incluir = set(filtro["excluir"]), set(filtro["incluir"])
    desde = filtro["desde"]
    vistos = set()
    res = {}
    for it in sorted(items, key=lambda x: (x["fecha"] or "", x["clave"])):
        llave = (it["carpeta"], it["message_id"] or it["sha256"])
        duplicado = llave in vistos
        vistos.add(llave)
        motivo = None
        if it["clave"] in excluir:
            motivo = "manual"
        elif filtro["papelera"] and _es_papelera(it):
            motivo = "papelera"
        elif filtro["boletines"] and it["boletin"] and it.get("especial") != "\\sent":
            motivo = "boletin"
        elif filtro["duplicados"] and duplicado:
            motivo = "duplicado"
        elif desde and it["fecha"] and it["fecha"] < desde:
            motivo = "fecha"
        if it["clave"] in incluir:
            motivo = None
        res[it["clave"]] = motivo
    return res


def claves_excluidas(cfg, correo):
    """Lo que subir_cuenta tiene que saltear. Vacío (y sin analizar nada) si no hay filtro."""
    filtro = filtro_de(correo)
    if not filtro_activo(filtro):
        return frozenset()
    return frozenset(k for k, mot in motivos(catalogo(cfg, correo), filtro).items() if mot)


def crecimiento_mensual(items):
    """Promedio de MB por mes de los últimos 12 meses con correo (para estimar cuánto dura el espacio)."""
    por_mes = defaultdict(int)
    hace_un_anio = (datetime.now() - timedelta(days=365)).date().isoformat()
    for it in items:
        if it["fecha"] and it["fecha"] >= hace_un_anio and not _es_papelera(it):
            por_mes[it["fecha"][:7]] += it["bytes"]
    return sum(por_mes.values()) / max(len(por_mes), 1) / 1048576 if por_mes else 0


def evaluar(cfg, correo, filtro=None, cantidad_pesados=60):
    """Resumen para la interfaz: cuánto se sube, cuánto queda afuera y por qué, y los más pesados."""
    filtro = filtro or filtro_de(correo)
    items = catalogo(cfg, correo)
    mot = motivos(items, filtro)
    incluir = set(filtro["incluir"])
    total = sum(it["bytes"] for it in items)
    subir = sum(it["bytes"] for it in items if not mot[it["clave"]])
    por_motivo = defaultdict(lambda: {"correos": 0, "bytes": 0})
    for it in items:
        if mot[it["clave"]]:
            por_motivo[mot[it["clave"]]]["correos"] += 1
            por_motivo[mot[it["clave"]]]["bytes"] += it["bytes"]
    # lo que liberaría cada regla por sí sola (para mostrar al lado de cada interruptor)
    potencial = {}
    for regla, motivo in (("papelera", "papelera"), ("boletines", "boletin"), ("duplicados", "duplicado")):
        solo = motivos(items, {**FILTRO_VACIO, regla: True})
        afuera = [it for it in items if solo[it["clave"]] == motivo]
        potencial[regla] = {"correos": len(afuera), "bytes": sum(it["bytes"] for it in afuera)}
    if filtro["desde"]:
        afuera = [it for it in items if it["fecha"] and it["fecha"] < filtro["desde"]]
        potencial["desde"] = {"correos": len(afuera), "bytes": sum(it["bytes"] for it in afuera)}
    pesados = []
    for it in sorted(items, key=lambda x: -x["bytes"])[:cantidad_pesados]:
        pesados.append({
            "clave": it["clave"], "bytes": it["bytes"], "fecha": it["fecha"], "de": it["de"],
            "de_nombre": it["de_nombre"], "asunto": it["asunto"], "carpeta": it["carpeta"],
            "adjuntos": [a["nombre"] for a in sorted(it["adjuntos"], key=lambda a: -a["bytes"])[:3]],
            "motivo": mot[it["clave"]], "forzado": it["clave"] in incluir,
        })
    fechas = sorted(it["fecha"] for it in items if it["fecha"])
    return {
        "filtro": filtro, "total": total, "subir": subir, "correos": len(items),
        "correos_subir": sum(1 for it in items if not mot[it["clave"]]),
        "por_motivo": por_motivo, "potencial": potencial, "pesados": pesados,
        "crecimiento_mb_mes": round(crecimiento_mensual(items), 1),
        "primera_fecha": fechas[0] if fechas else None,
    }


# ---------------------------------------------------------------- adjuntos aparte

def carpeta_adjuntos(cfg, correo=None):
    base = cfg.respaldo.parent / "adjuntos"
    return base / m.segura(correo) if correo else base


def guardar_adjuntos(cfg, correo, solo_excluidos=True, log=None):
    """Copia los adjuntos como archivos comunes: adjuntos/<correo>/<fecha> - <remitente> - <asunto>/archivo.
    Si ya existe un archivo igual, no lo vuelve a escribir."""
    raiz = cfg.respaldo / m.segura(correo)
    destino = carpeta_adjuntos(cfg, correo)
    items = catalogo(cfg, correo)
    if solo_excluidos:
        mot = motivos(items, filtro_de(correo))
        items = [it for it in items if mot[it["clave"]]]
    archivos = escritos = bytes_ = 0
    for it in items:
        if not it["adjuntos"]:
            continue
        m.CONTROL.punto()
        quien = m.segura(it["de_nombre"] or it["de"] or "sin remitente", 40)
        sub = destino / m.segura(f"{it['fecha'] or 'sin fecha'} - {quien} - {it['asunto'] or 'sin asunto'}", 110)
        msg = email.message_from_bytes((raiz / it["clave"]).read_bytes(), policy=policy.default)
        usados = set()
        for parte in msg.walk():
            if not es_adjunto(parte):
                continue
            datos = parte.get_payload(decode=True) or b""
            nombre = m.segura(parte.get_filename(), 100)
            raiz_nombre, ext = os.path.splitext(nombre)
            n = 2
            while nombre.lower() in usados:  # dos adjuntos con el mismo nombre en un correo
                nombre = f"{raiz_nombre} ({n}){ext}"
                n += 1
            usados.add(nombre.lower())
            ruta = sub / nombre
            archivos += 1
            bytes_ += len(datos)
            if ruta.exists() and ruta.stat().st_size == len(datos):
                continue
            sub.mkdir(parents=True, exist_ok=True)
            ruta.write_bytes(datos)
            escritos += 1
    if log:
        log.info(f"Adjuntos guardados aparte: {archivos} archivos ({escritos} nuevos, {bytes_ / 1048576:.0f} MB) en {destino}")
    return {"archivos": archivos, "nuevos": escritos, "bytes": bytes_, "carpeta": str(destino)}
