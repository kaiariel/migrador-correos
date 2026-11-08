# Migrador de correo

Hace **copias de seguridad locales** de tus casillas de correo y, si querés, las **migra a otro
servidor**. Copia todas las carpetas (recibidos, enviados, borradores, subcarpetas) con adjuntos,
fechas originales y marcas de leído, destacado y respondido. Cada vez que la repetís **solo baja lo
nuevo**, y nunca modifica nada en el servidor: no marca como leído ni borra.

Sirve con cualquier proveedor que tenga IMAP: cPanel, Hostinger, Gmail/Google Workspace, Zoho,
IONOS, Titan, GoDaddy, Yahoo o cualquier otro servidor que cargues a mano.

Solo necesita Python (ya instalado). No usa librerías externas.

## Cómo se abre

Doble clic en **«Migrador de correo»** en el escritorio (o en `Migrador.bat`, en esta carpeta).
Se abre la ventana de la aplicación y, minimizada en la barra de tareas, una ventana negra: es el
motor, **no la cierres mientras copiás o migrás**. Para salir, cerrá las dos.

> El acceso directo usa el ícono `ui\icono.ico`. Si alguna vez se borra, se vuelve a crear con
> clic derecho en `Migrador.bat` → «Enviar a» → «Escritorio (crear acceso directo)».

## Inicio

Es lo primero que ves al abrir la app. Para volver desde cualquier pantalla, tocá **Inicio** en la
barra lateral o el **logo**. Muestra:

- **Números clave:** cuántas cuentas hay, cuántos correos guardados y cuánto ocupan, cuándo fue la
  última copia y si la copia automática está activa.
- **Para revisar:** lo que necesita atención (cuentas sin copia, copias de más de un mes, errores,
  claves sin guardar o un servidor que conviene cambiar), cada cosa con su botón para resolverla.
- **Tus cuentas:** una tabla con la copia de cada una, la fecha y su estado (al día, vieja o con
  error).
- **Actividad reciente:** las últimas copias, migraciones y copias automáticas.
- **«Actualizar copia»:** actualiza de una vez todas las cuentas que tienen la clave cargada.

## Los cinco pasos

1. **Servidor actual.** Donde están hoy los correos. Elegí el proveedor y probá la conexión.
2. **Cuentas.** Las casillas, cada una con su clave. «Probar cuentas» muestra cuántos correos y
   carpetas tiene cada una. Activá **«Guardar las claves en este equipo»** para no tener que
   escribirlas cada vez. Cada cuenta puede tener **su propio servidor** (debajo del correo,
   «Cambiar»): sirve para respaldar casillas de distintos clientes, cada una en su hosting, sin
   tocar el paso 1. Al agregar una cuenta, la app averigua el servidor por el dominio. Si la dejás
   sin servidor, usa el del paso 1.
3. **Copia local.** «Hacer copia local» guarda todo en este equipo. Después, **«Actualizar copia»**
   baja solo lo nuevo. Cada cuenta muestra la fecha de su última copia, y la app te avisa si pasó
   más de un mes. Se puede terminar acá: es tu copia de seguridad.
4. **Migrar (opcional).** Solo si querés pasar los correos a otro servidor. Cargás el servidor
   nuevo, el correo y la clave de cada casilla allá, y elegís **desde dónde**:
   - **Desde la copia local:** sube lo que tenés en el equipo. No necesita el servidor viejo, así
     que sirve aunque ya no exista.
   - **Desde el servidor actual:** trae primero lo último del servidor viejo y después sube todo.
5. **Verificar.** Compara carpeta por carpeta el servidor actual, la copia local y el servidor
   nuevo. Si el servidor viejo ya no responde, compara la copia local con el nuevo. Además te guía
   en el cambio de DNS.

Podés pausar, cancelar o cerrar en cualquier momento: la próxima vez sigue donde quedó.

## Liberar espacio (cuando una casilla no entra en el servidor nuevo)

