"""Prueba de punta a punta del motor con dos servidores GreenMail en Docker.

    python pruebas/probar_todo.py

Requiere Docker en marcha. No toca la configuración real: trabaja en una carpeta temporal con
una copia del motor, claves cifradas de prueba y sus propios servidores (puertos 3143 y 4143).
Al terminar borra los contenedores y la carpeta temporal (salvo con --conservar).
"""
import hashlib
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent
sys.path.insert(0, str(AQUI))
import sembrar_y_comparar as sc  # noqa: E402

IMAGEN = "greenmail/standalone:2.1.2"
P_ORIGEN, P_DESTINO = 3143, 4143
CONTENEDORES = {"migrador-prueba-origen": P_ORIGEN, "migrador-prueba-destino": P_DESTINO}
OPCIONES = "-Dgreenmail.setup.test.all -Dgreenmail.hostname=0.0.0.0 -Dgreenmail.auth.disabled"

resultados = []


def prueba(nombre, ok, detalle=""):
    resultados.append((nombre, ok))
    print(f"{'OK   ' if ok else 'FALLA'} {nombre}" + (f"\n      {detalle}" if detalle and not ok else ""))


def docker(*args, check=True):
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check)


def esperar_puerto(puerto, segundos=40):
    fin = time.time() + segundos
    while time.time() < fin:
        try:
            with socket.create_connection(("127.0.0.1", puerto), timeout=1) as s:
                if s.recv(20).startswith(b"* OK"):
                    return True
        except OSError:
            time.sleep(0.5)
    return False


def levantar_servidores():
    for nombre, puerto in CONTENEDORES.items():
        docker("rm", "-f", nombre, check=False)
        docker("run", "-d", "--name", nombre, "-e", f"GREENMAIL_OPTS={OPCIONES}", "-p", f"{puerto}:3143", IMAGEN)
    for puerto in CONTENEDORES.values():
        if not esperar_puerto(puerto):
            sys.exit(f"El servidor de prueba del puerto {puerto} no arrancó.")
        for _ in range(40):  # el puerto abre antes de que GreenMail acepte usuarios
            try:
                sc.conectar(puerto, sc.CUENTAS[0]).logout()
                break
            except Exception:
                time.sleep(0.5)
        else:
            sys.exit(f"El servidor de prueba del puerto {puerto} no acepta inicios de sesión.")


def bajar_servidores():
    for nombre in CONTENEDORES:
        docker("rm", "-f", nombre, check=False)


def escribir_config(trabajo, puerto_origen=P_ORIGEN):
    (trabajo / "config.ini").write_text(f"""[origen]
proveedor = otro
servidor = 127.0.0.1
puerto = {puerto_origen}
seguridad = ninguna
verificar_certificado = si
[destino]
proveedor = otro
servidor = 127.0.0.1
puerto = {P_DESTINO}
seguridad = ninguna
verificar_certificado = si
[general]
carpeta_respaldo = {trabajo / "respaldo"}
excluir_carpetas =
cuentas_a_la_vez = 2
lote_mb = 5
""", encoding="utf-8")


def escribir_cuentas(trabajo, servidores):
    """cuentas.csv con el servidor propio de cada cuenta ({correo: (host, puerto)}; sin entrada = el general)."""
    filas = ["correo,clave_origen,correo_destino,clave_destino,servidor,puerto,seguridad,verificar"]
    for c in sc.CUENTAS:
        host, puerto = servidores.get(c, ("", ""))
        filas.append(f"{c},x,,,{host},{puerto},{'ninguna' if host else ''},{'si' if host else ''}")
    (trabajo / "cuentas.csv").write_text("\n".join(filas) + "\n", encoding="utf-8")


