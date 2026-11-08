# Guía para agentes de IA — Migrador de correo

Leé esto antes de tocar el código. Vale para cualquier agente (Claude Code, Codex, Gemini CLI,
Cursor, Copilot…). La guía de uso para personas está en [LEEME.md](LEEME.md).

## Qué es

Aplicación de escritorio para Windows que **hace copias locales de casillas de correo por IMAP** y,
opcionalmente, **las migra a otro servidor**. Nació para pasar las casillas de
clientes de un hosting cPanel a Hostinger sin perder enviados ni adjuntos, y sirve con cualquier
servidor IMAP.

- Interfaz web local (`app.py` + `ui/`) que se abre como ventana con Edge en modo `--app`.
- Motor en Python (`migrador.py`) que también funciona en terminal.
- Copia automática programada con el Programador de tareas de Windows (`programador.py`).
- «Liberar espacio» (`espacio.py`): elegir qué no se sube cuando una casilla no entra en el
  servidor nuevo, y guardar sus adjuntos aparte. **Nunca borra nada.**
- **Solo la biblioteca estándar de Python** (3.12) y **JavaScript sin dependencias**. No hay npm,
  no hay pip, no hay paso de compilación.

## Mapa de documentos

| Documento | Para qué |
|---|---|
| [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md) | Piezas, flujo de datos, formatos de archivo, API HTTP, eventos, invariantes |
| [docs/DESARROLLO.md](docs/DESARROLLO.md) | Cómo correrlo, probarlo con GreenMail, ver la interfaz, trampas conocidas |
| [docs/DECISIONES.md](docs/DECISIONES.md) | Por qué está hecho así (no deshacer sin leer esto) |
| [docs/HOJA_DE_RUTA.md](docs/HOJA_DE_RUTA.md) | Ideas y mejoras pendientes, priorizadas |
| [HISTORIAL.md](HISTORIAL.md) | Qué cambió y cuándo |

## Reglas que no se negocian

1. **Nunca perder ni duplicar correos.** Toda descarga es incremental (UIDVALIDITY + UID) y toda
   subida se deduplica (sha256 en el estado local + Message-ID o huella fecha/remitente/asunto en
   el destino). Si cambiás `respaldar_*`, `subir_*`, `plan_de_subida` o `clave_mensaje`, corré la
   suite completa.
2. **El servidor de origen es de solo lectura.** Se abre con `EXAMINE` (`select(readonly=True)`) y
   se lee con `BODY.PEEK[]`: no marca como leído, no mueve, no borra. No agregues nada que escriba
   en el origen.
3. **Las claves nunca se escriben en texto plano**: ni en `cuentas.csv`, ni en registros, ni en
   mensajes de error, ni en el chat. Se guardan solo cifradas con DPAPI (`guardar_claves`).
4. **La app solo escucha en 127.0.0.1** con token por sesión y control de `Host`. No la abras a la
   red ni quites el token.
5. **No pises la configuración real al probar.** Probá en una carpeta temporal y con las variables
   `MIGRADOR_CLAVES`, `MIGRADOR_TAREA` y `MIGRADOR_SCRIPT_TAREA` (ver DESARROLLO.md). No crees ni
   borres la tarea real `\MigradorCorreos\CopiaAutomatica` sin pedido explícito.
6. **Sin dependencias nuevas** salvo que sean imprescindibles: la app tiene que correr con doble clic en
   cualquier Windows con Python.

## Antes de dar algo por terminado

```
python pruebas/probar_todo.py
```

Tienen que pasar las 16 pruebas (necesita Docker Desktop en marcha). Si tocaste la interfaz,
además mirala en el navegador (ver «Ver la interfaz» en DESARROLLO.md) en claro, oscuro y a 375 px
de ancho.

## Estilo

- **Todo en español**: nombres de funciones y variables (`respaldar_cuenta`, `seleccionadas`),
  comentarios, mensajes y textos de la interfaz.
- Textos de interfaz con **voseo** («Elegí», «Tocá», «Podés»), cortos y sin tecnicismos: quien la
  usa no es programador. Los errores se explican en palabras simples (`explicar_error`).
- Interfaz de **estilo neutro** (sin marca): tokens de color en `:root`, modo
  claro y oscuro, íconos Phosphor en `ui/iconos.js`.
- Cambios **graduales**: El proyecto prefiere pulir lo existente antes que rediseños completos. Si una
  mejora cambia el flujo, proponela primero.
- Comentarios solo donde explican un porqué no evidente; el resto, código claro.

## Dónde vive y qué no subir a ningún lado

Archivos generados al usarla que **no son
código** y no deben compartirse: `config.ini`, `cuentas.csv`, `estado_app.json`,
`automatica.json`, `filtros.json`, `registros/`. La copia de los correos vive fuera de la carpeta del programa (por defecto
`C:\MigracionCorreos\respaldo`) y las claves en `%APPDATA%\MigradorCorreos\claves.bin`.
