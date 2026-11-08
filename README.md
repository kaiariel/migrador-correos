# Migrador de correo

**Copias de seguridad locales de casillas de correo por IMAP y, si querés, migración a otro servidor, sin perder enviados, adjuntos ni marcas.** Para Windows 10 y 11, con interfaz visual en español. Solo usa Python y su biblioteca estándar: nada de pip ni npm. Código abierto y de dominio público.

Nació para mudar las casillas de varios clientes de un hosting cPanel a Hostinger. Las herramientas a mano tenían tres problemas:

1. **Se perdían cosas en el camino:** enviados, subcarpetas, fechas originales o marcas de leído.
2. **Si algo se cortaba a la mitad, repetir duplicaba correos.**
3. **No había respaldo propio:** si el servidor viejo se daba de baja antes de tiempo, lo que no se había copiado no se recuperaba.

El Migrador resuelve las tres. Primero guarda todo en tu disco y después sube a destino, sin duplicar nunca.

[Guía de uso](LEEME.md) · [Qué cambió](CHANGELOG.md) · [Cómo está hecho](docs/ARQUITECTURA.md) · [Por qué está hecho así](docs/DECISIONES.md) · [Lo que falta](docs/HOJA_DE_RUTA.md)

> La interfaz y la documentación están en español.

---

## Empezar

