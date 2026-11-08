"""Copia automática: una tarea del Programador de tareas de Windows que ejecuta
`migrador.py respaldar --automatica` los días y a la hora elegidos.

La tarea corre con el usuario actual y solo con la sesión iniciada (así puede leer
las claves cifradas). Si a esa hora la computadora estaba apagada, se ejecuta apenas
se prende (StartWhenAvailable). Si falla (por ejemplo, Google Drive todavía no montó
la unidad), Windows la reintenta hasta 3 veces cada 15 minutos.
"""

import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

BASE = Path(__file__).resolve().parent
# MIGRADOR_TAREA y MIGRADOR_SCRIPT_TAREA permiten probar con otra tarea y otro lanzador sin tocar la real
NOMBRE_TAREA = os.environ.get("MIGRADOR_TAREA") or r"\MigradorCorreos\CopiaAutomatica"
DIAS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]  # orden de weekday()
DIAS_XML = {"lunes": "Monday", "martes": "Tuesday", "miercoles": "Wednesday", "jueves": "Thursday",
            "viernes": "Friday", "sabado": "Saturday", "domingo": "Sunday"}
DISPONIBLE = sys.platform == "win32"
SIN_VENTANA = 0x08000000  # CREATE_NO_WINDOW: que schtasks no abra una consola


def interprete():
    """pythonw.exe (sin ventana negra) junto al Python que está corriendo; si no existe, python.exe."""
    exe = Path(sys.executable)
    sin_consola = exe.with_name("pythonw.exe")
    return sin_consola if sin_consola.exists() else exe


def _schtasks(*args):
    r = subprocess.run(["schtasks", *args], capture_output=True, text=True, creationflags=SIN_VENTANA)
    salida = (r.stdout or "") + (r.stderr or "")
    return r.returncode == 0, salida.strip()


def xml_tarea(dias, hora, argumentos, directorio):
    h, m = (int(x) for x in hora.split(":"))
    inicio = datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)
    usuario = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}".lstrip("\\")
    dias_xml = "".join(f"<{DIAS_XML[d]} />" for d in DIAS if d in dias)
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Copia local automática de correo (Migrador de correo). Se configura desde la app.</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{inicio.strftime("%Y-%m-%dT%H:%M:%S")}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByWeek>
        <DaysOfWeek>{dias_xml}</DaysOfWeek>
        <WeeksInterval>1</WeeksInterval>
      </ScheduleByWeek>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(usuario)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT12H</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT15M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(str(interprete()))}</Command>
      <Arguments>{escape(argumentos)}</Arguments>
      <WorkingDirectory>{escape(str(directorio))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def programar(dias, hora, nombre=NOMBRE_TAREA, script=None):
    """Crea o reemplaza la tarea. Devuelve (ok, mensaje)."""
    if not DISPONIBLE:
        return False, "La copia automática solo funciona en Windows."
    dias = [d for d in DIAS if d in dias]
    if not dias:
        return False, "Elegí al menos un día."
    script = Path(script or os.environ.get("MIGRADOR_SCRIPT_TAREA") or BASE / "migrador.py")
    argumentos = f'"{script}" respaldar --automatica'
    contenido = xml_tarea(dias, hora, argumentos, script.parent)
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-16") as f:
        f.write(contenido)
        ruta = f.name
    try:
        ok, salida = _schtasks("/create", "/tn", nombre, "/xml", ruta, "/f")
    finally:
        os.unlink(ruta)
    return ok, "" if ok else f"Windows no aceptó la tarea: {salida}"


def desprogramar(nombre=NOMBRE_TAREA):
    if not DISPONIBLE or not existe(nombre):
        return True, ""
    ok, salida = _schtasks("/delete", "/tn", nombre, "/f")
    return ok, "" if ok else salida


def existe(nombre=NOMBRE_TAREA):
    return DISPONIBLE and _schtasks("/query", "/tn", nombre)[0]


def ejecutar_ahora(nombre=NOMBRE_TAREA):
    ok, salida = _schtasks("/run", "/tn", nombre)
    return ok, "" if ok else salida


def proxima(dias, hora, desde=None):
    """Próxima fecha y hora programada (para mostrar en la app)."""
    if not dias:
        return None
    desde = desde or datetime.now()
    h, m = (int(x) for x in hora.split(":"))
    for i in range(8):
        dia = desde + timedelta(days=i)
        candidato = dia.replace(hour=h, minute=m, second=0, microsecond=0)
        if DIAS[candidato.weekday()] in dias and candidato > desde:
            return candidato
    return None