def renombrar_carpeta(puerto, usuario, vieja, nueva):
    """Como otro servidor que llama distinto a la misma carpeta (p. ej. «Enviados» en vez de «Sent»)."""
    i = sc.conectar(puerto, usuario)
    try:
        typ, _ = i.rename(sc.wire(vieja), sc.wire(nueva))
        if typ != "OK":
            raise RuntimeError("RENAME no soportado")
    except Exception:
        i.create(sc.wire(nueva))
        i.select(sc.wire(vieja))
        i.copy("1:*", sc.wire(nueva))
        i.close()
        i.delete(sc.wire(vieja))
    i.logout()


def probar_servidor_por_cuenta(trabajo, motor, mig):
    """Cada cuenta con su propio servidor, y una cuenta que pasa a otro servidor después de migrar."""
    a, b = sc.CUENTAS
    raiz_a = trabajo / "respaldo" / mig.segura(a)
    raiz_b = trabajo / "respaldo" / mig.segura(b)

    def huellas(raiz):
        return {str(p.relative_to(raiz)): hashlib.sha256(p.read_bytes()).hexdigest() for p in raiz.glob("*/*.eml")}

    # Guardar y leer el servidor de cada cuenta (y un cuentas.csv viejo, sin esas columnas)
    (trabajo / "cuentas.csv").write_text(f"correo,clave_origen,correo_destino,clave_destino\n{a},,,\n", encoding="utf-8")
    viejo = mig.leer_cuentas_dicts()
    mig.escribir_cuentas_dicts([{**viejo[0]}, {"correo": b, "correo_destino": "", "servidor": "imap.ejemplo.test",
                                               "puerto": 143, "seguridad": "starttls", "verificar": False}])
    leidas = {c["correo"]: c for c in mig.leer_cuentas_dicts()}
    cb = mig.cuenta_desde_dict(leidas[b])
    prueba("Cada cuenta guarda su servidor (y un cuentas.csv viejo sigue andando)",
           leidas[a]["servidor"] == "" and mig.cuenta_desde_dict(leidas[a]).origen is None
           and cb.origen and (cb.origen.host, cb.origen.puerto, cb.origen.seguridad, cb.origen.verificar)
           == ("imap.ejemplo.test", 143, "starttls", False), str(leidas))

    # El correo de «a» ya se migró al servidor del puerto 4143 (allí está todo lo que se subió);
    # ese servidor llama «Enviados» a la carpeta «Sent» y recibió 2 correos nuevos.
    renombrar_carpeta(P_DESTINO, a, "Sent", "Enviados")
    sc.agregar(P_DESTINO, a, 2, etiqueta="llego-al-nuevo")
    sc.agregar(P_ORIGEN, b, 1, etiqueta="sigue-en-el-viejo")
    antes_a, antes_b = huellas(raiz_a), huellas(raiz_b)
    escribir_cuentas(trabajo, {a: ("localhost", P_DESTINO)})  # «b» sigue con el servidor general (puerto 3143)
    rc, salida = motor("respaldar")
    despues_a, despues_b = huellas(raiz_a), huellas(raiz_b)
    intactos = all(despues_a.get(k) == v for k, v in antes_a.items())
    huella = json.loads((raiz_a / "_origen.json").read_text(encoding="utf-8"))
    prueba("Cambio de servidor: baja solo lo nuevo, no duplica ni toca lo que ya estaba",
           rc == 0 and "ya no es el mismo" not in salida and len(despues_a) - len(antes_a) == 2 and intactos
           and "ya estaban en la copia" in salida and huella.get("anteriores") and not huella.get("cambio_pendiente"),
           f"rc={rc}, nuevos={len(despues_a) - len(antes_a)}, intactos={intactos}, huella={ {k: huella.get(k) for k in ('servidor', 'cambio_pendiente')} }\n{salida[-900:]}")
    meta_sent = json.loads((raiz_a / "Sent" / "_carpeta.json").read_text(encoding="utf-8"))
    prueba("Carpeta con otro nombre en el servidor nuevo: sigue en la misma carpeta local",
           not (raiz_a / "Enviados").exists() and "Enviados" in meta_sent.get("nombres_servidor", []),
           f"carpetas={sorted(p.name for p in raiz_a.iterdir() if p.is_dir())}, meta={meta_sent}")
    prueba("En la misma copia, otra cuenta sigue con su propio servidor",
           len(despues_b) - len(antes_b) == 1 and all(despues_b.get(k) == v for k, v in antes_b.items()),
           f"nuevos en b={len(despues_b) - len(antes_b)}")

    rc, salida = motor("respaldar")
    prueba("Repetir desde el servidor nuevo no baja nada", rc == 0 and huellas(raiz_a) == despues_a
           and "0 mensajes nuevos descargados" in salida, salida[-600:])

    # Mismo nombre de servidor pero otra máquina (lo que pasa cuando se muda el DNS): frena
    escribir_cuentas(trabajo, {a: ("localhost", P_ORIGEN)})
    rc, salida = motor("respaldar", "--cuenta", a)
    prueba("Con servidor propio, si el DNS se mudó frena y no mezcla", rc != 0 and "ya no es el mismo" in salida
           and huellas(raiz_a) == despues_a, salida[-600:])
    escribir_cuentas(trabajo, {a: ("localhost", P_DESTINO)})


