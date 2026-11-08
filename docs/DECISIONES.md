# Decisiones

Por qué el proyecto es como es. Antes de deshacer algo de esta lista, leé el motivo.

## Producto

**D1. IMAP, no SMTP ni POP3.** SMTP solo envía. POP3 no ve carpetas ni enviados. IMAP lee todas las
carpetas con sus marcas y fechas, y permite subir conservándolas (`APPEND` con marcas y fecha).

**D2. Primero a disco, después al destino.** En vez de copiar servidor a servidor, todo pasa por
una copia local. Eso da un respaldo propio, permite subir aunque el servidor viejo ya no exista y
hace los reintentos baratos.

**D3. La copia local es la función principal; migrar es opcional.** Fue un pedido explícito desde el
principio: copias de seguridad periódicas «por si el hosting cae», no solo para migrar. De ahí salen
los cinco pasos (Servidor actual → Cuentas → Copia local → Migrar opcional → Verificar), la fecha de
la última copia por cuenta y la copia automática.

**D4. Migrar elige la fuente: «desde la copia local» (`subir`) o «desde el servidor actual»
(`migrar`).** La primera sirve cuando el servidor viejo ya no está. La segunda es la correcta
después de cambiar el DNS, para traer lo que llegó durante la propagación. Reemplazó a un
interruptor «De una vez / Por etapas» que resultaba confuso.

**D5. Genérica, no atada a un proveedor.** Proveedores precargados más «Otro servidor», para
reutilizarla en cualquier migración.

**D6. Estilo neutro**, sin marca, para que se pueda usar con cualquier cliente.

## Seguridad

**D7. Interfaz web local en lugar de Tkinter o un .exe.** Con solo la biblioteca estándar no hay
interfaz moderna. Un servidor HTTP local más HTML, CSS y JS dan una app vistosa sin instalar nada,
y la ventana `--app` de Edge la hace parecer una aplicación de escritorio. Contras asumidos: hace
falta la ventana negra del servidor, y hubo que protegerla (D8).

**D8. Solo 127.0.0.1, token por sesión, control de `Host` y puerto exclusivo.** Cualquier página
abierta en el navegador podría intentar hablarle a un servidor local: el token y el control de
`Host` lo impiden. El puerto exclusivo se agregó después de que la app «se metió» en el puerto de
otra app local (ver DESARROLLO.md, «Trampas conocidas»).

**D9. Claves cifradas con DPAPI y fuera de la carpeta del programa.** Primero se guardaban en texto plano en
`cuentas.csv`, que puede estar en una carpeta sincronizada (Drive, OneDrive). Se pasaron a `%APPDATA%` cifradas con el usuario de Windows: sin
dependencias, solo legibles por ese usuario en ese equipo, y compatibles con la tarea programada
(que corre como el mismo usuario). Si se apaga «Guardar las claves», el archivo se borra.

**D10. El origen es de solo lectura** (`EXAMINE` + `BODY.PEEK`): migrar o respaldar no debe cambiar
nada para quien sigue usando esas casillas.

## Integridad de los datos

**D11. Incremental por (UIDVALIDITY, UID).** Es lo que garantiza el estándar IMAP para identificar
un mensaje dentro de una carpeta. Si cambia el UIDVALIDITY, se baja de nuevo y la subida deduplica.

**D12. Deduplicar en dos capas** (sha256 local + Message-ID o huella en el destino). La primera es
rápida; la segunda protege si se pierde el estado o si alguien subió correos por otro medio. Sin
Message-ID se usa el sha1 de fecha|remitente|asunto, aceptando que dos mensajes idénticos en esos
tres campos se consideren el mismo.

**D13. No subir los marcados `\Deleted`.** En el servidor ya estaban «borrados» para el usuario.

**D14. Gmail: no copiar las vistas virtuales y depurar «Todos».** `\Flagged` e `\Important` son
vistas de otras carpetas. Copiarlas duplicaría correos. De `\All` solo se suben los mensajes que
no están en ninguna otra carpeta (los archivados), a la carpeta Archivo del destino.

