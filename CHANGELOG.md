# Qué cambió

## 9.0 — Servidor propio por cuenta (octubre de 2026)

- Cada cuenta puede tener su propio servidor (columnas opcionales en `cuentas.csv`; vacío = el general). «Averiguar por el dominio» lo deduce de los registros MX y, en un cPanel, propone el nombre real del servidor, que no cambia con el DNS.
- Cambio de servidor a propósito sin duplicar: la copia sigue en la misma carpeta, compara cabeceras con toda la copia de la cuenta y baja solo lo nuevo. Los `.eml` existentes no se tocan. Si cambia la máquina con el mismo nombre (el DNS por debajo), se sigue frenando.
- La interfaz ya no se desborda a lo ancho en el celular.
- 16 pruebas de punta a punta.

## 8.2 — Verificar sin el servidor viejo

- «Verificar» ya no exige la clave del servidor actual: si falta, no entra o es el mismo que el nuevo, compara la copia local contra el destino y lo avisa.

## 8.1 — Servidor nuevo igual al actual

- Frena si el servidor nuevo apunta a la misma máquina que el actual (por nombre o IP), un error fácil de cometer que hacía que «Probar» diera bien contra el servidor viejo.

## 8.0 — Liberar espacio

- Sección «Liberar espacio» en Migrar: límite del buzón con medidor y meses de margen, reglas (papelera y spam, boletines, duplicados, subir solo desde una fecha), los correos más pesados con «subir igual» o «dejar afuera», y adjuntos aparte como archivos comunes. Nunca borra.
- Los nombres de archivo ya no terminan en espacio o punto (Windows no los admite).

## 7.1 — Acceso directo y una sola ventana

- Ícono propio y consola del motor minimizada.
- Una sola instancia: abrir de nuevo trae al frente la que ya está abierta, y una versión nueva reemplaza a una vieja que esté libre.

## 7.0 — Página de inicio

- Vista **Inicio** con números clave, «Para revisar» con acciones directas, tabla de cuentas con su estado, actividad reciente y «Actualizar copia» para todas las cuentas.

## 6.0 — Copia automática

- Copia programada con el Programador de tareas de Windows: desactivada por defecto, días y hora a elección, «Probar ahora» y resultado de la última copia.
- Bloqueo entre procesos para que la app y la copia automática no escriban a la vez.
- Suite de pruebas con GreenMail y documentación para agentes de IA (`AGENTS.md`, `docs/`).

## 5.0 — La copia local en el centro

- Cinco pasos: Servidor actual, Cuentas, Copia local, Migrar (opcional, desde la copia o desde el servidor) y Verificar.
- Claves cifradas con DPAPI; `cuentas.csv` deja de guardarlas.
- Fecha de la última copia por cuenta.

## 4.0 — Protección del origen

- Huella del servidor en la primera copia: si el nombre ya apunta al hosting nuevo por el DNS, se frena sin copiar y sugiere el nombre real del servidor viejo.

## 3.0 — Puerto exclusivo

- La app usa un puerto exclusivo desde el 47615 (en Windows, `SO_REUSEADDR` dejaba que dos programas compartieran el mismo puerto).

## 2.0 — Interfaz visual

- App web local con ventana tipo aplicación, progreso en vivo, pausa, cancelación, modo oscuro y vista para celular.
- Proveedores precargados, errores explicados en palabras simples, cuota de espacio y manejo de Gmail.

## 1.0 — Motor de terminal

- Respaldo incremental a `.eml`, subida con deduplicación, traducción de carpetas especiales, verificación de conteos, reintentos y registros.