def main():
    conservar = "--conservar" in sys.argv
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        sys.exit("Docker no está en marcha. Abrí Docker Desktop y volvé a intentar.")

    trabajo = Path(tempfile.mkdtemp(prefix="migrador-prueba-"))
    for archivo in ("migrador.py", "programador.py", "espacio.py"):
        shutil.copy(RAIZ / archivo, trabajo / archivo)
    escribir_config(trabajo)
    (trabajo / "cuentas.csv").write_text("correo,clave_origen,correo_destino,clave_destino\n"
                                         + "".join(f"{c},x,,\n" for c in sc.CUENTAS), encoding="utf-8")
    entorno = {**os.environ, "MIGRADOR_CLAVES": str(trabajo / "claves.bin"), "PYTHONIOENCODING": "utf-8"}

    def motor(*args):
        r = subprocess.run([sys.executable, str(trabajo / "migrador.py"), *args], cwd=trabajo, env=entorno,
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           stdin=subprocess.DEVNULL, timeout=900)
        return r.returncode, (r.stdout or "") + (r.stderr or "")

    def emls():
        return len(list((trabajo / "respaldo").glob("*/*/*.eml")))

    print(f"Carpeta de trabajo: {trabajo}")
    print("Levantando servidores de prueba…")
    levantar_servidores()
    try:
        sc.sembrar(P_ORIGEN)

        rc, salida = motor("respaldar")
        prueba("Copia local completa (todas las carpetas, con ñ y &)", rc == 0 and emls() == sc.contar_origen(P_ORIGEN),
               f"rc={rc}, en disco={emls()}, en origen={sc.contar_origen(P_ORIGEN)}\n{salida[-800:]}")

        rc, salida = motor("subir")
        prueba("Subida desde la copia: contenido, marcas y fechas idénticos", rc == 0 and sc.comparar(P_ORIGEN, P_DESTINO, False),
               salida[-800:])

        rc, salida = motor("migrar")
        prueba("Repetir no duplica nada", rc == 0 and "0 mensajes nuevos en destino" in salida
               and sc.comparar(P_ORIGEN, P_DESTINO, False), salida[-800:])

        sc.agregar(P_ORIGEN, sc.CUENTAS[0], 3)
        rc, salida = motor("migrar")
        prueba("Migrar desde el servidor trae y sube solo lo nuevo", rc == 0 and "3 por descargar" in salida
               and sc.comparar(P_ORIGEN, P_DESTINO, False), salida[-800:])

        for estado in (trabajo / "respaldo").glob("*/_subidos_*.json"):
            estado.unlink()
        rc, salida = motor("subir")
        prueba("Sin el archivo de estado tampoco duplica (Message-ID y huella)", rc == 0
               and sc.comparar(P_ORIGEN, P_DESTINO, False), salida[-800:])

        # Liberar espacio: con filtro, lo excluido no se sube y sus adjuntos se guardan aparte
        (trabajo / "filtros.json").write_text(json.dumps({sc.CUENTAS[0]: {"papelera": True, "desde": "2019-03-15"}}),
                                              encoding="utf-8")
        rc, salida = motor("subir")
        adjuntos = list((trabajo / "adjuntos").rglob("*.pdf"))
        rc_v, salida_v = motor("verificar")
        prueba("Liberar espacio: deja afuera lo filtrado, guarda sus adjuntos y verifica bien",
               rc == 0 and "correos no se suben" in salida and len(adjuntos) > 0 and rc_v == 0,
               f"rc={rc}, adjuntos={len(adjuntos)}, rc_verificar={rc_v}\n{salida[-600:]}\n{salida_v[-400:]}")
        (trabajo / "filtros.json").unlink()

        escribir_config(trabajo, puerto_origen=P_DESTINO)  # «el DNS ya apunta al servidor nuevo»
        rc, salida = motor("respaldar")
        prueba("Detecta que el origen ya no es el servidor viejo y no copia", rc != 0 and "ya no es el mismo" in salida,
               salida[-800:])
        escribir_config(trabajo)

        spec = importlib.util.spec_from_file_location("migrador_prueba", trabajo / "migrador.py")
        mig = importlib.util.module_from_spec(spec)
        os.environ["MIGRADOR_CLAVES"] = str(trabajo / "claves.bin")
        spec.loader.exec_module(mig)
        cfg = mig.config_desde_dict(mig.leer_config_dict())
        tomado, soltar = threading.Event(), threading.Event()

        def retener():
            with mig.bloqueo(cfg):
                tomado.set()
                soltar.wait(60)

        hilo = threading.Thread(target=retener)
        hilo.start()
        tomado.wait(10)
        rc, salida = motor("respaldar")
        soltar.set()
        hilo.join()
        prueba("Bloqueo: no corren dos copias a la vez", rc != 0 and "otra copia" in salida, salida[-800:])

        if mig.CLAVES_CIFRABLES:
            mig.guardar_claves({c: {"clave_origen": "x", "clave_destino": "x"} for c in sc.CUENTAS})
            (trabajo / "cuentas.csv").write_text("correo,clave_origen,correo_destino,clave_destino\n"
                                                 + "".join(f"{c},,,\n" for c in sc.CUENTAS), encoding="utf-8")
            sc.agregar(P_ORIGEN, sc.CUENTAS[1], 2, etiqueta="auto")
            rc, salida = motor("respaldar", "--automatica")
            try:
                auto = json.loads((trabajo / "automatica.json").read_text(encoding="utf-8"))
            except Exception:
                auto = {}
            prueba("Copia automática con claves cifradas (sin preguntar nada)", rc == 0 and auto.get("ok") and auto.get("nuevos") == 2,
                   f"rc={rc}, automatica.json={auto}")
        else:
            print("—     Copia automática: se omite (solo Windows)")

        probar_servidor_por_cuenta(trabajo, motor, mig)

        docker("stop", "migrador-prueba-origen")
        rc, salida = motor("verificar")
        prueba("Verificar sin el servidor viejo compara la copia local con el destino",
               rc == 0 and "Comparo la copia local con el destino" in salida, salida[-800:])
    finally:
        bajar_servidores()
        if conservar:
            print(f"Se conservó la carpeta de trabajo: {trabajo}")
        else:
            shutil.rmtree(trabajo, ignore_errors=True)

    fallas = [n for n, ok in resultados if not ok]
    print(f"\n{len(resultados) - len(fallas)} de {len(resultados)} pruebas OK.")
    sys.exit(1 if fallas else 0)


if __name__ == "__main__":
    main()