**D15. Protección del origen por UIDVALIDITY de INBOX.** Es la señal más confiable de «este es
otro servidor»: la IP puede cambiar por balanceo y el nombre lo cambia el DNS. La sugerencia usa el
nombre inverso de la IP (por ejemplo `server123.tuhosting.com`) y no los nombres del certificado, que son
del dominio y se mudan con el DNS. Este error real se corrigió el 14/10/2026.

**D16. Bloqueo de sistema y no un archivo «.lock» con PID.** `msvcrt.locking` se libera solo si el
proceso muere, así que no deja bloqueos huérfanos. En Windows, `os.kill(pid, 0)` **termina** el
proceso, por eso no se usa para comprobar si un PID sigue vivo.

**D26. Servidor propio por cuenta, opcional.** Es común respaldar casillas de varios clientes, cada
una en su hosting. Con un único `[origen]` había que cambiar el
servidor cada vez. Se agregaron columnas opcionales a `cuentas.csv` en lugar de un archivo nuevo:
un CSV viejo sigue andando, vacío significa «el general», y guardar desde la interfaz conserva lo
que ya estaba. Para un cPanel conviene el nombre real (`server123.tuhosting.com`) y no `mail.dominio`, que
se muda con el DNS: es lo que propone «Averiguar por el dominio».

**D27. Cambio de servidor: adoptar si cambió el nombre, frenar si cambió la máquina.** D15 frena
siempre que cambia el UIDVALIDITY, pero pasar una cuenta de un cPanel a Hostinger es un cambio a
propósito. La señal es el nombre: si el servidor configurado es otro que el de la huella, el usuario
lo cambió; si es el mismo, lo cambió el DNS por debajo y se sigue frenando. Al adoptar, se compara
cada carpeta nueva por cabeceras con **toda** la copia de la cuenta (los correos pueden haber
cambiado de carpeta en la migración) y lo ya presente se anota en `_vistos.json` en vez de bajarse:
los `.eml` viejos no se tocan, porque la copia local puede tener correos que ya no están en ningún
servidor. Las carpetas se reconocen por nombre o por tipo especial
(«Enviados» en Hostinger = `INBOX.Sent` local); si hay dos locales del mismo tipo, se crea una
nueva, igual deduplicada.

## Copia automática

**D17. Programador de tareas de Windows y no un servicio ni la app abierta.** Funciona con la app
cerrada, sin permisos de administrador, y con «ejecutar apenas se pueda» si la computadora estaba
apagada. Se registra por XML porque `schtasks /create` por parámetros no admite varios días a la
vez ni esas opciones. Viene **desactivada por defecto**, con domingo a las 22:00 sugerido.

**D18. Requiere las claves guardadas**: la tarea corre sin nadie delante. La interfaz no deja
activarla sin claves, y apagar las claves la desactiva.

**D19. `automatica.json` separado de `estado_app.json`**: la app guarda su estado desde la memoria
y pisaría lo que escriba otro proceso.

## Liberar espacio

**D23. Liberar espacio = no subir, nunca borrar.** El caso real: una casilla de algo más de
1 GB y un hosting nuevo con 1 GB por buzón. Como se migra desde la copia local, no hace falta
tocar el servidor viejo: se elige qué no se sube y queda todo en la copia.

**D24. Adjuntos aparte como archivos comunes**, «por las dudas». Lo que no se
sube queda en `.eml`, que hace falta abrir con un programa de correo; los adjuntos sueltos se abren
con doble clic.

**D25. La fecha sale del encabezado `Date`** (lo que ve el usuario), con `INTERNALDATE` como
respaldo. Permite, por ejemplo, subir solo el último año y dejar lo anterior en la copia local.

## Técnica

**D20. Sin dependencias.** Se usa con doble clic en cualquier Windows con Python: nada de pip, npm
ni compilación.

**D21. Código y textos en español con voseo**, porque la usan personas hispanohablantes sin perfil técnico.

**D22. `setTimeout` y no `requestAnimationFrame`** para el refresco en vivo (este último se
congela con la ventana minimizada).
