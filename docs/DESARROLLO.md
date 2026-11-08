# Desarrollo

## Requisitos

- Windows 10/11 con **Python 3.12** o superior (el de python.org).
  No hace falta instalar paquetes.
- **Docker Desktop** solo para las pruebas (servidores IMAP GreenMail).
- Edge o Chrome para la ventana `--app`; si no hay, se abre el navegador por defecto.

## Correr

```
Migrador.bat                         interfaz (abre la ventana)
python app.py --sin-ventana          interfaz sin abrir ventana: la URL con token sale en la consola
python app.py --puerto 47690         puerto fijo
python migrador.py                   menú de terminal
python migrador.py respaldar         una acción (pide por teclado las claves que falten)
```

> La app usa `config.ini`, `cuentas.csv` y `estado_app.json` **de su propia carpeta**. Para no
> pisar los datos reales, probá siempre en una copia (abajo).

## Pruebas automáticas

```
python pruebas/probar_todo.py            16 pruebas de punta a punta (unos minutos)
python pruebas/probar_todo.py --conservar   deja la carpeta temporal para inspeccionarla
```

Levanta dos contenedores GreenMail (`migrador-prueba-origen` en 3143 y `migrador-prueba-destino`
en 4143, con autenticación desactivada, así que cualquier clave sirve) y copia el motor a una
carpeta temporal. Ahí siembra correos difíciles: carpetas con ñ y `&`, subcarpetas, adjuntos de
3 MB, marcas, fechas de 2019, mensajes sin Message-ID y uno marcado como borrado. Después verifica:

1. copia local completa;
2. subida idéntica (contenido, marcas y fechas);
3. repetir no duplica;
4. «migrar» trae y sube solo lo nuevo;
5. sin el archivo de estado tampoco duplica;
6. detecta el origen cambiado;
7. bloqueo entre procesos;
8. copia automática con claves cifradas;
9. verificar con el origen apagado.

Si agregás una función que mueve correos, **agregá su prueba acá**.

`pruebas/sembrar_y_comparar.py` también se usa suelto:

```
python pruebas/sembrar_y_comparar.py sembrar 3143
python pruebas/sembrar_y_comparar.py comparar 3143 4143
```

## Ver la interfaz con datos de prueba

1. Levantá los servidores y sembrá correos:

   ```
   docker run -d --name gm-origen  -e "GREENMAIL_OPTS=-Dgreenmail.setup.test.all -Dgreenmail.hostname=0.0.0.0 -Dgreenmail.auth.disabled" -p 3143:3143 greenmail/standalone:2.1.2
   docker run -d --name gm-destino -e "GREENMAIL_OPTS=-Dgreenmail.setup.test.all -Dgreenmail.hostname=0.0.0.0 -Dgreenmail.auth.disabled" -p 4143:3143 greenmail/standalone:2.1.2
   python pruebas/sembrar_y_comparar.py sembrar 3143
   ```

2. Copiá `app.py`, `migrador.py`, `programador.py` y `ui/` a una carpeta temporal. Escribí ahí un
   `config.ini` con origen `127.0.0.1:3143`, destino `127.0.0.1:4143`, `seguridad = ninguna` y una
   `carpeta_respaldo` dentro de esa carpeta, más un `cuentas.csv` con
   `info@empresa.test` y `ventas@empresa.test`.
3. Lanzala con las variables de prueba, para no tocar las claves ni la tarea reales:

   ```python
   # lanzar.py, en la carpeta temporal
   import os, sys, runpy
   aqui = os.path.dirname(os.path.abspath(__file__))
   os.environ["MIGRADOR_CLAVES"] = os.path.join(aqui, "claves_prueba.bin")
   os.environ["MIGRADOR_TAREA"] = r"\MigradorCorreosPrueba\CopiaAutomatica"
   os.environ["MIGRADOR_SCRIPT_TAREA"] = os.path.join(aqui, "auto_prueba.py")  # lanzador que fija las mismas variables
   sys.path.insert(0, aqui)
   sys.argv = ["app.py", "--sin-ventana", "--puerto", "47690"]
   runpy.run_path(os.path.join(aqui, "app.py"), run_name="__main__")
   ```

4. Abrí la URL con token que aparece en la consola.
5. Al terminar: `docker rm -f gm-origen gm-destino`. Si creaste la tarea de prueba, borrala con
   `schtasks /delete /tn "\MigradorCorreosPrueba\CopiaAutomatica" /f` y su carpeta desde el
   Programador de tareas.

