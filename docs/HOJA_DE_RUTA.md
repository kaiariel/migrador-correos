# Hoja de ruta

Ideas para mejorar el proyecto, de más a menos útiles según el uso real. Antes de empezar
cualquiera, leé [DECISIONES.md](DECISIONES.md) y proponela primero en un issue: el proyecto prefiere cambios graduales.

## Prioridad alta

0. ~~Cambiar de servidor de origen después de migrar.~~ Hecho en v9 (D26, D27): cada cuenta guarda
   su servidor y, al cambiarlo, la copia sigue en la misma carpeta sin volver a bajar lo que ya
   estaba.

1. **Aviso cuando falla la copia automática.** Hoy el resultado se ve solo al abrir la app (paso 3).
   Agregar una notificación de Windows (toast) al terminar con errores, y quizás un correo
   opcional.
2. **Retención o rotación de la copia local.** La copia solo crece; los correos borrados en el
   servidor siguen en el disco (a propósito, es un respaldo). Agregar «Ver correos que ya no están
   en el servidor» y la opción de archivarlos aparte, sin borrar nunca de forma automática.
3. **Exportar la copia a un formato de lectura fácil**: `.mbox` por carpeta (Thunderbird lo importa
   directo) y una guía para importarlo en Outlook. Hoy son archivos `.eml` sueltos.
4. **Restaurar a un servidor desde la copia** desde la interfaz, para cualquier cuenta y carpeta.
   Ya es posible con «Migrar → desde la copia local» apuntando al mismo servidor, pero conviene
   un botón «Restaurar» explícito.
5. **Perfiles por cliente.** Desde v9 cada cuenta tiene su propio servidor, que era lo más urgente.
   Falta agrupar por cliente: carpeta de copia, servidor nuevo y programación propios.

## Prioridad media

6. **Buscar en la copia local** (asunto, remitente, fecha) desde la interfaz, leyendo los `.eml`.
7. **Copiar la copia a un disco externo o a otra carpeta** como paso opcional de la copia
   automática (la regla 3-2-1).
8. **Empaquetar como .exe** (PyInstaller) para usarla en una computadora sin Python. Ojo con
   D20: el empaquetado se haría aparte y no agregaría dependencias en tiempo de ejecución.
9. **OAuth2 para Microsoft 365 y Gmail.** Microsoft desactivó las claves en IMAP; Gmail exige
   contraseñas de aplicación. Hoy esos proveedores no están (Microsoft) o funcionan solo con
   contraseña de aplicación (Gmail).
10. **Detección de POP3**: avisar si una casilla tiene muy pocos correos o no tiene Enviados, porque
    puede que el historial esté en el Outlook de alguna computadora (ya pasó en la conversación
    inicial).
11. **Cifrar la copia local** (opcional), por ejemplo con una clave derivada de DPAPI, para casillas
    sensibles.

## Prioridad baja

12. Mostrar el tamaño de cada carpeta y la cantidad de adjuntos en «Probar cuentas».
13. Velocidad: hoy cada `APPEND` es una ida y vuelta. Algunos servidores aceptan `MULTIAPPEND`.
14. Pruebas unitarias de `nombre_destino`, `tipo_especial`, `mutf7_*` e `interpretarLineas`
    (hoy están cubiertas solo por la prueba de punta a punta).
15. Traducción de la interfaz (hoy está todo en español rioplatense/paraguayo).

## Limitaciones conocidas

- La tarea programada corre solo con la sesión de Windows iniciada (lo exige DPAPI).
- Si la unidad donde está el programa (por ejemplo Google Drive) no está montada cuando corre la tarea, falla y Windows la reintenta 3
  veces cada 15 minutos.
- Mensajes de más de 50 MB: Hostinger los rechaza; quedan en `_errores.csv` y en la copia local.
- Las carpetas excluidas se comparan por nombre completo o por el último componente, sin comodines.