1. Instalá **Python 3.12 o superior** desde [python.org](https://www.python.org/downloads/windows/). En el instalador, marcá «Add python.exe to PATH».
2. Bajá este repositorio: **Code → Download ZIP**, o `git clone https://github.com/kaiariel/migrador-correos`. Descomprimilo en un disco local, por ejemplo `C:\Herramientas\MigradorCorreos\`.
3. Doble clic en **`Migrador.bat`**. Se abre la aplicación en una ventana de Edge o Chrome, y minimizada queda una ventana negra: es el motor, no la cierres mientras copiás.
4. Seguí los cinco pasos: **Servidor actual → Cuentas → Copia local → Migrar (opcional) → Verificar**.

No hace falta instalar nada más. La configuración y las cuentas se guardan en la carpeta del programa, y la copia de los correos en `C:\MigracionCorreos\respaldo` (se puede cambiar).

---

## Qué hace

| Paso | Para qué sirve |
|---|---|
| **Inicio** | Números clave (cuentas, correos guardados, espacio, última copia), una lista de lo que conviene revisar con su botón para resolverlo y «Actualizar copia» de todas las cuentas de una vez. |
| **1. Servidor actual** | Dónde están hoy los correos. Proveedores precargados: cPanel, Hostinger, Gmail y Google Workspace, Zoho, IONOS, Titan, GoDaddy, Yahoo u otro servidor cargado a mano. |
| **2. Cuentas** | Las casillas con su clave. «Probar cuentas» dice cuántos correos y carpetas tiene cada una. Cada cuenta puede tener **su propio servidor**, y «Averiguar por el dominio» lo deduce de los registros MX. Sirve para respaldar casillas de distintos clientes, cada una en su hosting. |
| **3. Copia local** | Guarda cada correo como un `.eml` completo, con adjuntos, que abre Outlook o Thunderbird. **Incremental:** después solo baja lo nuevo. Tiene **copia automática** programada (desactivada por defecto). |
| **4. Migrar** | Sube a otro servidor **desde la copia local** (no hace falta el servidor viejo) o **desde el servidor actual** (trae primero lo último). Conserva carpetas, subcarpetas, fechas y marcas de leído, destacado y respondido. Traduce las carpetas especiales: Enviados, Borradores, Spam y Papelera. |
| **Liberar espacio** | Cuando una casilla no entra en el buzón nuevo: límite con medidor y meses de margen, reglas (papelera y spam, boletines, duplicados, subir solo desde una fecha) y la lista de los correos más pesados. **Nunca borra**: lo que no se sube queda en la copia, y sus adjuntos además como archivos comunes. |
| **5. Verificar** | Compara carpeta por carpeta el servidor viejo, la copia local y el servidor nuevo. Si el viejo ya no existe, compara la copia con el nuevo. Además guía el cambio de DNS. |

Podés pausar, cancelar o cerrar en cualquier momento: la próxima vez sigue donde quedó.

### Lo que no negocia

- **No pierde ni duplica correos.** La descarga es incremental por `UIDVALIDITY` + `UID`, y la subida se deduplica en dos capas: un sha256 en el estado local y, en el destino, el `Message-ID` o una huella de fecha, remitente y asunto. Repetir una migración, o hacerla sin el archivo de estado, no duplica nada.
- **El servidor viejo es de solo lectura.** Abre las carpetas con `EXAMINE` y lee con `BODY.PEEK[]`: no marca como leído, no mueve y no borra.
- **Se frena si el DNS lo engaña.** En la primera copia guarda la huella del servidor. Si después `mail.tudominio.com` ya apunta al hosting nuevo, se detiene sin copiar y te sugiere el nombre real del servidor viejo. Si vos cambiás de servidor a propósito, sigue en la misma carpeta y baja solo lo nuevo.
- **Las claves nunca quedan en texto plano.** Si activás «Guardar las claves en este equipo», se cifran con DPAPI, ligadas a tu usuario de Windows, en `%APPDATA%\MigradorCorreos\claves.bin`. `cuentas.csv` guarda solo los correos.
- **Solo escucha en tu equipo.** El servidor local atiende únicamente en `127.0.0.1`, con un token por sesión y control del encabezado `Host`: otra página web abierta en el navegador no le puede hablar.

### Para mudar un dominio sin perder correos

1. Hacé la **copia local** mientras el dominio sigue en el servidor viejo.
2. Creá las casillas en el hosting nuevo y **cambiá los MX o los DNS**.
3. Cuando propague, **migrá «desde el servidor actual»**: trae también lo que siguió llegando al viejo durante la propagación.
4. **Verificá**, y recién ahí das de baja el servidor anterior.

El paso a paso completo, con la copia automática y «Liberar espacio», está en la [guía de uso](LEEME.md).

---

## Desde la terminal

El mismo motor funciona sin interfaz, con la configuración y las claves que guardó la app:

```
python migrador.py                                   menú
python migrador.py respaldar                         copia local de todas las cuentas
python migrador.py respaldar --cuenta info@tudominio.com
python migrador.py subir                             migrar desde la copia local
python migrador.py migrar                            actualizar la copia y subir
python migrador.py verificar                         comparar conteos
```

Para configurarlo sin la interfaz, copiá `config.ejemplo.ini` a `config.ini` y `cuentas.ejemplo.csv` a `cuentas.csv`. Si las claves no están guardadas, las pide por teclado y no las guarda.

---

## Pruebas

```
python pruebas/probar_todo.py
```

Son 16 pruebas de punta a punta contra dos servidores IMAP [GreenMail](https://greenmail-mail-test.github.io/greenmail/) en Docker, así que hace falta **Docker Desktop**. Siembran casos difíciles (carpetas con ñ y `&`, subcarpetas, adjuntos de 3 MB, fechas viejas, mensajes sin `Message-ID`, uno marcado como borrado) y comprueban:

- que la subida queda idéntica en contenido, marcas y fechas;
- que repetir no duplica, ni siquiera sin el archivo de estado;
- que detecta el servidor cambiado por DNS;
- que la app y la copia automática nunca escriben a la vez;
- que verificar funciona con el servidor viejo apagado;
- que un cambio de servidor a propósito no vuelve a bajar lo que ya estaba.

Corren sobre una copia en una carpeta temporal, sin tocar tu configuración.

---

## Cómo está hecho

- **`app.py`**: servidor HTTP local de la biblioteca estándar más la API que usa la interfaz. Se abre como ventana con `msedge --app`.
- **`ui/`**: HTML, CSS y JavaScript sin dependencias ni compilación. Modo claro y oscuro, vista para celular e íconos de [Phosphor](https://phosphoricons.com).
- **`migrador.py`**: el motor. Copia, subida, deduplicación, verificación, proveedores y errores explicados en palabras simples.
- **`espacio.py`**: «Liberar espacio» y los adjuntos aparte.
- **`programador.py`**: la copia automática, como tarea del Programador de tareas de Windows.

Los detalles (formatos de archivo, API, eventos e invariantes) están en [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md). Si vas a modificarlo, o a pedirle a una IA que lo haga, empezá por [AGENTS.md](AGENTS.md).

### Limitaciones conocidas

- **Pensado para Windows:** el cifrado de claves (DPAPI), la copia automática y el acceso directo dependen de Windows. El motor de terminal es Python puro, pero fuera de Windows no guarda claves.
- **Algunos hostings rechazan los mensajes muy grandes** (Hostinger, los de más de 50 MB). Quedan anotados en `_errores.csv` y siguen en la copia local.
- **Lo que una casilla bajó por POP3 a una computadora** y borró del servidor no está en el servidor: hay que exportarlo desde ese programa de correo.

---

## Licencia

Dominio público, bajo [The Unlicense](LICENSE). Podés usarlo, copiarlo, modificarlo y venderlo sin pedir permiso ni dar crédito.

Se ofrece tal cual, sin garantías. Antes de dar de baja un servidor viejo, verificá la migración y guardá la copia local en un disco externo.