En el paso 4, la sección **«Liberar espacio»** permite elegir, por cuenta, qué correos **no se
suben**. **Nada se borra**: lo que no se sube sigue en la copia local, y sus adjuntos se guardan
además como archivos comunes en `C:\MigracionCorreos\adjuntos\<correo>\`, en una carpeta por
correo con fecha, remitente y asunto. Así se abren sin programa de correo.

- **Límite del buzón:** los MB que permite el servidor nuevo. El medidor muestra cuánto se sube,
  cuánto queda libre y para cuántos meses alcanza al ritmo de crecimiento de la casilla.
- **Reglas:** papelera y spam; boletines y publicidad (correos con «darse de baja»); correos
  duplicados; **subir solo desde** un mes (lo anterior queda en la copia).
- **Los correos más pesados:** destildá los que no quieras subir. Si una regla deja afuera algo
  importante (por ejemplo, un estatuto anterior a la fecha), tildalo para **subirlo igual**.
- Los adjuntos de lo que no se sube se guardan solos al migrar. También están los botones
  «Guardar adjuntos de lo que no se sube» y «Guardar todos los adjuntos».
- **Cuidado:** cuando des de baja el servidor viejo, lo que no se subió va a existir **solo en la
  copia local**. Guardá una copia de `C:\MigracionCorreos` en un disco externo.

## Copia automática

En el paso 3, la tarjeta **«Copia automática»** actualiza la copia local sola, sin abrir la app,
los días y a la hora que elijas. Viene **desactivada**; al activarla sugiere el domingo a las 22:00.

- Necesita **«Guardar las claves en este equipo»** (paso 2), porque nadie va a estar ahí para
  escribirlas. Si después las desactivás, la copia automática se apaga sola.
- La computadora tiene que estar **prendida y con tu sesión iniciada**. Si a esa hora estaba
  apagada, la copia se hace apenas la prendas. Si falla (por ejemplo, Google Drive todavía no
  arrancó), Windows la reintenta hasta 3 veces cada 15 minutos.
- **«Probar ahora»** la ejecuta en el momento para confirmar que funciona.
- El resultado de la última copia automática (cuándo, cuántos correos nuevos, errores) aparece en
  la misma tarjeta, y el detalle en `registros\…_auto_respaldar.log`.
- Por dentro es una tarea del Programador de tareas de Windows llamada
  `\MigradorCorreos\CopiaAutomatica`. Se maneja desde la app; no hace falta tocarla a mano.
- Si la copia automática arranca mientras estás usando la app, una espera a la otra: nunca
  escriben a la vez.

## Mudar un dominio sin perder correos

1. **Copia local** (paso 3) mientras el dominio sigue en el servidor viejo.
2. Creá las casillas en el hosting nuevo y **cambiá los registros MX (o los DNS)**. Marcalo en el
   paso 5.
3. Esperá a que se propague (hasta un día) y **migrá «Desde el servidor actual»** (paso 4): trae
   también lo que siguió llegando al viejo durante la propagación.
4. Verificá y recién entonces das de baja el servidor anterior.

> **Importante:** como servidor actual usá el **nombre del servidor** (por ejemplo
> `server123.tuhosting.com`, el que muestra tu cPanel) y no `mail.tudominio.com`: después del cambio de DNS, ese nombre
> apunta al hosting nuevo. Igual la app se protege: en la primera copia guarda la huella del
> servidor, y si después detecta que es otro, se detiene sin copiar nada y te dice qué poner.

**Después de migrar**, cambiá el servidor de la cuenta al nuevo (paso 2, «Cambiar», por ejemplo
`imap.hostinger.com`). La próxima copia sigue en la misma carpeta: reconoce los correos que ya
tenías y baja solo los nuevos, sin tocar lo que ya estaba guardado.

## Seguridad

- La aplicación solo funciona en tu equipo: no se puede abrir desde otra computadora ni desde otra
  página web.
- Si activás «Guardar las claves en este equipo», se guardan **cifradas con tu usuario de Windows**
  en `%APPDATA%\MigradorCorreos\claves.bin`, fuera de la carpeta del programa. Solo tu usuario, en esta
  computadora, puede leerlas. Si lo desactivás, se borran.
- `cuentas.csv` guarda solo los correos, nunca las claves.

## Dónde queda cada cosa

- **Copia local**: la carpeta elegida en «Opciones avanzadas» del paso 1 (por defecto
  `C:\MigracionCorreos\respaldo`), una subcarpeta por cuenta y por carpeta de correo. Cada correo es
  un `.eml` completo con adjuntos que abre Outlook o Thunderbird. Conviene copiarla cada tanto a un
  disco externo.
- **Registros**: carpeta `registros\`, uno por cada tarea.
- **Errores puntuales** (por ejemplo, un correo más grande de lo que acepta el destino):
  `<copia local>\<correo>\_errores.csv`.

## Detalles

- Las carpetas especiales se traducen solas al migrar: Enviados, Borradores, Spam y Papelera van a
  sus equivalentes, y las subcarpetas se recrean igual.
- Desde Gmail: las etiquetas pasan como carpetas, «Destacados» e «Importantes» no se duplican y de
  «Todos» solo se copian los archivados (a la carpeta Archivo).
- Los correos marcados como borrados pero sin purgar no se suben.
- Si una casilla usaba POP3 en alguna computadora, parte del correo puede estar solo en esa
  computadora y no en el servidor: eso hay que exportarlo desde Outlook.

## Para mejorar la app (o pedirle ayuda a una IA)

La documentación técnica está en `AGENTS.md` (empezá por ahí) y en la carpeta `docs/`:
arquitectura, cómo probarla, por qué está hecha así y la lista de mejoras pendientes. Cualquier
IA (Claude, Codex, Gemini, Cursor…) que abra esta carpeta la encuentra sola. Antes de dar por
buena una mejora, tiene que pasar `python pruebas/probar_todo.py`.

## Desde la terminal (opcional)

El mismo motor funciona sin interfaz, con la configuración y las claves guardadas por la app:

```
python migrador.py respaldar
python migrador.py respaldar --cuenta info@tudominio.com
python migrador.py subir
python migrador.py migrar
python migrador.py verificar
```
