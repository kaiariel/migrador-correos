"""Herramientas de prueba: siembra correos en un servidor IMAP de prueba y compara dos servidores.

Uso suelto:
    python sembrar_y_comparar.py sembrar  [puerto_origen]
    python sembrar_y_comparar.py comparar [puerto_origen puerto_destino]

Pensado para GreenMail con autenticación desactivada (cualquier clave sirve).
"""
import hashlib
import imaplib
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from migrador import mutf7_decode, wire  # noqa: E402

CUENTAS = ["info@empresa.test", "ventas@empresa.test"]
PLAN = {"INBOX": 30, "Sent": 10, "Drafts": 2, "Clientes": 4, "Clientes.2024": 5, "Ñandú & Cía": 3, "Trash": 2}


def conectar(puerto, usuario):
    i = imaplib.IMAP4("127.0.0.1", puerto)
    i.login(usuario, "x")
    return i


def mensaje(n, carpeta, adjunto=None, sin_id=False):
    m = EmailMessage()
    m["From"] = "Cliente Ñoño <cliente@otro.test>"
    m["To"] = "info@empresa.test"
    m["Subject"] = f"[{carpeta}] Mensaje {n} con tildes áéí"
    m["Date"] = format_datetime(datetime(2019, 3, 1, tzinfo=timezone.utc) + timedelta(days=n))
    if not sin_id:
        m["Message-ID"] = make_msgid(domain="otro.test")
    m.set_content(f"Hola, este es el mensaje {n} de {carpeta}.\nSaludos.")
    if adjunto:
        m.add_attachment(adjunto, maintype="application", subtype="pdf", filename=f"factura_{n}.pdf")
    return m.as_bytes()


def sembrar(puerto=3143):
    """Carpetas con ñ y &, subcarpetas, adjuntos grandes, marcas, fechas viejas, un correo sin
    Message-ID por carpeta y uno marcado como borrado sin purgar."""
    for usuario in CUENTAS:
        i = conectar(puerto, usuario)
        for carpeta, cantidad in PLAN.items():
            if usuario.startswith("ventas") and carpeta not in ("INBOX", "Sent"):
                continue
            if carpeta != "INBOX":
                i.create(wire(carpeta))
            for n in range(cantidad):
                adjunto = os.urandom(3_000_000) if (carpeta == "INBOX" and n < 3) else (os.urandom(20_000) if n % 4 == 0 else None)
                flags = ["\\Seen"] if n % 2 == 0 else []
                if n % 5 == 0:
                    flags.append("\\Flagged")
                if n % 7 == 0:
                    flags.append("\\Answered")
                if carpeta == "Drafts":
                    flags.append("\\Draft")
                fecha = imaplib.Time2Internaldate(datetime(2019, 3, 1, 10, 30, tzinfo=timezone.utc) + timedelta(days=n))
                i.append(wire(carpeta), "(" + " ".join(flags) + ")" if flags else None, fecha,
                         mensaje(n, carpeta, adjunto, sin_id=(n == 1)))
        i.append(wire("INBOX"), "(\\Deleted)", None, mensaje(99, "INBOX-borrado"))
        i.logout()


def agregar(puerto, usuario, cantidad, carpeta="INBOX", etiqueta="nuevo"):
    i = conectar(puerto, usuario)
    for k in range(cantidad):
        i.append(wire(carpeta), None, None, mensaje(5000 + k, etiqueta))
    i.logout()


def huella(puerto, usuario):
    """{carpeta: [(hash del contenido, marcas, fecha de recepción), ...]}"""
    i = conectar(puerto, usuario)
    _, data = i.list()
    res = {}
    for item in data:
        linea = item.decode()
        nombre = mutf7_decode(re.search(r'"([^"]*)"\s*$', linea)[1] if linea.endswith('"') else linea.split()[-1])
        typ, d = i.select(wire(nombre), readonly=True)
        if typ != "OK" or int(d[0]) == 0:
            res[nombre] = []
            continue
        _, d = i.fetch("1:*", "(FLAGS INTERNALDATE BODY.PEEK[])")
        msgs = []
        for it in d:
            if isinstance(it, tuple):
                flags = tuple(sorted(f for f in re.search(rb"FLAGS \(([^)]*)\)", it[0])[1].decode().split() if f != "\\Recent"))
                fecha = re.search(rb'INTERNALDATE "([^"]+)"', it[0])[1].decode()
                msgs.append((hashlib.sha256(it[1].replace(b"\r\n", b"\n")).hexdigest()[:12], flags, fecha))
        res[nombre] = sorted(msgs)
    i.logout()
    return res


def comparar(p_origen=3143, p_destino=4143, mostrar=True):
    """True si el destino tiene exactamente lo del origen (menos los marcados como borrados)."""
    todo_ok = True
    for usuario in CUENTAS:
        o, d = huella(p_origen, usuario), huella(p_destino, usuario)
        for carpeta, msgs in o.items():
            esperados = [m for m in msgs if "\\Deleted" not in m[1]]
            hay = d.get(carpeta)
            ok = hay == esperados
            todo_ok &= ok
            if mostrar:
                print(f"  {usuario:22} {carpeta:14} origen={len(msgs):4} destino={len(hay) if hay is not None else '—':>4}  {'igual' if ok else 'DIFERENTE'}")
    return todo_ok


def contar_origen(puerto=3143):
    total = 0
    for usuario in CUENTAS:
        i = conectar(puerto, usuario)
        _, data = i.list()
        for item in data:
            linea = item.decode()
            nombre = re.search(r'"([^"]*)"\s*$', linea)[1] if linea.endswith('"') else linea.split()[-1]
            _, st = i.status(f'"{nombre}"', "(MESSAGES)")
            total += int(re.search(rb"MESSAGES (\d+)", st[0])[1])
        i.logout()
    return total


if __name__ == "__main__":
    accion = sys.argv[1] if len(sys.argv) > 1 else "comparar"
    if accion == "sembrar":
        sembrar(int(sys.argv[2]) if len(sys.argv) > 2 else 3143)
        print("Sembrado")
    else:
        ok = comparar(*(int(x) for x in sys.argv[2:4]))
        print("RESULTADO:", "TODO IDÉNTICO" if ok else "HAY DIFERENCIAS")