### Variables de entorno (solo pruebas)

| Variable | Efecto |
|---|---|
| `MIGRADOR_CLAVES` | Ruta del archivo de claves cifradas, en lugar de `%APPDATA%\MigradorCorreos\claves.bin` |
| `MIGRADOR_TAREA` | Nombre de la tarea programada, en lugar de `\MigradorCorreos\CopiaAutomatica` |
| `MIGRADOR_INSTANCIA` | Ruta de `instancia.json` (registro de la app abierta), en lugar de `%APPDATA%\MigradorCorreos\instancia.json` |
| `MIGRADOR_SCRIPT_TAREA` | Script que ejecuta la tarea, en lugar de `migrador.py` (para un lanzador con las variables de arriba) |

## Agregar cosas

- **Un proveedor**: una entrada en `PROVEEDORES` (`migrador.py`) con `nombre`, `servidor`,
  `puerto`, `seguridad` y una `ayuda` corta en voseo. La interfaz lo muestra solo.
- **Un ícono**: tomalo de [Phosphor](https://phosphoricons.com) (estilo «regular»; en el paquete `@phosphor-icons/core` está en `assets/regular/<nombre>.svg`),
  copiá el contenido interior del `<svg>` y agregalo a `ICONOS` en `ui/iconos.js`. Se usa con `ic("nombre")`.
- **Una acción del motor**: agregala a `ACCIONES` y a `procesar()`. La API ya la acepta en
  `/api/accion` y la valida con las banderas origen/destino.
- **Una ruta de la API**: una función que recibe el JSON y devuelve un dict, registrada en `RUTAS_POST`.
- **Un texto de error**: en `explicar_error()`, en palabras simples.

## Trampas conocidas (ya nos pasaron)

- **Puertos en Windows**: `HTTPServer` usa `SO_REUSEADDR` y en Windows eso deja «compartir» un
  puerto ocupado. La ventana mostró otra app local (un panel de finanzas en el 8765). Por eso
  existen `ServidorExclusivo` y el rango 47615+.
- **Varias apps abiertas a la vez**: como el acceso directo abre la consola minimizada, cada
  doble clic dejaba otro motor corriendo (llegó a haber 4, algunos con código viejo). Por eso existe
  el control de una sola instancia (`instancia.json` y `/api/salir`).
- **`requestAnimationFrame` se congela** con la ventana minimizada u oculta: la interfaz no se
  refrescaba. Se usa `setTimeout`.
- **Orden de los eventos**: el aviso de fin de tarea llegaba antes que el último progreso. Por eso
  `vaciar_progreso()` va antes de emitir `trabajo`.
- **Capturas en el panel del navegador**: con la ventana oculta, las animaciones y transiciones se
  quedan a mitad. Para capturar, inyectá
  `*{animation:none!important;transition:none!important}`.
- **La página guarda su configuración antes de cada acción** (`iniciar()` hace POST de `S.config`).
  Si en una prueba cambiás `config.ini` por fuera, la página lo pisa. Cambiá los campos desde la
  interfaz.
- **imaplib no pone comillas** a los nombres de carpeta: usá siempre `wire(nombre)`.
- **Las líneas `FETCH` traen literales en tuplas** y el UID puede venir antes o después del
  literal: mirá `respaldar_carpeta`.
- **GreenMail con autenticación desactivada crea la casilla al primer login**. En un servidor real,
  la casilla de destino tiene que existir antes.
- **PowerShell 5.1** lee los archivos UTF-8 sin BOM como ANSI: para leer salidas con tildes, usá
  Bash o Python.
- **Bloques heredoc largos** con comillas mezcladas pueden cortarse en la terminal de la IA: para
  scripts de cambios grandes, escribí un `.py` temporal y ejecutalo.

## Lista de control antes de entregar

- [ ] `python pruebas/probar_todo.py` → 10 de 10.
- [ ] Si tocaste la interfaz: probala en claro, oscuro y a 375 px; sin errores en la consola.
- [ ] La carpeta real quedó limpia: sin `__pycache__`, sin archivos de prueba y sin tocar
      `config.ini`, `cuentas.csv` ni `estado_app.json`.
- [ ] No quedaron contenedores (`docker ps`) ni tareas de prueba en el Programador.
- [ ] HISTORIAL.md actualizado y, si cambió el uso, LEEME.md también.
