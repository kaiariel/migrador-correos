import { ICONOS } from "./iconos.js";

// ------------------------------------------------------------ utilidades
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const ic = (n, cls = "") =>
  `<svg class="ic ${cls}" viewBox="0 0 256 256" fill="currentColor" aria-hidden="true">${ICONOS[n] || ""}</svg>`;
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const NUM = new Intl.NumberFormat("es-ES", { useGrouping: "always" });
const fmtN = (n) => NUM.format(Number(n || 0));
const fmtB = (b) => {
  if (!b) return "0 MB";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (b >= 1024 && i < 4) { b /= 1024; i++; }
  return `${b.toFixed(b < 10 && i > 1 ? 1 : 0).replace(".", ",")} ${u[i]}`;
};
const fmtT = (s) => {
  if (!isFinite(s) || s < 0) return "—";
  s = Math.round(s);
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} h ${m % 60} min`;
};
const fmtFecha = (iso) => iso ? new Date(iso).toLocaleString("es-ES", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "";
const fmtDia = (d) => d.toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "long" });
const diasDesde = (iso) => iso ? Math.floor((Date.now() - Date.parse(iso)) / 864e5) : null;
const hace = (iso) => {
  const d = diasDesde(iso);
  if (d === null) return "";
  if (d <= 0) return `hoy, ${new Date(iso).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" })}`;
  if (d === 1) return "ayer";
  return `hace ${d} días`;
};
const plural = (n, uno, varios) => `${fmtN(n)} ${n === 1 ? uno : varios}`;
const leer = (k, def) => { try { return localStorage.getItem(k) ?? def; } catch { return def; } };
const escribir = (k, v) => { try { localStorage.setItem(k, v); } catch {} };
const demorar = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

async function api(ruta, datos) {
  const r = await fetch(ruta, {
    method: datos === undefined ? "GET" : "POST",
    headers: { "X-Token": window.TOKEN, "Content-Type": "application/json" },
    body: datos === undefined ? undefined : JSON.stringify(datos),
  });
  if (!r.ok) throw new Error(`El migrador respondió ${r.status}`);
  return r.json();
}

// ------------------------------------------------------------ estado
const S = {
  config: null, proveedores: {}, cuentas: [], recordar: false, clavesCifrables: true, trabajo: {}, progreso: {},
  log: [], resultados: {}, app: {}, local: {}, paso: "servidor",
  pruebas: { origen: null, destino: null }, probando: {}, excluidas: new Set(),
  muestras: {}, filtroLog: "todo", conectado: true, siguienteId: 1, fuente: leer("fuente", "copia"),
  automatica: null, autoEnMarcha: false, espacio: {}, espacioAbierto: new Set(), filtros: {},
};
const ACTIVOS = ["corriendo", "pausado", "cancelando"];
const MIGRACION = ["migrar", "respaldar", "subir"];
const DE_LA_VISTA = { copia: ["respaldar"], migrar: ["subir", "migrar"] };
const ocupado = () => ACTIVOS.includes(S.trabajo.estado);
const migrando = () => ocupado() && MIGRACION.includes(S.trabajo.accion);
const enCurso = (accion) => ocupado() && S.trabajo.accion === accion;
const deEstaVista = (accion = S.trabajo.accion) => (DE_LA_VISTA[S.paso] || []).includes(accion);
const nuevaCuenta = (c = {}) => ({
  id: S.siguienteId++, correo: c.correo || "", correo_destino: c.correo_destino || "",
  tiene_clave_origen: !!c.tiene_clave_origen, tiene_clave_destino: !!c.tiene_clave_destino,
  clave_origen: c.clave_origen ?? null, clave_destino: c.clave_destino ?? null,
  // servidor propio de la cuenta (vacío = el servidor actual general del paso 1)
  servidor: c.servidor || "", puerto: c.puerto || "", seguridad: c.seguridad || "", verificar: c.verificar ?? "",
});
// el servidor del que se copia esta cuenta: el suyo o, si no tiene, el general
const servidorDe = (c) => (c.servidor || "").trim() || (S.config.origen.servidor || "").trim();
const conCorreo = () => S.cuentas.filter((c) => c.correo.trim());
const seleccionadas = () => S.cuentas.filter((c) => c.correo.trim() && !S.excluidas.has(c.id));
const idSeguro = (correo) => correo.replace(/[^a-z0-9]/gi, "_");
function guardarExcluidas() {
  escribir("excluidas", JSON.stringify(S.cuentas.filter((c) => S.excluidas.has(c.id)).map((c) => c.correo.trim().toLowerCase())));
}
const resultado = (accion, correo) => S.resultados[accion]?.[correo];
// prueba del servidor actual: vale la de «probar_origen» o la de una prueba completa anterior
const pruebaOrigen = (correo) => {
  const r = resultado("probar_origen", correo) || resultado("probar", correo);
  return r && (r.ok ? { ok: true, ...r.resultado.origen } : { ok: false, error: r.error });
};
const pruebaDestino = (correo) => {
  const r = resultado("probar_destino", correo) || resultado("probar", correo);
  return r && (r.ok ? { ok: true, ...r.resultado.destino } : { ok: false, error: r.error });
};

// ------------------------------------------------------------ avisos y modal
function aviso(texto, tipo = "info") {
  const icono = { ok: "check-circle", error: "warning-circle", info: "info" }[tipo];
  const el = document.createElement("div");
  el.className = `aviso-toast ${tipo}`;
  el.innerHTML = `${ic(icono)}<span>${texto}</span>`;
  $("#avisos").append(el);
  setTimeout(() => { el.classList.add("saliendo"); setTimeout(() => el.remove(), 220); }, tipo === "error" ? 7000 : 4200);
}

function abrirModal({ titulo, texto = "", cuerpo = "", aceptar = "Aceptar", cancelar = "Cancelar", peligro = false }) {
  const d = $("#modal");
  d.innerHTML = `<form method="dialog">
    <div class="modal-cuerpo"><h2>${titulo}</h2>${texto ? `<p>${texto}</p>` : ""}${cuerpo}</div>
    <div class="modal-pie">
      <button class="boton fantasma" value="no">${cancelar}</button>
      <button class="boton ${peligro ? "peligro" : "primario"}" value="si">${aceptar}</button>
    </div></form>`;
  d.returnValue = "";
  return new Promise((res) => {
    d.onclose = () => res(d.returnValue === "si" ? new FormData(d.querySelector("form")) : null);
    d.showModal();
    d.querySelector("textarea, input")?.focus();
  });
}

function mostrarGuardado() {
  const g = $("#guardado");
  if (!g) return;
  g.classList.add("visible");
  clearTimeout(g._t);
  g._t = setTimeout(() => g.classList.remove("visible"), 1600);
}

// ------------------------------------------------------------ guardar configuración y cuentas
const guardarConfig = demorar(async () => {
  try { S.config = (await api("/api/config", S.config)).config; mostrarGuardado(); }
  catch (e) { aviso(`No se pudo guardar: ${esc(e.message)}`, "error"); }
}, 450);

let guardandoCuentas = Promise.resolve();
async function guardarCuentasYa() {
  const datos = {
    recordar: S.recordar,
    cuentas: conCorreo().map((c) => ({
      correo: c.correo.trim(), correo_destino: c.correo_destino.trim(),
      clave_origen: c.clave_origen, clave_destino: c.clave_destino,
      servidor: (c.servidor || "").trim(), puerto: c.puerto, seguridad: c.seguridad, verificar: c.verificar,
    })),
  };
  guardandoCuentas = api("/api/cuentas", datos).then((r) => {
    if (!r.ok) throw new Error(r.error);
    if (r.automatica) S.automatica = r.automatica;
    if (r.automatica_apagada) aviso("Se desactivó la copia automática porque necesita las claves guardadas.", "info");
    for (const pub of r.cuentas) {
      const c = S.cuentas.find((x) => x.correo.trim().toLowerCase() === pub.correo.toLowerCase());
      if (c) {
        c.tiene_clave_origen = pub.tiene_clave_origen;
        c.tiene_clave_destino = pub.tiene_clave_destino;
        c.clave_origen = null;
        c.clave_destino = null;
      }
    }
    mostrarGuardado();
    actualizarPasos();
  }).catch((e) => aviso(`No se pudieron guardar las cuentas: ${esc(e.message)}`, "error"));
  return guardandoCuentas;
}
const guardarCuentas = demorar(guardarCuentasYa, 600);

// ------------------------------------------------------------ navegación
const copiaMasVieja = () => {
  const fechas = seleccionadas().map((c) => S.local[c.correo.trim()]?.fecha).filter(Boolean);
  return fechas.length ? fechas.sort()[0] : null;
};

const PASOS = [
  { id: "inicio", titulo: "Inicio", sub: () => "Resumen", icono: "house" },
  { id: "servidor", titulo: "Servidor actual", sub: () => "De dónde se copian" },
  { id: "cuentas", titulo: "Cuentas", sub: () => { const n = conCorreo().length; return n ? plural(n, "casilla", "casillas") : "Casillas a copiar"; } },
  { id: "copia", titulo: "Copia local", sub: () => enCurso("respaldar") ? "Copiando…" : copiaMasVieja() ? `Última: ${hace(copiaMasVieja())}` : "Respaldo en este equipo" },
  { id: "migrar", titulo: "Migrar", sub: () => ocupado() && ["subir", "migrar"].includes(S.trabajo.accion) ? "En curso…" : "Opcional · a otro servidor" },
  { id: "verificar", titulo: "Verificar", sub: () => "Conteos y DNS" },
];

function estadoPaso(id) {
  if (id === "servidor") return S.pruebas.origen?.ok || S.app.ultima_copia || copiaMasVieja() ? "hecho" : "";
  if (id === "cuentas") {
    if (enCurso("probar_origen")) return "activo";
    const cs = seleccionadas();
    if (cs.length && cs.every((c) => pruebaOrigen(c.correo.trim())?.ok)) return "hecho";
    return cs.length && cs.every((c) => S.local[c.correo.trim()]?.fecha) ? "hecho" : "";
  }
  if (id === "copia") return enCurso("respaldar") ? "activo" : (copiaMasVieja() ? "hecho" : "");
  if (id === "migrar") return ocupado() && ["subir", "migrar", "probar_destino"].includes(S.trabajo.accion) ? "activo" : (S.app.ultima_migracion ? "hecho" : "");
  if (id === "verificar") return enCurso("verificar") ? "activo" : (S.app.ultima_verificacion?.ok ? "hecho" : "");
}

function actualizarPasos() {
  $("#pasos").innerHTML = PASOS.map((p, i) => {
    const est = p.icono ? "" : estadoPaso(p.id);
    return `<button class="paso ${est} ${p.icono ? "paso-inicio" : ""}" data-ir="${p.id}" ${S.paso === p.id ? 'aria-current="page"' : ""}>
      <span class="paso-numero">${p.icono ? ic(p.icono) : est === "hecho" ? ic("check") : i}</span>
      <span class="paso-texto"><strong>${p.titulo}</strong><small>${esc(p.sub())}</small></span>
    </button>`;
  }).join("");
}

function irA(paso) {
  S.paso = paso;
  escribir("paso", paso);
  render();
  $("#vista").focus({ preventScroll: true });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function render() {
  actualizarPasos();
  $("#vista").innerHTML = `<div class="vista">${VISTAS[S.paso]()}</div>`;
  const l = $("#lineas");
  if (l) l.scrollTop = l.scrollHeight;
}

const cabecera = (eyebrow, titulo, texto) => `
  <header class="cabecera">
    <div><div class="eyebrow">${eyebrow}</div><h1>${titulo}</h1><p>${texto}</p></div>
    <span class="guardado" id="guardado">${ic("check")}Guardado</span>
  </header>`;

const pie = (atras, adelante) => `<div class="pie-vista">${atras || "<span></span>"}${adelante || ""}</div>`;
const botonIr = (paso, texto, clase = "primario") => `<button class="boton ${clase}" data-ir="${paso}">${texto}${ic("arrow-right")}</button>`;
const botonVolver = (paso, texto) => `<button class="boton fantasma" data-ir="${paso}">← ${texto}</button>`;

// ------------------------------------------------------------ tarjetas de servidor (origen en el paso 1, destino en el 4)
function pastillaPrueba(lado) {
  if (S.probando[lado]) return `<span class="pastilla activa"><span class="punto"></span>Probando…</span>`;
  const p = S.pruebas[lado];
  if (!p) return `<span class="pastilla">Sin probar</span>`;
  return p.ok ? `<span class="pastilla ok">${ic("check-circle")}Responde</span>`
              : `<span class="pastilla error">${ic("warning-circle")}Sin conexión</span>`;
}
function detallePrueba(lado) {
  const p = S.pruebas[lado];
  if (!p) return "";
  if (!p.ok) return `<span class="error">${esc(p.error)}</span>`;
  return `Respondió en ${fmtN(p.ms)} ms${p.aviso ? ` · ${esc(p.aviso)}` : ""}`;
}

function tarjetaServidor(lado) {
  const s = S.config[lado];
  const p = S.proveedores[s.proveedor] || S.proveedores.otro;
  const seg = [["ssl", "SSL/TLS"], ["starttls", "STARTTLS"], ["ninguna", "Sin cifrar"]];
  return `<section class="tarjeta servidor" data-lado="${lado}" id="servidor-${lado}">
    <div class="servidor-cabeza">
      <div class="lado">
        <span class="lado-icono">${ic(lado === "origen" ? "hard-drives" : "cloud-arrow-up")}</span>
        <div><small>${lado === "origen" ? "Servidor actual" : "Servidor nuevo"}</small><strong>${esc(p.nombre)}</strong></div>
      </div>
      <span id="pastilla-${lado}">${pastillaPrueba(lado)}</span>
    </div>
    <label class="campo">Proveedor
      <select class="entrada" data-servidor="proveedor">
        ${Object.entries(S.proveedores).map(([k, v]) => `<option value="${k}" ${k === s.proveedor ? "selected" : ""}>${esc(v.nombre)}</option>`).join("")}
      </select>
    </label>
    <div class="fila">
      <label class="campo crece">Servidor IMAP
        <input class="entrada" data-servidor="servidor" value="${esc(s.servidor)}" placeholder="mail.tudominio.com" spellcheck="false" autocomplete="off">
      </label>
      <label class="campo corto">Puerto
        <input class="entrada num" type="number" min="1" max="65535" data-servidor="puerto" value="${s.puerto}">
      </label>
    </div>
    <div class="campo"><span>Seguridad</span>
      <div class="segmentado" role="group" aria-label="Seguridad">
        ${seg.map(([v, t]) => `<button type="button" data-seguridad="${v}" aria-pressed="${s.seguridad === v}">${t}</button>`).join("")}
      </div>
    </div>
    <label class="interruptor"><input type="checkbox" data-servidor="verificar" ${s.verificar ? "checked" : ""}><span class="pista"></span>Verificar el certificado del servidor</label>
    <p class="ayuda">${ic("info")}<span>${esc(p.ayuda)}</span></p>
    ${lado === "destino" && s.servidor && s.servidor.trim().toLowerCase() === (S.config.origen.servidor || "").trim().toLowerCase()
      ? `<div class="banner error" style="margin:0">${ic("warning-circle")}<span>Este es el mismo servidor que el actual. Poné acá el del hosting nuevo${S.proveedores[s.proveedor]?.servidor ? ` (${esc(S.proveedores[s.proveedor].servidor)})` : ""}.</span></div>` : ""}
    <div class="acciones">
      <span class="detalle-prueba" id="detalle-${lado}">${detallePrueba(lado)}</span>
      <button class="boton secundario" data-accion="probar-servidor" data-lado="${lado}">${ic("plugs-connected")}Probar conexión</button>
    </div>
  </section>`;
}

function refrescarPrueba(lado) {
  const p = $(`#pastilla-${lado}`), d = $(`#detalle-${lado}`);
  if (p) p.innerHTML = pastillaPrueba(lado);
  if (d) d.innerHTML = detallePrueba(lado);
  actualizarPasos();
}

async function probarServidor(lado) {
  S.probando[lado] = true;
  refrescarPrueba(lado);
  try {
    await api("/api/config", S.config);
    S.pruebas[lado] = await api("/api/probar-servidor", { servidor: S.config[lado] });
  } catch (e) {
    S.pruebas[lado] = { ok: false, error: e.message };
  }
  S.probando[lado] = false;
  refrescarPrueba(lado);
}

// ------------------------------------------------------------ inicio
const NOMBRE_ACCION = {
  respaldar: "Copia local", subir: "Migración desde la copia", migrar: "Migración desde el servidor",
  verificar: "Verificación", probar: "Prueba de conexión", probar_origen: "Prueba de conexión",
  probar_destino: "Prueba del servidor nuevo", automatica: "Copia automática",
};

function estadoCopiaCuenta(correo) {
  const l = S.local[correo];
  const ultimo = resultado("respaldar", correo);
  if (ultimo && !ultimo.ok && ultimo.error !== "Cancelado") return ["error", "Falló la última copia", ultimo.error];
  const auto = S.automatica?.ultima;
  const errAuto = auto?.errores?.[correo];
  if (errAuto && (!l?.fecha || auto.fecha >= l.fecha)) return ["error", "Falló la copia automática", errAuto];
  if (!l?.fecha) return ["aviso", "Sin copia", ""];
  const d = diasDesde(l.fecha);
  return d > 30 ? ["aviso", `Hace ${d} días`, "Conviene actualizarla"] : ["ok", "Al día", ""];
}

function avisosInicio() {
  const lista = [];
  const cuentas = conCorreo();
  const host = S.config.origen.servidor;
  const usanGeneral = cuentas.filter((c) => !(c.servidor || "").trim());
  if (!cuentas.length) lista.push({ tipo: "info", texto: "Agregá las casillas que querés respaldar.", ir: "cuentas", boton: "Agregar cuentas" });
  else if (!host && usanGeneral.length) lista.push({ tipo: "info", texto: `${plural(usanGeneral.length, "cuenta no tiene", "cuentas no tienen")} servidor: configurá el general o uno propio en cada una.`, ir: "cuentas", boton: "Revisar" });
  if (migrando()) lista.push({ tipo: "info", texto: `Hay una tarea en curso: ${NOMBRE_ACCION[S.trabajo.accion].toLowerCase()}.`, ir: S.trabajo.accion === "respaldar" ? "copia" : "migrar", boton: "Ver progreso" });
  const conError = cuentas.filter((c) => estadoCopiaCuenta(c.correo.trim())[0] === "error");
  if (conError.length) lista.push({ tipo: "error", texto: `${plural(conError.length, "cuenta tuvo", "cuentas tuvieron")} errores en la última copia.`, ir: "copia", boton: "Revisar" });
  const sinCopia = cuentas.filter((c) => !S.local[c.correo.trim()]?.fecha);
  if (cuentas.length && sinCopia.length) lista.push({ tipo: "aviso", texto: `${plural(sinCopia.length, "cuenta todavía no tiene", "cuentas todavía no tienen")} copia local.`, ir: "copia", boton: "Hacer copia" });
  const viejas = cuentas.filter((c) => diasDesde(S.local[c.correo.trim()]?.fecha) > 30);
  if (viejas.length) lista.push({ tipo: "aviso", texto: `La copia de ${plural(viejas.length, "cuenta tiene", "cuentas tienen")} más de un mes.`, ir: "copia", boton: "Actualizar" });
  const propio = usanGeneral.map((c) => S.local[c.correo.trim()]?.nombre_servidor).find(Boolean);
  if (propio && host && host.toLowerCase() !== propio.toLowerCase() && /^(mail|imap|webmail)\./i.test(host)) {
    lista.push({ tipo: "aviso", texto: `Como servidor actual usás <b>${esc(host)}</b>. Si vas a mudar el dominio, conviene <b>${esc(propio)}</b>: ese nombre no cambia con el DNS.`, ir: "servidor", boton: "Cambiar" });
  }
  if (S.automatica?.disponible && !S.automatica.activa && cuentas.length) {
    lista.push(S.recordar
      ? { tipo: "info", texto: "La copia automática está desactivada.", ir: "copia", boton: "Programar" }
      : { tipo: "info", texto: "La copia automática está desactivada: necesita que guardes las claves.", ir: "cuentas", boton: "Guardar claves" });
  }
  return lista;
}

function actividadInicio() {
  const filas = (S.app.historial || []).filter((h) => !h.accion.startsWith("probar")).map((h) => ({ ...h }));
  const u = S.automatica?.ultima;
  if (u) filas.push({ fecha: u.fecha, accion: "automatica", cuentas: u.cuentas, resultado: u.ok ? "ok" : "con errores", nuevos: u.nuevos });
  return filas.sort((a, b) => (a.fecha < b.fecha ? 1 : -1)).slice(0, 7);
}

function vistaInicio() {
  const cuentas = conCorreo();
  let mensajes = 0, bytes = 0, conCopia = 0, ultima = null;
  for (const c of cuentas) {
    const l = S.local[c.correo.trim()];
    if (l?.fecha) { conCopia++; mensajes += l.mensajes; bytes += l.bytes; if (!ultima || l.fecha > ultima) ultima = l.fecha; }
  }
  const a = S.automatica;
  const avisos = avisosInicio();
  const actividad = actividadInicio();
  const icono = { error: "warning-circle", aviso: "warning", info: "info" };
  const pastillaRes = (r) => r === "ok" ? `<span class="pastilla ok">${ic("check")}Bien</span>` : r === "cancelado" ? `<span class="pastilla aviso">Cancelada</span>` : `<span class="pastilla error">Con errores</span>`;
  const kpi = (icono2, etiqueta, valor, sub, clase = "") => `<div class="tarjeta kpi ${clase}">
      <span class="kpi-icono">${ic(icono2)}</span><small>${etiqueta}</small><strong class="num">${valor}</strong><span>${sub}</span></div>`;
  const bloqueado = ocupado() || !cuentas.some(servidorDe);
  return `<header class="cabecera">
    <div><div class="eyebrow">Migrador de correo</div><h1>Inicio</h1><p>El estado de tus copias de correo de un vistazo.</p></div>
    <div class="cabecera-acciones">
      <button class="boton secundario" data-accion="abrir" data-que="respaldo">${ic("folder-open")}Abrir copia</button>
      <button class="boton primario" data-accion="actualizar-todo" ${bloqueado ? "disabled" : ""}>${ic("arrows-clockwise")}Actualizar copia</button>
    </div>
  </header>
  <div class="kpis">
    ${kpi("users-three", "Cuentas", fmtN(cuentas.length), cuentas.length ? `${fmtN(conCopia)} con copia local` : "Todavía ninguna")}
    ${kpi("envelope-simple-open", "Correos guardados", fmtN(mensajes), bytes ? `${fmtB(bytes)} en este equipo` : "Sin copia todavía")}
    ${kpi("clock-counter-clockwise", "Última copia", ultima ? hace(ultima) : "—", ultima ? fmtFecha(ultima) : "Hacela en el paso 3", ultima && diasDesde(ultima) > 30 ? "alerta" : "")}
    ${kpi("calendar-check", "Copia automática", a?.activa ? "Activa" : "Desactivada", a?.activa && a.proxima ? `Próxima: ${fmtDiaHora(a.proxima)}` : "Se programa en el paso 3", a?.activa ? "bien" : "")}
  </div>
  <div class="inicio-rejilla">
    <div class="inicio-columna">
      <section class="tarjeta">
        <h2>Para revisar</h2>
        ${avisos.length ? `<ul class="lista-avisos">${avisos.map((v) => `<li class="${v.tipo}">${ic(icono[v.tipo])}<span>${v.texto}</span><button class="boton secundario chico" data-ir="${v.ir}">${v.boton}</button></li>`).join("")}</ul>`
          : `<p class="todo-bien">${ic("check-circle")}Todo en orden. No hay nada pendiente.</p>`}
      </section>
      <section class="tarjeta tabla-resumen-caja">
        <div class="seccion-cabeza"><h2>Tus cuentas</h2><button class="boton fantasma chico" data-ir="cuentas">${ic("plus")}Agregar o editar</button></div>
        ${cuentas.length ? `<div class="tabla-desliza"><table class="tabla-resumen">
          <thead><tr><th>Cuenta</th><th>Copia local</th><th>Última copia</th><th>Estado</th></tr></thead>
          <tbody>${cuentas.map((c) => {
            const correo = c.correo.trim(), l = S.local[correo] || {};
            const [clase, texto, detalle] = estadoCopiaCuenta(correo);
            return `<tr>
              <td><span class="cuenta-nombre">${avatar(correo, true)}<span>${esc(correo)}</span></span></td>
              <td class="num">${l.fecha ? `${fmtN(l.mensajes)} correos · ${fmtB(l.bytes)}<small>${plural(l.carpetas, "carpeta", "carpetas")}</small>` : "—"}</td>
              <td>${l.fecha ? hace(l.fecha) : "Nunca"}</td>
              <td><span class="pastilla ${clase}" title="${esc(detalle)}">${clase === "ok" ? ic("check") : ""}${texto}</span></td>
            </tr>`;
          }).join("")}</tbody></table></div>`
          : `<div class="vacio" style="padding:26px 10px"><p>Todavía no agregaste cuentas.</p><button class="boton primario" data-ir="cuentas">${ic("plus")}Agregar cuentas</button></div>`}
      </section>
    </div>
    <div class="inicio-columna">
      <section class="tarjeta">
        <h2>Actividad reciente</h2>
        ${actividad.length ? `<ul class="actividad">${actividad.map((h) => `<li>
            <span class="actividad-icono">${ic(h.accion === "automatica" ? "calendar-check" : ["subir", "migrar"].includes(h.accion) ? "cloud-arrow-up" : h.accion === "verificar" ? "list-checks" : "cloud-arrow-down")}</span>
            <div><strong>${NOMBRE_ACCION[h.accion] || h.accion}</strong><small>${fmtFecha(h.fecha)} · ${plural(h.cuentas || 0, "cuenta", "cuentas")}${h.nuevos ? ` · ${plural(h.nuevos, "correo nuevo", "correos nuevos")}` : ""}</small></div>
            ${pastillaRes(h.resultado)}
          </li>`).join("")}</ul>`
          : `<p class="sub" style="margin:0">Todavía no hay actividad.</p>`}
      </section>
      <section class="tarjeta">
        <h2>Servidores</h2>
        <div class="servidores-mini">
          <button class="servidor-mini" data-ir="servidor">${ic("hard-drives")}<span><small>Servidor actual (general)</small><strong>${esc(S.config.origen.servidor || "Sin configurar")}</strong></span>${ic("caret-right")}</button>
          ${(() => {
            const propios = [...new Set(cuentas.map((c) => (c.servidor || "").trim()).filter(Boolean))];
            return propios.length ? `<button class="servidor-mini" data-ir="cuentas">${ic("users-three")}<span><small>Servidores propios de cuentas</small><strong>${esc(propios.join(" · "))}</strong></span>${ic("caret-right")}</button>` : "";
          })()}
          <button class="servidor-mini" data-ir="migrar">${ic("cloud-arrow-up")}<span><small>Servidor nuevo (opcional)</small><strong>${esc(S.config.destino.servidor || "Sin configurar")}</strong></span>${ic("caret-right")}</button>
        </div>
      </section>
    </div>
  </div>`;
}

// ------------------------------------------------------------ paso 1: servidor actual
function vistaServidor() {
  const g = S.config.general;
  return `${cabecera("Paso 1 de 5", "Servidor actual", "El servidor donde están hoy los correos. Desde acá se hacen las copias locales y, si querés, la migración.")}
  <div class="servidor-solo">${tarjetaServidor("origen")}</div>
  <details class="tarjeta avanzadas" ${leer("avanzadas", "0") === "1" ? "open" : ""} id="avanzadas">
    <summary>${ic("database")}Opciones avanzadas<span class="caret">${ic("caret-down")}</span></summary>
    <div class="rejilla">
      <div class="campo">Carpeta de la copia local
        <div class="fila">
          <input class="entrada crece" data-general="carpeta_respaldo" value="${esc(g.carpeta_respaldo)}" spellcheck="false">
          <button type="button" class="boton secundario" data-accion="abrir" data-que="respaldo">${ic("folder-open")}Abrir</button>
        </div>
        <span class="nota">Mejor en el disco C: o en un disco externo que en una carpeta sincronizada (Drive, OneDrive): son miles de archivos.</span>
      </div>
      <div class="campo">Cuentas a la vez
        <div class="rango"><input type="range" min="1" max="4" data-general="cuentas_a_la_vez" value="${g.cuentas_a_la_vez}"><output id="salida-hilos">${g.cuentas_a_la_vez}</output></div>
        <span class="nota">2 o 3 es seguro. Más puede hacer que el servidor corte la conexión.</span>
      </div>
      <label class="campo">Carpetas que no se copian
        <input class="entrada" data-general="excluir_carpetas" value="${esc(g.excluir_carpetas.join(", "))}" placeholder="Ej.: Trash, Spam" spellcheck="false">
        <span class="nota">Separadas por comas. Vacío = se copia todo.</span>
      </label>
      <label class="campo">Tamaño de cada tanda de descarga (MB)
        <input class="entrada num" type="number" min="1" max="200" data-general="lote_mb" value="${g.lote_mb}">
        <span class="nota">20 está bien para casi todos los servidores.</span>
      </label>
    </div>
  </details>
  ${pie("", botonIr("cuentas", "Continuar con las cuentas"))}`;
}

// ------------------------------------------------------------ paso 2: cuentas
const COLUMNAS_CUENTAS = "26px minmax(190px, 1.4fr) minmax(150px, 1fr) minmax(190px, 1.5fr) 34px";
const ojo = `<button type="button" data-accion="ver-clave" tabindex="-1" aria-label="Mostrar clave">${ic("eye")}</button>`;

function estadoCuenta(c) {
  const correo = c.correo.trim();
  if (!correo) return `<span class="linea-estado tenue">Escribí el correo</span>`;
  const p = S.progreso[correo];
  if (enCurso("probar_origen") && S.trabajo.cuentas.includes(correo) && p?.fase !== "listo") {
    return `<span class="linea-estado">${ic("circle-notch", "girando")}<span>Probando…</span></span>`;
  }
  const o = pruebaOrigen(correo);
  const local = S.local[correo];
  const lineas = [];
  if (o && !o.ok) lineas.push(`<span class="linea-estado error" title="${esc(o.error)}">${ic("warning-circle")}<span>${esc(o.error)}</span></span>`);
  if (o?.ok) {
    lineas.push(`<span class="linea-estado ok">${ic("check-circle")}<span>${plural(o.mensajes, "correo", "correos")}${o.usado_kb ? ` · ${fmtB(o.usado_kb * 1024)}` : ""}</span></span>`);
    if (o.aviso) lineas.push(`<span class="linea-estado aviso" title="${esc(o.aviso)}">${ic("warning")}<span>El servidor ya no es el de la primera copia</span></span>`);
  }
  if (!o) {
    const sinClave = !c.tiene_clave_origen && !c.clave_origen;
    lineas.push(sinClave ? `<span class="linea-estado aviso">${ic("key")}<span>Falta la clave</span></span>`
                         : `<span class="linea-estado tenue">Sin probar</span>`);
  }
  if (local?.fecha) lineas.push(`<span class="linea-estado tenue">${ic("database")}<span>Copia local: ${hace(local.fecha)}</span></span>`);
  if (o?.ok && o.carpetas?.length) lineas.push(`<button class="ver-carpetas" data-accion="ver-carpetas">Ver ${plural(o.carpetas.length, "carpeta", "carpetas")}</button>`);
  return lineas.join("");
}

function chipsCarpetas(c) {
  const o = pruebaOrigen(c.correo.trim());
  if (!o?.ok || !o.carpetas) return "";
  return o.carpetas.map((f) => `<span class="chip-carpeta">${ic("folder-simple")}${esc(f.nombre)} <b class="num">${fmtN(f.mensajes)}</b></span>`).join("");
}

function lineaServidor(c) {
  const propio = (c.servidor || "").trim();
  const general = (S.config.origen.servidor || "").trim();
  const texto = propio ? `<b>${esc(propio)}</b>`
    : general ? `Servidor general · <b>${esc(general)}</b>` : `<span class="falta">Sin servidor: elegí uno</span>`;
  return `${ic("hard-drives")}<span>${texto}</span>
    <button type="button" class="enlace-mini" data-accion="servidor-cuenta">${propio ? "Cambiar" : "Usar uno propio"}</button>`;
}

function filaCuenta(c) {
  return `<div class="cuenta" data-id="${c.id}">
    <div class="cuenta-fila">
      <input type="checkbox" class="casilla" data-sel ${S.excluidas.has(c.id) ? "" : "checked"} aria-label="Incluir esta cuenta">
      <input class="entrada" data-c="correo" value="${esc(c.correo)}" placeholder="correo@tudominio.com" spellcheck="false" autocomplete="off" aria-label="Correo">
      <div class="clave"><input class="entrada" type="password" data-c="clave_origen" value="${esc(c.clave_origen ?? "")}" placeholder="${c.tiene_clave_origen ? "•••••• guardada" : "Clave"}" autocomplete="new-password" aria-label="Clave">${ojo}</div>
      <div class="estado-cuenta" id="estado-${c.id}">${estadoCuenta(c)}</div>
      <button class="icono-boton peligro" data-accion="quitar-cuenta" aria-label="Quitar cuenta" title="Quitar">${ic("trash")}</button>
    </div>
    <div class="cuenta-servidor" id="servidor-cuenta-${c.id}">${lineaServidor(c)}</div>
    <div class="carpetas-lista" id="carpetas-${c.id}">${chipsCarpetas(c)}</div>
  </div>`;
}

function refrescarServidorCuenta(c) {
  const el = $(`#servidor-cuenta-${c.id}`);
  if (el) el.innerHTML = lineaServidor(c);
}

// Al agregar una cuenta se averigua su servidor por el dominio del correo; queda como propio y se puede cambiar.
async function detectarServidorCuenta(c, avisar = true) {
  const correo = c.correo.trim();
  if (!correo.includes("@") || (c.servidor || "").trim()) return;
  try {
    const r = await api("/api/detectar-servidor", { correo });
    if (!r.ok || c.correo.trim() !== correo || (c.servidor || "").trim()) return;
    Object.assign(c, { servidor: r.servidor, puerto: r.puerto, seguridad: r.seguridad, verificar: r.verificar });
    refrescarServidorCuenta(c);
    guardarCuentas();
    if (avisar) aviso(`${esc(correo)}: servidor <b>${esc(r.servidor)}</b>. ${esc(r.como || "")}`, "ok");
  } catch {}
}

function tablaCuentas() {
  if (!S.cuentas.length) {
    return `<div class="vacio">
      <div class="vacio-icono">${ic("users-three")}</div>
      <strong>Todavía no hay cuentas</strong>
      <p>Agregalas una por una o pegá la lista de correos de una vez.</p>
      <div class="barra-herramientas" style="justify-content:center;margin:16px 0 0">
        <button class="boton primario" data-accion="agregar-cuenta">${ic("plus")}Agregar cuenta</button>
        <button class="boton secundario" data-accion="pegar-lista">${ic("clipboard-text")}Pegar lista</button>
      </div>
    </div>`;
  }
  const todas = S.cuentas.every((c) => !S.excluidas.has(c.id));
  return `<div class="cuentas-cabeza">
      <input type="checkbox" class="casilla" data-sel-todas ${todas ? "checked" : ""} aria-label="Incluir todas">
      <span>Correo</span><span>Clave</span><span>Estado</span><span></span>
    </div>${S.cuentas.map(filaCuenta).join("")}`;
}

function resumenCuentas() {
  let mensajes = 0, kb = 0, probadas = 0;
  for (const c of seleccionadas()) {
    const o = pruebaOrigen(c.correo.trim());
    if (o?.ok) { probadas++; mensajes += o.mensajes; kb += o.usado_kb || 0; }
  }
  return `<div class="dato"><small>Seleccionadas</small><strong class="num">${fmtN(seleccionadas().length)}</strong></div>
    ${probadas ? `<div class="dato"><small>Correos</small><strong class="num">${fmtN(mensajes)}</strong></div>` : ""}
    ${kb ? `<div class="dato"><small>Tamaño</small><strong class="num">${fmtB(kb * 1024)}</strong></div>` : ""}`;
}

function interruptorRecordar() {
  if (!S.clavesCifrables) return "<span></span>";
  return `<div class="recordar">
    <label class="interruptor"><input type="checkbox" data-recordar ${S.recordar ? "checked" : ""}><span class="pista"></span>Guardar las claves en este equipo</label>
    <span class="nota">${ic("shield-check")}Cifradas con tu usuario de Windows y fuera de la carpeta del programa. Así actualizás la copia con un clic.</span>
  </div>`;
}

function vistaCuentas() {
  return `${cabecera("Paso 2 de 5", "Cuentas", "Las casillas que querés copiar, con su clave del servidor actual.")}
  <div class="barra-herramientas">
    <button class="boton secundario" data-accion="agregar-cuenta">${ic("plus")}Agregar cuenta</button>
    <button class="boton fantasma" data-accion="pegar-lista">${ic("clipboard-text")}Pegar lista</button>
    <button class="boton fantasma" data-accion="importar-csv">${ic("upload-simple")}Importar CSV</button>
    <input type="file" id="archivo-csv" accept=".csv,.txt" hidden>
    <span class="espacio"></span>
    <button class="boton primario" data-accion="probar-cuentas" id="boton-probar" ${ocupado() ? "disabled" : ""}>${ic("plugs-connected")}Probar cuentas</button>
  </div>
  <div class="tarjeta tabla-cuentas" id="tabla-cuentas" style="--columnas:${COLUMNAS_CUENTAS}">${tablaCuentas()}</div>
  <div class="pie-tabla">
    ${interruptorRecordar()}
    <div class="resumen" id="resumen-cuentas">${resumenCuentas()}</div>
  </div>
  ${pie(botonVolver("servidor", "Servidor actual"), botonIr("copia", "Continuar con la copia local"))}`;
}

function refrescarEstadosCuentas() {
  for (const c of S.cuentas) {
    const e = $(`#estado-${c.id}`);
    if (e) e.innerHTML = estadoCuenta(c);
    const k = $(`#carpetas-${c.id}`);
    if (k) k.innerHTML = chipsCarpetas(c);
    const d = $(`#destino-estado-${c.id}`);
    if (d) d.innerHTML = estadoDestino(c);
  }
  const r = $("#resumen-cuentas");
  if (r) r.innerHTML = resumenCuentas();
  $$("[data-accion=probar-cuentas], [data-accion=probar-destino]").forEach((b) => (b.disabled = ocupado()));
}

function agregarCuentas(lista) {
  let nuevas = 0;
  for (const d of lista) {
    const correo = (d.correo || "").trim();
    if (!correo.includes("@")) continue;
    const existente = S.cuentas.find((c) => c.correo.trim().toLowerCase() === correo.toLowerCase());
    if (existente) {
      if (d.clave_origen) existente.clave_origen = d.clave_origen;
      if (d.correo_destino) existente.correo_destino = d.correo_destino;
      if (d.clave_destino) existente.clave_destino = d.clave_destino;
      continue;
    }
    S.cuentas = S.cuentas.filter((c) => c.correo.trim());
    S.cuentas.push(nuevaCuenta({ correo, clave_origen: d.clave_origen || null, correo_destino: d.correo_destino || "",
      clave_destino: d.clave_destino || null, servidor: d.servidor || "", puerto: d.puerto || "", seguridad: d.seguridad || "" }));
    nuevas++;
  }
  guardarCuentasYa();
  render();
  if (nuevas) for (const c of S.cuentas.slice(-nuevas)) detectarServidorCuenta(c, nuevas === 1);
  aviso(nuevas ? `${plural(nuevas, "cuenta agregada", "cuentas agregadas")}.` : "No encontré correos nuevos en la lista.", nuevas ? "ok" : "info");
}

function interpretarLineas(texto) {
  const lineas = texto.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  if (!lineas.length) return [];
  const sep = /;/.test(lineas[0]) && !/,/.test(lineas[0]) ? ";" : /\t/.test(lineas[0]) ? "\t" : ",";
  let columnas = ["correo", "clave_origen", "correo_destino", "clave_destino"];
  const cab = lineas[0].toLowerCase().split(sep).map((x) => x.trim().replace(/^"|"$/g, ""));
  if (cab.some((x) => x.startsWith("correo") || x === "email")) {
    columnas = cab.map((x) => x === "email" || x === "correo" ? "correo"
      : x === "clave" || x === "password" || x === "clave_origen" ? "clave_origen"
      : x === "usuario_destino" ? "correo_destino" : x);
    lineas.shift();
  }
  return lineas.map((l) => {
    const partes = l.split(sep).map((x) => x.trim().replace(/^"|"$/g, ""));
    const d = {};
    columnas.forEach((k, i) => { d[k] = partes[i] || ""; });
    return d;
  });
}

// ------------------------------------------------------------ progreso compartido (copia y migración)
function muestrear(correo, p) {
  const etapa = p.fase === "subiendo" ? p.subida : p.fase === "descargando" ? p.descarga : null;
  if (!etapa) return;
  const lista = (S.muestras[correo] ||= []);
  const ahora = Date.now() / 1000;
  const ultimo = lista[lista.length - 1];
  if (ultimo && ultimo.fase !== p.fase) lista.length = 0;
  lista.push({ t: ahora, hechos: etapa.hechos, bytes: etapa.bytes, fase: p.fase });
  while (lista.length > 2 && ahora - lista[0].t > 25) lista.shift();
}

function metricas() {
  let porSeg = 0, bytesSeg = 0, restantes = 0, hechos = 0, total = 0, bytes = 0;
  for (const correo of S.trabajo.cuentas || []) {
    const p = S.progreso[correo];
    if (!p) continue;
    const d = p.descarga, s = p.subida;
    const tieneDesc = S.trabajo.accion !== "subir";
    const tieneSub = S.trabajo.accion !== "respaldar";
    const tDesc = d?.total || 0;
    const tSub = s ? s.total : (tieneSub ? tDesc : 0);
    total += (tieneDesc ? tDesc : 0) + tSub;
    hechos += (tieneDesc ? Math.min(d?.hechos || 0, tDesc) : 0) + Math.min(s?.hechos || 0, tSub);
    bytes += (d?.bytes || 0) + (s?.bytes || 0);
    const fin = ["listo", "error", "cancelado"].includes(p.fase);
    if (!fin) restantes += (tieneDesc ? Math.max(0, tDesc - (d?.hechos || 0)) : 0) + Math.max(0, tSub - (s?.hechos || 0));
    const m = S.muestras[correo];
    if (m && m.length > 1 && !fin) {
      const a = m[0], b = m[m.length - 1], dt = b.t - a.t;
      if (dt > 0.5) { porSeg += Math.max(0, b.hechos - a.hechos) / dt; bytesSeg += Math.max(0, b.bytes - a.bytes) / dt; }
    }
  }
  const pct = total ? Math.min(100, (hechos / total) * 100) : 0;
  return { porSeg, bytesSeg, restantes, hechos, total, bytes, pct, eta: porSeg > 0 ? restantes / porSeg : Infinity };
}

function anillo(pct, estado, icono) {
  const r = 46, c = 2 * Math.PI * r;
  return `<div class="anillo ${estado || ""}">
    <svg viewBox="0 0 112 112"><circle class="fondo-anillo" cx="56" cy="56" r="${r}"/>
      <circle class="valor-anillo" data-k="anillo" data-offset="${c * (1 - pct / 100)}" cx="56" cy="56" r="${r}" stroke-dasharray="${c}" style="stroke-dashoffset:${c * (1 - pct / 100)}"/></svg>
    <div class="centro" data-k="anillo-centro">${icono ? ic(icono) : `<strong class="num">${Math.floor(pct)}%</strong>`}</div>
  </div>`;
}

function nombreServidor(lado) {
  const s = S.config[lado];
  return `${esc((S.proveedores[s.proveedor] || {}).nombre || "Servidor")}${s.servidor ? ` (${esc(s.servidor)})` : ""}`;
}

function panelCorriendo() {
  const t = S.trabajo;
  const m = metricas();
  const pausado = t.estado === "pausado", cancelando = t.estado === "cancelando";
  const que = { respaldar: "Copiando", subir: "Subiendo", migrar: "Migrando" }[t.accion];
  const titulo = cancelando ? "Cancelando…" : pausado ? "En pausa" : `${que} ${plural(t.cuentas.length, "cuenta", "cuentas")}…`;
  const texto = cancelando ? "Termina la tanda en curso. Lo ya hecho queda guardado."
    : pausado ? "Termina la tanda en curso y espera. Podés reanudar cuando quieras."
    : { migrar: "Trayendo lo último del servidor actual y subiendo al servidor nuevo.", respaldar: "Guardando los correos en este equipo. Solo baja lo que todavía no tenés.", subir: "Subiendo la copia local al servidor nuevo." }[t.accion];
  return `<div data-forma="corriendo-${t.estado}-${t.accion}" style="display:contents">
    ${anillo(m.pct, "")}
    <div class="control-texto">
      <h2>${titulo}</h2><p>${texto}</p>
      <div class="metricas">
        <div class="metrica"><small>Velocidad</small><strong class="num" data-k="vel">${m.porSeg && !pausado ? `${fmtN(Math.round(m.porSeg * 60))} correos/min` : "—"}</strong></div>
        <div class="metrica"><small>Datos</small><strong class="num" data-k="datos">${fmtB(m.bytes)}${m.bytesSeg && !pausado ? ` · ${fmtB(m.bytesSeg)}/s` : ""}</strong></div>
        <div class="metrica"><small>Tiempo restante</small><strong class="num" data-k="eta">${pausado ? "En pausa" : fmtT(m.eta)}</strong></div>
        <div class="metrica"><small>Transcurrido</small><strong class="num" data-k="trans">${fmtT(Date.now() / 1000 - t.inicio)}</strong></div>
      </div>
    </div>
    <div class="control-botones">
      ${pausado ? `<button class="boton primario grande" data-accion="reanudar">${ic("play")}Reanudar</button>`
                : `<button class="boton secundario grande" data-accion="pausar" ${cancelando ? "disabled" : ""}>${ic("pause")}Pausar</button>`}
      <button class="boton peligro" data-accion="cancelar" ${cancelando ? "disabled" : ""}>${ic("stop")}Cancelar</button>
    </div></div>`;
}

const notaOcupado = () => ocupado() && !deEstaVista()
  ? `<p class="detalle-prueba" style="margin-top:8px">Hay otra tarea en marcha. Esperá a que termine.</p>` : "";

function resumenUltimo(acciones) {
  const t = S.trabajo;
  if (!acciones.includes(t.accion) || !["terminado", "cancelado"].includes(t.estado)) return null;
  const res = S.resultados[t.accion] || {};
  const errores = (t.cuentas || []).filter((c) => res[c] && !res[c].ok && res[c].error !== "Cancelado");
  let bajados = 0, subidos = 0;
  for (const c of t.cuentas || []) { const r = res[c]?.resultado; if (r) { bajados += r.descargados || 0; subidos += r.subidos || 0; } }
  return { cancelado: t.estado === "cancelado", errores, bajados, subidos, n: (t.cuentas || []).length };
}

function panelCopiaQuieto() {
  const sel = seleccionadas();
  let mensajes = 0, bytes = 0, con = 0;
  for (const c of sel) { const l = S.local[c.correo.trim()]; if (l?.fecha) { con++; mensajes += l.mensajes; bytes += l.bytes; } }
  const vieja = copiaMasVieja();
  const u = resumenUltimo(["respaldar"]);
  let anilloHtml, titulo, texto;
  if (u && !u.cancelado && u.errores.length) {
    anilloHtml = anillo(100, "error", "warning-circle");
    titulo = `La copia falló en ${plural(u.errores.length, "cuenta", "cuentas")}`;
    texto = "Mirá el detalle en cada tarjeta. Lo que se llegó a copiar quedó guardado.";
  } else if (u && !u.cancelado) {
    anilloHtml = anillo(100, "completo", "check-circle");
    titulo = "Copia local actualizada";
    texto = `${u.bajados ? `Se bajaron ${plural(u.bajados, "correo nuevo", "correos nuevos")}.` : "No había correos nuevos."} En total: ${fmtN(mensajes)} correos · ${fmtB(bytes)}.`;
  } else if (con) {
    const dias = diasDesde(vieja);
    anilloHtml = anillo(100, dias > 30 ? "error" : "completo", dias > 30 ? "warning-circle" : "database");
    titulo = `Última copia: ${hace(vieja)}`;
    texto = `${con === sel.length ? plural(con, "cuenta", "cuentas") : `${con} de ${sel.length} cuentas`} · ${fmtN(mensajes)} correos · ${fmtB(bytes)}.${dias > 30 ? " Conviene actualizarla." : ""}`;
  } else {
    anilloHtml = anillo(0, "", "database");
    titulo = sel.length ? "Todavía no hay copia local" : "Agregá cuentas para empezar";
    texto = `Se guarda en ${esc(S.config.general.carpeta_respaldo)}, con adjuntos y carpetas. Cada correo queda como un archivo .eml que abre Outlook o Thunderbird.`;
  }
  const deshabilitado = ocupado() || !sel.length ? "disabled" : "";
  return `<div data-forma="copia-${S.trabajo.estado}-${S.trabajo.accion}-${con}" style="display:contents">
    ${anilloHtml}
    <div class="control-texto"><h2>${titulo}</h2><p>${texto}</p>${notaOcupado()}</div>
    <div class="control-botones">
      <button class="boton primario grande" data-accion="respaldar" ${deshabilitado}>${ic(con ? "arrows-clockwise" : "cloud-arrow-down")}${con ? "Actualizar copia" : "Hacer copia local"}</button>
      <button class="boton secundario" data-accion="abrir" data-que="respaldo">${ic("folder-open")}Abrir carpeta</button>
    </div></div>`;
}

function panelMigrarQuieto() {
  const sel = seleccionadas();
  const desdeCopia = S.fuente === "copia";
  const sinCopia = sel.filter((c) => !S.local[c.correo.trim()]?.mensajes).length;
  const u = resumenUltimo(["subir", "migrar"]);
  let anilloHtml, titulo, texto;
  if (u?.cancelado) {
    anilloHtml = anillo(metricas().pct, ""); titulo = "Migración cancelada";
    texto = "Lo subido hasta ahora quedó en el servidor nuevo. Al volver a empezar, sigue desde donde quedó.";
  } else if (u?.errores.length) {
    anilloHtml = anillo(100, "error", "warning-circle"); titulo = `Terminó con errores en ${plural(u.errores.length, "cuenta", "cuentas")}`;
    texto = "Revisá el detalle en cada tarjeta y en el registro. Podés volver a intentarlo: no se duplica nada.";
  } else if (u) {
    anilloHtml = anillo(100, "completo", "check-circle"); titulo = "Migración completa";
    texto = `${u.n === 1 ? "La cuenta quedó" : `Las ${fmtN(u.n)} cuentas quedaron`} en el servidor nuevo. `
      + (u.bajados || u.subidos ? `En esta pasada: ${u.bajados ? `${plural(u.bajados, "correo traído", "correos traídos")} del servidor actual y ` : ""}${plural(u.subidos, "subido", "subidos")}.` : "No había nada nuevo.");
  } else {
    anilloHtml = anillo(0, "", "cloud-arrow-up");
    titulo = sel.length ? `Listo para migrar ${plural(sel.length, "cuenta", "cuentas")}` : "Agregá cuentas para empezar";
    texto = desdeCopia ? `Desde la copia local hacia ${nombreServidor("destino")}.` : `Desde ${nombreServidor("origen")} hacia ${nombreServidor("destino")}.`;
  }
  const falta = !S.config.destino.servidor ? "Configurá el servidor nuevo arriba." : desdeCopia && sinCopia === sel.length && sel.length ? "Todavía no hay copia local: hacela en el paso 3 o elegí «Desde el servidor actual»." : "";
  const deshabilitado = ocupado() || !sel.length || falta ? "disabled" : "";
  return `<div data-forma="migrar-${S.trabajo.estado}-${S.trabajo.accion}-${S.fuente}-${!!falta}" style="display:contents">
    ${anilloHtml}
    <div class="control-texto"><h2>${titulo}</h2><p>${texto}</p>
      ${sel.some((c) => filtroActivo(S.filtros[c.correo.trim().toLowerCase()])) ? `<p class="detalle-prueba" style="margin-top:8px">${ic("info")} «Liberar espacio» deja afuera algunos correos: quedan en la copia local.</p>` : ""}
      ${falta ? `<p class="detalle-prueba error" style="margin-top:8px">${falta}</p>` : desdeCopia && sinCopia ? `<p class="detalle-prueba" style="margin-top:8px">${plural(sinCopia, "cuenta no tiene", "cuentas no tienen")} copia local y no se van a subir.</p>` : ""}
      ${notaOcupado()}
    </div>
    <div class="control-botones">
      <button class="boton primario grande" data-accion="${desdeCopia ? "subir" : "migrar"}" ${deshabilitado}>${ic(u && !u.cancelado ? "arrows-clockwise" : "cloud-arrow-up")}${u && !u.cancelado ? "Migrar de nuevo" : "Migrar"}</button>
    </div></div>`;
}

function panelControl() {
  if (migrando() && deEstaVista()) return panelCorriendo();
  return S.paso === "copia" ? panelCopiaQuieto() : panelMigrarQuieto();
}

const FASES = {
  en_cola: ["En cola", ""], conectando: ["Conectando", "activa"], descargando: ["Copiando", "activa"],
  subiendo: ["Subiendo", "activa"], probando: ["Probando", "activa"], verificando: ["Verificando", "activa"],
  listo: ["Listo", "ok"], error: ["Error", "error"], cancelado: ["Cancelada", "aviso"],
};

function colorAvatar(texto) {
  let h = 0;
  for (const ch of texto) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return `hsl(${h} 52% 48%)`;
}
const avatar = (correo, chico = false) => `<span class="avatar ${chico ? "chico" : ""}" style="background:${colorAvatar(correo)}">${esc(correo[0] || "?")}</span>`;

function etapaHtml(clave, titulo, icono, datos, activa, terminada) {
  const total = datos?.total || 0, hechos = Math.min(datos?.hechos || 0, total);
  const pct = total ? (hechos / total) * 100 : (terminada ? 100 : 0);
  const pausada = activa && S.trabajo.estado === "pausado";
  const clase = terminada ? "lista" : pausada ? "pausada" : activa ? "en-curso" : "";
  const detalle = datos ? `${fmtN(hechos)} de ${fmtN(total)}${datos.bytes ? ` · ${fmtB(datos.bytes)}` : ""}` : (terminada ? "Sin cambios" : "En espera");
  return `<div class="etapa">
    <div class="etapa-cabeza"><span>${ic(icono)}${titulo}</span><span class="num" data-k="${clave}-txt">${detalle}</span></div>
    <div class="barra ${clase}" data-k="${clave}-barra"><i data-ancho="${pct}" style="width:${pct}%"></i></div>
  </div>`;
}

function lineaCopia(local) {
  return local?.fecha
    ? `${fmtN(local.mensajes)} correos · ${fmtB(local.bytes)} · ${plural(local.carpetas, "carpeta", "carpetas")}`
    : "Todavía sin copia";
}

function tarjetaCuenta(c) {
  const correo = c.correo.trim();
  const p = S.progreso[correo];
  const local = S.local[correo];
  const destino = c.correo_destino.trim() || correo;
  const acc = S.trabajo.accion;
  const enEste = deEstaVista(acc) && (S.trabajo.cuentas || []).includes(correo) && !!p;
  const excluida = S.excluidas.has(c.id) && !enEste;
  const fase = enEste ? p.fase : null;
  const pausado = S.trabajo.estado === "pausado" && FASES[fase]?.[1] === "activa";
  const [txtFase, claseFase] = pausado ? ["En pausa", "aviso"] : (FASES[fase] || ["", ""]);
  const trabajando = enEste && claseFase === "activa" && ocupado();
  const sub = S.paso === "migrar" ? `Hacia ${esc(destino)}` : local?.fecha ? `Última copia: ${hace(local.fecha)}` : "Sin copia local";
  let cuerpo;
  if (enEste) {
    const fin = ["listo", "error", "cancelado"].includes(fase);
    const descTerminada = fase === "subiendo" || (fin && fase === "listo") || (p.descarga?.total > 0 && p.descarga.hechos >= p.descarga.total);
    cuerpo = (acc !== "subir" ? etapaHtml("desc", acc === "respaldar" ? "Copia a este equipo" : "Lo nuevo del servidor actual", "cloud-arrow-down", p.descarga, fase === "descargando", descTerminada) : "")
           + (acc !== "respaldar" ? etapaHtml("sub", "Subida al servidor nuevo", "cloud-arrow-up", p.subida, fase === "subiendo", fin && fase === "listo") : "");
  } else {
    cuerpo = `<div class="etapa"><div class="etapa-cabeza"><span>${ic("database")}Copia local</span><span class="num" data-k="copia-txt">${lineaCopia(local)}</span></div></div>`;
  }
  const pieTxt = enEste && p.carpeta ? `${ic("folder-simple")}<span>${esc(p.carpeta)}</span>` : "";
  const error = enEste && p.error ? `<div class="tc-error">${esc(p.error)}</div>` : "";
  return `<article class="tarjeta tarjeta-cuenta ${trabajando ? "trabajando" : ""} ${error ? "con-error" : ""} ${excluida ? "excluida" : ""}" id="tc-${idSeguro(correo)}"
      data-forma="${enEste ? "t" : "q"}-${acc}-${!!error}-${excluida}">
    <div class="tc-cabeza">
      ${avatar(correo)}
      <div class="tc-nombre"><strong>${esc(correo)}</strong><small data-k="sub">${sub}</small></div>
      <span data-k="fase">${excluida ? '<span class="pastilla">No incluida</span>' : txtFase ? `<span class="pastilla ${claseFase}">${claseFase === "activa" ? '<span class="punto"></span>' : ""}${txtFase}</span>` : ""}</span>
    </div>
    ${cuerpo}
    <div class="tc-pie" data-k="pie">${pieTxt}</div>
    ${error}
  </article>`;
}

function rejillaCuentas() {
  const cuentas = conCorreo();
  return cuentas.length ? cuentas.map(tarjetaCuenta).join("")
    : `<div class="tarjeta vacio" style="grid-column:1/-1"><div class="vacio-icono">${ic("users-three")}</div><strong>No hay cuentas</strong><p>Agregalas en el paso 2.</p><button class="boton secundario" data-ir="cuentas">Ir a Cuentas</button></div>`;
}

function lineaLog(l) {
  return `<div class="${l.nivel}"><span class="hora">${esc(l.hora)}</span><span class="quien">${esc(l.cuenta === "-" ? "" : l.cuenta)}</span><span class="texto">${esc(l.texto)}</span></div>`;
}
const pasaFiltro = (l) => S.filtroLog === "todo" || l.nivel === "WARNING" || l.nivel === "ERROR";

function registroHtml() {
  const errores = S.log.filter((l) => l.nivel === "ERROR").length;
  return `<details class="tarjeta registro" id="registro" ${leer("registro", "0") === "1" ? "open" : ""}>
    <summary>${ic("list-checks")}Registro de actividad <span class="contador" id="contador-errores" ${errores ? "" : "hidden"}>${errores}</span><span class="caret">${ic("caret-down")}</span></summary>
    <div class="registro-barra">
      <div class="segmentado" role="group" aria-label="Filtrar registro">
        <button type="button" data-filtro-log="todo" aria-pressed="${S.filtroLog === "todo"}">Todo</button>
        <button type="button" data-filtro-log="problemas" aria-pressed="${S.filtroLog !== "todo"}">Avisos y errores</button>
      </div>
      <button class="boton fantasma chico" data-accion="abrir" data-que="registros">${ic("arrow-square-out")}Carpeta de registros</button>
    </div>
    <div class="lineas" id="lineas">${S.log.filter(pasaFiltro).map(lineaLog).join("") || '<div><span></span><span></span><span class="texto">Sin actividad todavía.</span></div>'}</div>
  </details>`;
}

// ------------------------------------------------------------ copia automática (paso 3)
const DIAS_SEMANA = [["lunes", "L", "lunes"], ["martes", "M", "martes"], ["miercoles", "X", "miércoles"], ["jueves", "J", "jueves"],
  ["viernes", "V", "viernes"], ["sabado", "S", "sábados"], ["domingo", "D", "domingos"]];
const NOMBRE_DIA = Object.fromEntries(DIAS_SEMANA.map(([d, , plural]) => [d, plural]));
const fmtDiaHora = (iso) => new Date(iso).toLocaleString("es-ES", { weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" });

function descripcionDias(dias) {
  if (dias.length === 7) return "todos los días";
  if (dias.length === 5 && !dias.includes("sabado") && !dias.includes("domingo")) return "de lunes a viernes";
  const nombres = DIAS_SEMANA.filter(([d]) => dias.includes(d)).map(([d]) => NOMBRE_DIA[d]);
  return "los " + (nombres.length > 1 ? `${nombres.slice(0, -1).join(", ")} y ${nombres.at(-1)}` : nombres[0]);
}

function tarjetaAutomatica() {
  const a = S.automatica;
  if (!a?.disponible) return "";
  const sinClaves = !S.recordar;
  const pastilla = a.activa
    ? (a.tarea_existe ? `<span class="pastilla ok">${ic("check-circle")}Activa</span>` : `<span class="pastilla aviso">${ic("warning")}Falta la tarea en Windows</span>`)
    : `<span class="pastilla">Desactivada</span>`;
  const u = a.ultima;
  const errores = u && !u.ok ? Object.entries(u.errores || {}) : [];
  let ultima = "";
  if (S.autoEnMarcha) ultima = `<span>${ic("circle-notch", "girando")}La copia automática está en marcha…</span>`;
  else if (u) ultima = `<span class="${u.ok ? "ok" : "error"}">${ic(u.ok ? "check-circle" : "warning-circle")}Última automática: ${fmtFecha(u.fecha)} · ${u.ok ? (u.nuevos ? plural(u.nuevos, "correo nuevo", "correos nuevos") : "sin correos nuevos") : `con errores en ${plural(errores.length, "cuenta", "cuentas")}`}</span>`
    + (errores.length ? `<span class="tenue">${esc(errores.map(([c, e]) => (c === "-" ? "" : `${c}: `) + e).join(" · "))}</span>` : "");
  return `<section class="tarjeta automatica" id="automatica">
    <div class="auto-cabeza">
      <span class="lado-icono">${ic("calendar-check")}</span>
      <div class="auto-titulo"><h2>Copia automática</h2><p class="sub">Actualiza la copia local sola, sin abrir la app, los días y a la hora que elijas.</p></div>
      ${pastilla}
    </div>
    <div class="auto-cuerpo">
      <div class="auto-config">
        <label class="interruptor"><input type="checkbox" data-auto-activa ${a.activa ? "checked" : ""} ${sinClaves && !a.activa ? "disabled" : ""}><span class="pista"></span>Hacer la copia automáticamente</label>
        ${sinClaves && !a.activa ? `<p class="detalle-prueba">${ic("key")} Necesita las claves guardadas: activá «Guardar las claves en este equipo» en <a href="#" data-ir="cuentas">Cuentas</a>.</p>` : ""}
        <div class="auto-cuando ${a.activa ? "" : "apagada"}">
          <div class="campo"><span>Días</span>
            <div class="dias" role="group" aria-label="Días de la copia">
              ${DIAS_SEMANA.map(([d, letra, nombre]) => `<button type="button" class="dia" data-dia="${d}" aria-pressed="${a.dias.includes(d)}" title="${nombre}" aria-label="${nombre}">${letra}</button>`).join("")}
            </div>
          </div>
          <label class="campo">Hora<input type="time" class="entrada hora num" data-auto-hora value="${esc(a.hora)}"></label>
        </div>
      </div>
      <div class="auto-info">
        ${a.activa ? `<span>${ic("calendar-check")}Programada ${descripcionDias(a.dias)} a las ${esc(a.hora)}${a.proxima ? `. Próxima: ${fmtDiaHora(a.proxima)}` : ""}.</span>` : ""}
        ${ultima}
        ${a.activa ? `<div><button class="boton secundario chico" data-accion="automatica-ahora" ${S.autoEnMarcha || ocupado() ? "disabled" : ""}>${ic("play")}Probar ahora</button></div>` : ""}
      </div>
    </div>
    <p class="nota-auto">${ic("info")}La computadora tiene que estar prendida y con tu sesión iniciada. Si a esa hora estaba apagada, la copia se hace apenas la prendas.</p>
  </section>`;
}

function refrescarAutomatica() {
  const el = $("#automatica");
  if (el) el.outerHTML = tarjetaAutomatica();
}

async function configurarAutomatica(cambios) {
  const a = { ...S.automatica, ...cambios };
  const r = await api("/api/automatica", { activa: a.activa, dias: a.dias, hora: a.hora });
  S.automatica = r.automatica;
  refrescarAutomatica();
  if (!r.ok) return aviso(esc(r.error), "error");
  if ("activa" in cambios) {
    aviso(a.activa ? `Copia automática programada ${descripcionDias(S.automatica.dias)} a las ${S.automatica.hora}.` : "Copia automática desactivada.", "ok");
  } else if (a.activa) mostrarGuardado();
}

let sondeoAuto = null;
function seguirAutomatica() {
  const antes = S.automatica?.ultima?.fecha;
  const inicio = Date.now();
  S.autoEnMarcha = true;
  refrescarAutomatica();
  clearInterval(sondeoAuto);
  sondeoAuto = setInterval(async () => {
    try {
      const d = await api("/api/estado");
      S.local = d.local;
      const nueva = d.automatica?.ultima?.fecha;
      if (nueva !== antes || Date.now() - inicio > 30 * 60e3) {
        clearInterval(sondeoAuto);
        S.autoEnMarcha = false;
        S.automatica = d.automatica;
        if (nueva !== antes) {
          const u = d.automatica.ultima;
          aviso(u.ok ? `Copia automática lista: ${u.nuevos ? plural(u.nuevos, "correo nuevo", "correos nuevos") : "sin correos nuevos"}.` : "La copia automática terminó con errores. Mirá el detalle en el paso 3.", u.ok ? "ok" : "error");
        }
        refrescarAutomatica();
        refrescarVivo(true);
      }
    } catch {}
  }, 4000);
}

// ------------------------------------------------------------ paso 3: copia local
function vistaCopia() {
  return `${cabecera("Paso 3 de 5", "Copia local", "Guarda en este equipo todos los correos, con adjuntos y carpetas. Actualizala cada tanto: solo baja lo nuevo y no toca nada en el servidor.")}
  ${seleccionadas().some((c) => !servidorDe(c)) ? `<div class="banner">${ic("warning")}<span>Hay cuentas sin servidor. Configurá el general en el <a href="#" data-ir="servidor">paso 1</a> o uno propio en <a href="#" data-ir="cuentas">Cuentas</a>.</span></div>` : ""}
  <div class="tarjeta panel-control" id="panel-control">${panelControl()}</div>
  <div class="rejilla-cuentas" id="rejilla-cuentas">${rejillaCuentas()}</div>
  ${tarjetaAutomatica()}
  ${registroHtml()}
  ${pie(botonVolver("cuentas", "Cuentas"), botonIr("migrar", "¿Pasar a otro servidor? Migrar", "secundario"))}`;
}

// ------------------------------------------------------------ liberar espacio (paso 4)
const MOTIVOS = { papelera: "Papelera o spam", boletin: "Boletín o publicidad", duplicado: "Duplicado", fecha: "Anterior a la fecha", manual: "Lo dejaste afuera" };
const filtroActivo = (f) => !!(f && (f.papelera || f.boletines || f.duplicados || f.desde || f.excluir?.length));

function tarjetaEspacio(c) {
  const correo = c.correo.trim();
  const d = S.espacio[correo];
  const abierta = S.espacioAbierto.has(correo);
  const filtro = d?.filtro || S.filtros[correo.toLowerCase()];
  const limiteMb = filtro?.limite_mb || d?.limite_sugerido_mb || null;
  let resumen = filtroActivo(filtro) ? "Con correos que no se suben" : "Se sube todo";
  let medidor = "";
  if (d) {
    resumen = `Se suben ${fmtB(d.subir)} de ${fmtB(d.total)}`;
    if (limiteMb) {
      const limite = limiteMb * 1048576, pct = Math.min(100, (d.subir / limite) * 100);
      const clase = d.subir > limite ? "error" : pct > 85 ? "aviso" : "bien";
      const libre = limite - d.subir;
      const meses = d.crecimiento_mb_mes > 0 ? Math.floor(libre / 1048576 / d.crecimiento_mb_mes) : null;
      medidor = `<div class="medidor ${clase}">
        <div class="barra"><i style="width:${pct}%"></i></div>
        <span>${d.subir > limite ? `No entra: sobran ${fmtB(-libre)}` : `Quedan libres ${fmtB(libre)}${meses !== null ? ` · alcanza para unos ${plural(meses, "mes", "meses")} (crece ${fmtN(Math.round(d.crecimiento_mb_mes))} MB por mes)` : ""}`}</span>
      </div>`;
    }
  }
  const cabeza = `<div class="espacio-cabeza">
      ${avatar(correo, true)}
      <div class="espacio-titulo"><strong>${esc(correo)}</strong><small>${resumen}${limiteMb ? ` · límite ${fmtB(limiteMb * 1048576)}` : ""}</small></div>
      <button class="boton ${abierta ? "fantasma" : "secundario"} chico" data-accion="espacio-abrir" data-correo="${esc(correo)}">${abierta ? "Cerrar" : "Configurar"}</button>
    </div>`;
  if (!abierta) return `<section class="tarjeta espacio-cuenta" data-espacio="${esc(correo)}">${cabeza}${medidor}</section>`;
  if (!d) return `<section class="tarjeta espacio-cuenta" data-espacio="${esc(correo)}">${cabeza}
      <p class="espacio-cargando">${ic("circle-notch", "girando")}Analizando la copia local… La primera vez puede tardar un par de minutos.</p></section>`;
  const f = d.filtro, pot = d.potencial || {};
  const cuanto = (x) => x ? `${plural(x.correos, "correo", "correos")} · ${fmtB(x.bytes)}` : "—";
  const regla = (clave, titulo, texto) => `<label class="regla">
      <span class="interruptor"><input type="checkbox" data-regla="${clave}" ${f[clave] ? "checked" : ""}><span class="pista"></span></span>
      <span><strong>${titulo}</strong><small>${texto}</small></span></label>`;
  const filas = d.pesados.map((x) => {
    const sube = !x.motivo;
    const estado = x.forzado ? `<span class="pastilla ok">Subís igual</span>` : sube ? `<span class="pastilla ok">Se sube</span>` : `<span class="pastilla aviso">${MOTIVOS[x.motivo]}</span>`;
    return `<tr class="${sube ? "" : "afuera"}">
      <td><input type="checkbox" class="casilla" data-pesado="${esc(x.clave)}" ${sube ? "checked" : ""} aria-label="Subir este correo"></td>
      <td class="n">${fmtB(x.bytes)}</td><td>${esc(x.fecha || "")}</td>
      <td><span class="recorte">${esc(x.de_nombre || x.de)}</span></td>
      <td><span class="recorte">${esc(x.asunto || "(sin asunto)")}</span>${x.adjuntos.length ? `<small class="recorte">${ic("folder-simple")}${esc(x.adjuntos.join(", "))}</small>` : ""}</td>
      <td>${estado}</td></tr>`;
  }).join("");
  return `<section class="tarjeta espacio-cuenta abierta" data-espacio="${esc(correo)}">${cabeza}${medidor}
    <div class="espacio-cuerpo">
      <div class="espacio-limite">
        <label class="campo">Límite del buzón en el servidor nuevo (MB)
          <input class="entrada num" type="number" min="50" step="50" data-espacio-limite value="${limiteMb || ""}" placeholder="Ej.: 1024">
        </label>
        <p class="nota">${d.correos_subir} de ${d.correos} correos se suben. Lo que no se sube queda en la copia local y sus adjuntos se guardan aparte.</p>
      </div>
      <div class="reglas">
        ${regla("papelera", "Papelera y spam", cuanto(pot.papelera))}
        ${regla("boletines", "Boletines y publicidad", `Correos con «darse de baja» · ${cuanto(pot.boletines)}`)}
        ${regla("duplicados", "Correos duplicados", cuanto(pot.duplicados))}
        <label class="regla">
          <span class="interruptor"><input type="checkbox" data-regla-desde ${f.desde ? "checked" : ""}><span class="pista"></span></span>
          <span><strong>Subir solo desde</strong>
            <input type="month" class="entrada mes" data-espacio-desde value="${esc((f.desde || "").slice(0, 7))}" ${f.desde ? "" : "disabled"}>
            <small>${f.desde ? `Lo anterior queda en la copia · ${cuanto(pot.desde)}` : `El correo más viejo es de ${esc(d.primera_fecha || "—")}`}</small></span>
        </label>
      </div>
      <h3 class="espacio-sub">Los correos más pesados</h3>
      <p class="nota">Destildá los que no quieras subir. Si una regla deja afuera algo importante, tildalo para subirlo igual.</p>
      <div class="tabla-desliza-sola"><table class="tabla-resumen pesados">
        <thead><tr><th>Subir</th><th class="n">Tamaño</th><th>Fecha</th><th>De</th><th>Asunto y adjuntos</th><th>Estado</th></tr></thead>
        <tbody>${filas}</tbody></table></div>
      <div class="espacio-pie">
        <button class="boton secundario chico" data-accion="espacio-adjuntos" data-correo="${esc(correo)}" ${ocupado() ? "disabled" : ""}>${ic("folder-open")}Guardar adjuntos de lo que no se sube</button>
        <button class="boton fantasma chico" data-accion="espacio-adjuntos-todos" data-correo="${esc(correo)}" ${ocupado() ? "disabled" : ""}>Guardar todos los adjuntos</button>
        <button class="boton fantasma chico" data-accion="abrir" data-que="adjuntos">${ic("arrow-square-out")}Abrir carpeta de adjuntos</button>
      </div>
    </div></section>`;
}

function refrescarEspacio(correo) {
  const c = conCorreo().find((x) => x.correo.trim() === correo);
  const el = $(`[data-espacio="${CSS.escape(correo)}"]`);
  if (c && el) el.outerHTML = tarjetaEspacio(c);
}

async function cargarEspacio(correo, filtro) {
  const r = await api("/api/espacio", filtro ? { correo, filtro } : { correo });
  if (!r.ok) { S.espacioAbierto.delete(correo); refrescarEspacio(correo); return aviso(esc(r.error), "error"); }
  S.espacio[correo] = r;
  S.filtros[correo.toLowerCase()] = r.filtro;
  refrescarEspacio(correo);
  refrescarTrabajo();
}

const cambiarFiltro = (correo, cambios) => cargarEspacio(correo, { ...S.espacio[correo].filtro, ...cambios })
  .catch((e) => aviso(esc(e.message), "error"));
const cambiarLimite = demorar((correo, valor) => cambiarFiltro(correo, { limite_mb: valor ? Number(valor) : null }), 600);

// ------------------------------------------------------------ paso 4: migrar (opcional)
const COLUMNAS_DESTINO = "minmax(190px, 1.2fr) minmax(190px, 1.2fr) minmax(150px, 1fr) minmax(170px, 1.2fr)";

function estadoDestino(c) {
  const correo = c.correo.trim();
  const p = S.progreso[correo];
  if (enCurso("probar_destino") && S.trabajo.cuentas.includes(correo) && p?.fase !== "listo") {
    return `<span class="linea-estado">${ic("circle-notch", "girando")}<span>Probando…</span></span>`;
  }
  const d = pruebaDestino(correo);
  if (!d) return `<span class="linea-estado tenue">Sin probar</span>`;
  if (!d.ok) return `<span class="linea-estado error" title="${esc(d.error)}">${ic("warning-circle")}<span>${esc(d.error)}</span></span>`;
  const local = S.local[correo];
  const libre = d.limite_kb ? (d.limite_kb - (d.usado_kb || 0)) * 1024 : null;
  let txt = `<span class="linea-estado ok">${ic("check-circle")}<span>Lista${libre != null ? ` · ${fmtB(libre)} libres` : ""}</span></span>`;
  if (libre != null && local?.bytes > libre) txt += `<span class="linea-estado aviso">${ic("warning")}<span>La copia no entra en el espacio libre</span></span>`;
  return txt;
}

function tablaDestino() {
  const cuentas = seleccionadas();
  if (!cuentas.length) return `<div class="vacio" style="padding:26px"><p>No hay cuentas seleccionadas. Agregalas en el paso 2.</p></div>`;
  return `<div class="cuentas-cabeza"><span>Cuenta</span><span>Correo en el servidor nuevo</span><span>Clave en el servidor nuevo</span><span>Estado</span></div>
    ${cuentas.map((c) => `<div class="cuenta" data-id="${c.id}"><div class="cuenta-fila">
      <span class="cuenta-nombre">${avatar(c.correo.trim(), true)}<span>${esc(c.correo.trim())}</span></span>
      <input class="entrada" data-c="correo_destino" value="${esc(c.correo_destino)}" placeholder="El mismo" spellcheck="false" autocomplete="off" aria-label="Correo en el servidor nuevo">
      <div class="clave"><input class="entrada" type="password" data-c="clave_destino" value="${esc(c.clave_destino ?? "")}" placeholder="${c.tiene_clave_destino ? "•••••• guardada" : "La misma"}" autocomplete="new-password" aria-label="Clave en el servidor nuevo">${ojo}</div>
      <div class="estado-cuenta" id="destino-estado-${c.id}">${estadoDestino(c)}</div>
    </div></div>`).join("")}`;
}

function vistaMigrar() {
  const copia = copiaMasVieja();
  const opcion = (valor, icono, titulo, texto, extra) => `<button type="button" class="opcion ${S.fuente === valor ? "elegida" : ""}" data-fuente="${valor}" aria-pressed="${S.fuente === valor}">
      <span class="opcion-icono">${ic(icono)}</span>
      <span class="opcion-texto"><strong>${titulo}</strong><span>${texto}</span>${extra ? `<small>${extra}</small>` : ""}</span>
      <span class="opcion-marca">${ic("check")}</span>
    </button>`;
  return `${cabecera("Paso 4 de 5 · opcional", "Migrar a otro servidor", "Pasá los correos a otro hosting. Podés subirlos desde la copia local o traerlos directo del servidor actual.")}
  <div class="migrar-rejilla">
    ${tarjetaServidor("destino")}
    <section class="tarjeta fuente">
      <h2>¿Desde dónde?</h2>
      <p class="sub">De dónde salen los correos que se suben al servidor nuevo.</p>
      ${opcion("copia", "database", "Desde la copia local", "Sube lo que guardaste en este equipo. No necesita el servidor actual: sirve aunque ya no exista.", copia ? `Copia más vieja: ${hace(copia)}` : "Todavía no hay copia local")}
      ${opcion("servidor", "hard-drives", "Desde el servidor actual", "Primero trae lo último del servidor actual y después sube todo. Ideal después de cambiar el DNS, para no perder lo que llegó durante la propagación.", S.config.origen.servidor ? esc(S.config.origen.servidor) : "")}
    </section>
  </div>
  <div class="barra-herramientas" style="margin-top:22px">
    <h2 class="titulo-seccion">Cuentas en el servidor nuevo</h2>
    <span class="espacio"></span>
    <button class="boton secundario" data-accion="probar-destino" ${ocupado() ? "disabled" : ""}>${ic("plugs-connected")}Probar cuentas</button>
  </div>
  <p class="sub-seccion">Creá antes las casillas en el servidor nuevo. Si el correo o la clave son los mismos, dejalos vacíos.</p>
  <div class="tarjeta tabla-cuentas" id="tabla-destino" style="--columnas:${COLUMNAS_DESTINO}">${tablaDestino()}</div>
  <h2 class="titulo-seccion" style="margin-top:26px">Liberar espacio</h2>
  <p class="sub-seccion" style="margin-top:6px">Si una casilla no entra en el servidor nuevo, elegí qué no se sube. Nada se borra: todo sigue en la copia local, y los adjuntos de lo que no se sube se guardan aparte como archivos.</p>
  <div class="espacio-lista" id="espacio">${seleccionadas().map(tarjetaEspacio).join("") || '<p class="nota">No hay cuentas seleccionadas.</p>'}</div>
  <div class="tarjeta panel-control" id="panel-control" style="margin-top:22px">${panelControl()}</div>
  <div class="rejilla-cuentas" id="rejilla-cuentas">${rejillaCuentas()}</div>
  ${registroHtml()}
  ${pie(botonVolver("copia", "Copia local"), botonIr("verificar", "Continuar con la verificación"))}`;
}

// ------------------------------------------------------------ paso 5: verificar
function resultadosVerificacion() {
  const cuentas = conCorreo();
  const res = S.resultados.verificar || {};
  if (enCurso("verificar")) {
    return cuentas.filter((c) => S.trabajo.cuentas.includes(c.correo.trim())).map((c) => {
      const p = S.progreso[c.correo.trim()];
      const listo = p?.fase === "listo" || p?.fase === "error";
      return `<div class="verif-cuenta"><div class="verif-fila">
        ${avatar(c.correo, true)}<strong>${esc(c.correo)}</strong>
        ${listo ? `<span class="pastilla ok">${ic("check")}Contado</span>` : `<span class="pastilla activa"><span class="punto"></span>Contando…</span>`}
      </div></div>`;
    }).join("");
  }
  const conRes = cuentas.filter((c) => res[c.correo.trim()]);
  if (!conRes.length) {
    const u = S.app.ultima_verificacion;
    return `<div class="vacio" style="padding:30px 10px">
      <div class="vacio-icono">${ic("list-checks")}</div>
      <strong>${u ? `Última verificación: ${fmtFecha(u.fecha)}` : "Todavía no verificaste"}</strong>
      <p>${u ? (u.ok ? "Todo coincidía." : "Había diferencias.") + " Verificá de nuevo para ver el detalle." : "Hacelo después de migrar: compara carpeta por carpeta."}</p>
    </div>`;
  }
  return conRes.map((c) => {
    const r = res[c.correo.trim()];
    let pastilla, tabla = "";
    if (!r.ok) {
      pastilla = `<span class="pastilla error">${ic("warning-circle")}No se pudo verificar</span>`;
      tabla = `<div class="tc-error" style="margin:0 14px 14px">${esc(r.error)}</div>`;
    } else {
      const faltan = r.resultado.filas.filter((f) => !f.ok).length;
      pastilla = faltan ? `<span class="pastilla aviso">${ic("warning")}${plural(faltan, "carpeta con diferencias", "carpetas con diferencias")}</span>`
                        : `<span class="pastilla ok">${ic("check-circle")}Todo coincide</span>`;
      tabla = (r.resultado.error_origen ? `<p class="nota-verif">${ic("info")}Se comparó la copia local con el servidor nuevo, sin el servidor actual (${esc(r.resultado.error_origen)}).</p>` : "")
        + `<table class="conteos"><thead><tr><th>Carpeta</th><th class="n">Servidor actual</th><th class="n">Copia local</th><th class="n">Servidor nuevo</th><th></th></tr></thead><tbody>
        ${r.resultado.filas.map((f) => `<tr>
          <td>${esc(f.carpeta)}${f.destino_nombre !== f.carpeta ? `<span class="destino-nombre">→ ${esc(f.destino_nombre)}</span>` : ""}</td>
          <td class="n">${f.origen == null ? "—" : fmtN(f.origen)}</td><td class="n">${fmtN(f.local)}</td><td class="n">${fmtN(f.destino)}</td>
          <td class="icono-estado ${f.ok ? "ok" : "falta"}" title="${f.ok ? "Coincide" : `Se esperaban ${fmtN(f.esperados)} en el servidor nuevo`}">${ic(f.ok ? "check-circle" : "warning-circle")}</td>
        </tr>`).join("")}</tbody></table>`;
    }
    const abierto = !r.ok || r.resultado.filas.some((f) => !f.ok);
    return `<details class="verif-cuenta" ${abierto ? "open" : ""}>
      <summary>${avatar(c.correo, true)}<strong>${esc(c.correo)}</strong>${pastilla}</summary>${tabla}</details>`;
  }).join("");
}

function pasosCambio() {
  const ck = S.app.checklist || {};
  const copia = S.app.ultima_copia, mig = S.app.ultima_migracion, ver = S.app.ultima_verificacion;
  const mx = ck.mx;
  const subida = !!(mx && mig && mig >= mx);
  const items = [
    { id: "copia", auto: true, hecho: !!copia, fecha: copia, titulo: "Copia local completa", texto: "Todos los correos del servidor actual, guardados en este equipo." },
    { id: "mx", hecho: !!mx, fecha: mx, titulo: "Cambiar los registros MX (o los DNS) del dominio", texto: "Desde ese momento los correos nuevos empiezan a llegar al servidor nuevo." },
    { id: "subida", auto: true, hecho: subida, fecha: subida && mig, titulo: "Migrar después del cambio", texto: "«Desde el servidor actual», para traer también lo que llegó durante la propagación.",
      recordatorio: mx && !subida ? `Recomendado a partir del ${fmtDia(new Date(Date.parse(mx) + 864e5))}` : "" },
    { id: "final", auto: true, hecho: subida && !!ver?.ok && ver.fecha >= mig, fecha: subida && ver?.ok && ver.fecha >= mig && ver.fecha, titulo: "Verificación final", texto: "Un conteo para confirmar que no falta nada." },
    { id: "baja", hecho: !!ck.baja, fecha: ck.baja, titulo: "Dar de baja el servidor anterior", texto: "Recién ahora. Guardá la copia local como respaldo histórico." },
  ];
  const sig = items.find((i) => !i.hecho)?.id;
  return items.map((i) => `<li class="item-paso ${i.hecho ? "hecho" : ""} ${i.id === sig ? "siguiente" : ""}">
    <button class="marca-paso" ${i.auto ? "disabled title=\"Se marca solo\"" : `data-accion="marcar" data-item="${i.id}" data-hecho="${i.hecho ? 1 : 0}" title="Marcar"`} aria-label="${i.titulo}">${ic("check")}</button>
    <div><strong>${i.titulo}</strong><p>${i.texto}</p>
      ${i.fecha ? `<span class="fecha">${fmtFecha(i.fecha)}</span>` : i.recordatorio ? `<span class="fecha recordatorio">${i.recordatorio}</span>` : ""}
      ${i.id === "subida" && mx && !subida ? `<div style="margin-top:8px"><button class="boton secundario chico" data-ir="migrar">${ic("arrows-clockwise")}Ir a migrar</button></div>` : ""}
    </div></li>`).join("");
}

function vistaVerificar() {
  return `${cabecera("Paso 5 de 5", "Verificar y cambiar de servidor", "Compará cuántos correos hay en cada lugar y seguí los pasos para cambiar al servidor nuevo sin perder nada.")}
  <div class="dos-columnas">
    <section class="tarjeta">
      <div class="servidor-cabeza" style="align-items:flex-start">
        <div><h2>Conteo por carpeta</h2><p class="sub">Servidor actual, copia local y servidor nuevo deberían coincidir.</p></div>
        <button class="boton primario" data-accion="verificar" ${ocupado() ? "disabled" : ""}>${ic("arrows-clockwise")}Verificar ahora</button>
      </div>
      <div id="verificacion">${resultadosVerificacion()}</div>
    </section>
    <section class="tarjeta">
      <h2>Cambio al servidor nuevo</h2><p class="sub">Seguí este orden para no perder correos.</p>
      <ol class="lista-pasos" id="lista-pasos">${pasosCambio()}</ol>
    </section>
  </div>
  ${pie(botonVolver("migrar", "Migrar"), `<button class="boton secundario" data-accion="abrir" data-que="respaldo">${ic("folder-open")}Abrir copia local</button>`)}`;
}

const VISTAS = { inicio: vistaInicio, servidor: vistaServidor, cuentas: vistaCuentas, copia: vistaCopia, migrar: vistaMigrar, verificar: vistaVerificar };

// ------------------------------------------------------------ refresco en vivo
function parchear(viejo, html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  const nuevo = t.content.firstElementChild;
  if (!viejo || !nuevo) return;
  if (viejo.dataset.forma !== nuevo.dataset.forma || viejo.querySelectorAll("[data-k]").length !== nuevo.querySelectorAll("[data-k]").length) {
    viejo.replaceWith(nuevo);
    return;
  }
  viejo.className = nuevo.className;
  for (const n of nuevo.querySelectorAll("[data-k]")) {
    const v = viejo.querySelector(`[data-k="${n.dataset.k}"]`);
    if (!v) continue;
    v.setAttribute("class", n.getAttribute("class") || "");
    const barra = n.querySelector("[data-ancho]");
    if (barra) { v.querySelector("[data-ancho]").style.width = barra.style.width; continue; }
    if (n.dataset.offset) { v.style.strokeDashoffset = n.dataset.offset; continue; }
    if (v.innerHTML !== n.innerHTML) v.innerHTML = n.innerHTML;
  }
}

function refrescarTrabajo() {
  const panel = $("#panel-control");
  if (panel) {
    const html = panelControl();
    const t = document.createElement("template");
    t.innerHTML = html.trim();
    if (panel.firstElementChild?.dataset.forma === t.content.firstElementChild.dataset.forma) parchear(panel.firstElementChild, html);
    else panel.innerHTML = html;
  }
  for (const c of conCorreo()) {
    const el = $(`#tc-${idSeguro(c.correo.trim())}`);
    if (el) parchear(el, tarjetaCuenta(c));
  }
}

let marcoPendiente = false;
function refrescarVivo(completo = false) {
  if (marcoPendiente && !completo) return;
  marcoPendiente = true;
  setTimeout(() => {  // no requestAnimationFrame: se congela con la ventana minimizada
    marcoPendiente = false;
    actualizarPasos();
    if (S.paso === "inicio" && completo) render();
    if (S.paso === "copia" || S.paso === "migrar") refrescarTrabajo();
    if (S.paso === "cuentas" || S.paso === "migrar") refrescarEstadosCuentas();
    if (S.paso === "verificar") {
      const v = $("#verificacion");
      if (v) v.innerHTML = resultadosVerificacion();
      if (completo) {
        const l = $("#lista-pasos");
        if (l) l.innerHTML = pasosCambio();
        const b = $("[data-accion=verificar]");
        if (b) b.disabled = ocupado();
      }
    }
  }, 40);
}

setInterval(() => { if (migrando() && deEstaVista()) refrescarTrabajo(); }, 1000);
setInterval(async () => {
  if (S.paso !== "copia" || S.autoEnMarcha || ocupado() || document.hidden) return;
  try {
    const d = await api("/api/estado");
    if (d.automatica?.ultima?.fecha !== S.automatica?.ultima?.fecha) {
      S.automatica = d.automatica; S.local = d.local;
      refrescarAutomatica(); refrescarTrabajo(); actualizarPasos();
    }
  } catch {}
}, 60000);

// ------------------------------------------------------------ acciones
async function iniciar(accion, correos = null) {
  await guardandoCuentas;
  await guardarCuentasYa();
  await api("/api/config", S.config);
  correos ||= seleccionadas().map((c) => c.correo.trim());
  if (!correos.length) { aviso("Seleccioná al menos una cuenta.", "error"); return false; }
  S.muestras = {};
  const r = await api("/api/accion", { accion, correos });
  if (!r.ok) aviso(esc(r.error), "error");
  return r.ok;
}

const ACCIONES = {
  "probar-servidor": (b) => probarServidor(b.dataset.lado),
  abrir: (b) => api("/api/abrir", { que: b.dataset.que }),
  "agregar-cuenta": () => {
    S.cuentas.push(nuevaCuenta());
    if (S.paso !== "cuentas") return irA("cuentas");
    $("#tabla-cuentas").innerHTML = tablaCuentas();
    $$(".cuenta").at(-1)?.querySelector("[data-c=correo]")?.focus();
    actualizarPasos();
  },
  "quitar-cuenta": (b) => {
    const id = Number(b.closest(".cuenta").dataset.id);
    S.cuentas = S.cuentas.filter((c) => c.id !== id);
    S.excluidas.delete(id);
    guardarCuentasYa();
    $("#tabla-cuentas").innerHTML = tablaCuentas();
    refrescarEstadosCuentas();
    actualizarPasos();
  },
  "ver-clave": (b) => {
    const i = b.parentElement.querySelector("input");
    i.type = i.type === "password" ? "text" : "password";
    b.innerHTML = ic(i.type === "password" ? "eye" : "eye-slash");
  },
  "ver-carpetas": (b) => b.closest(".cuenta").classList.toggle("abierta"),
  "servidor-cuenta": async (b) => {
    const c = S.cuentas.find((x) => x.id === Number(b.closest(".cuenta").dataset.id));
    const seg = c.seguridad || "ssl";
    const opcion = (v, t) => `<option value="${v}" ${seg === v ? "selected" : ""}>${t}</option>`;
    const f = await abrirModal({
      titulo: "Servidor de esta cuenta",
      texto: `De dónde se copia <b>${esc(c.correo.trim() || "esta cuenta")}</b>. Si lo dejás vacío, usa el servidor general del paso 1${S.config.origen.servidor ? ` (${esc(S.config.origen.servidor)})` : ""}.`,
      cuerpo: `<div class="fila">
          <label class="campo crece">Servidor IMAP
            <input class="entrada" name="servidor" value="${esc(c.servidor || "")}" placeholder="Vacío = el servidor general" spellcheck="false" autocomplete="off">
          </label>
          <label class="campo corto">Puerto
            <input class="entrada num" type="number" min="1" max="65535" name="puerto" value="${esc(String(c.puerto || 993))}">
          </label>
        </div>
        <label class="campo">Seguridad
          <select class="entrada" name="seguridad">${opcion("ssl", "SSL/TLS")}${opcion("starttls", "STARTTLS")}${opcion("ninguna", "Sin cifrar")}</select>
        </label>
        <label class="interruptor"><input type="checkbox" name="verificar" ${c.verificar === false ? "" : "checked"}><span class="pista"></span>Verificar el certificado del servidor</label>
        <div class="acciones-modal">
          <button type="button" class="boton secundario chico" data-accion="detectar-en-modal" data-correo="${esc(c.correo.trim())}">${ic("magnifying-glass")}Averiguar por el dominio</button>
          <span class="nota-modal" id="nota-deteccion"></span>
        </div>
        <p class="ayuda">${ic("info")}<span>Si el dominio todavía se va a mudar, conviene el nombre real del servidor (por ejemplo server123.tuhosting.com) y no mail.tudominio.com, que cambia con el DNS.</span></p>`,
      aceptar: "Guardar",
    });
    if (!f) return;
    const servidor = (f.get("servidor") || "").trim();
    Object.assign(c, servidor
      ? { servidor, puerto: Number(f.get("puerto")) || 993, seguridad: f.get("seguridad") || "ssl", verificar: f.get("verificar") === "on" }
      : { servidor: "", puerto: "", seguridad: "", verificar: "" });
    refrescarServidorCuenta(c);
    await guardarCuentasYa();
    aviso(servidor ? `Servidor guardado para ${esc(c.correo.trim())}.` : `${esc(c.correo.trim())} usa el servidor general.`, "ok");
  },
  "detectar-en-modal": async (b) => {
    const nota = $("#nota-deteccion"), form = b.closest("form");
    nota.textContent = "Averiguando…";
    try {
      const r = await api("/api/detectar-servidor", { correo: b.dataset.correo });
      if (!r.ok) { nota.textContent = r.aviso || "No pude averiguarlo."; return; }
      form.servidor.value = r.servidor;
      form.puerto.value = r.puerto;
      form.seguridad.value = r.seguridad;
      form.verificar.checked = r.verificar !== false;
      nota.textContent = r.como || "Listo.";
    } catch (e) { nota.textContent = e.message; }
  },
  "pegar-lista": async () => {
    const f = await abrirModal({
      titulo: "Pegar lista de cuentas",
      texto: "Un correo por línea. Opcional, separado por comas: la clave.",
      cuerpo: `<textarea class="entrada" name="lista" placeholder="info@tudominio.com&#10;ventas@tudominio.com, clave123"></textarea>`,
      aceptar: "Agregar",
    });
    if (f) agregarCuentas(interpretarLineas(f.get("lista") || ""));
  },
  "importar-csv": () => $("#archivo-csv").click(),
  "probar-cuentas": () => iniciar("probar_origen"),
  "probar-destino": () => iniciar("probar_destino"),
  respaldar: () => iniciar("respaldar"),
  migrar: () => iniciar("migrar"),
  subir: () => iniciar("subir"),
  verificar: () => iniciar("verificar"),
  "actualizar-todo": async () => {
    // desde el inicio: todas las cuentas con clave; las que no tienen se avisan y se saltean
    const conClave = conCorreo().filter((c) => c.tiene_clave_origen || c.clave_origen);
    const sinClave = conCorreo().filter((c) => !(c.tiene_clave_origen || c.clave_origen));
    if (!conClave.length) return aviso("Ninguna cuenta tiene la clave cargada. Escribila en el paso Cuentas.", "error");
    if (sinClave.length) aviso(`Se saltea ${sinClave.map((c) => esc(c.correo.trim())).join(", ")}: falta la clave.`, "info");
    if (await iniciar("respaldar", conClave.map((c) => c.correo.trim()))) irA("copia");
  },
  "espacio-abrir": (b) => {
    const correo = b.dataset.correo;
    if (S.espacioAbierto.has(correo)) S.espacioAbierto.delete(correo);
    else { S.espacioAbierto.add(correo); if (!S.espacio[correo]) cargarEspacio(correo).catch((e) => aviso(esc(e.message), "error")); }
    refrescarEspacio(correo);
  },
  "espacio-adjuntos": (b) => iniciar("adjuntos", [b.dataset.correo]),
  "espacio-adjuntos-todos": (b) => iniciar("adjuntos_todos", [b.dataset.correo]),
  "automatica-ahora": async () => {
    const r = await api("/api/automatica-ahora", {});
    if (!r.ok) return aviso(esc(r.error), "error");
    aviso("La copia automática arrancó en segundo plano. El resultado aparece acá cuando termine.", "info");
    seguirAutomatica();
  },
  pausar: () => api("/api/pausar", {}),
  reanudar: () => api("/api/reanudar", {}),
  cancelar: async () => {
    const ok = await abrirModal({
      titulo: "¿Cancelar la tarea?",
      texto: "Lo hecho hasta ahora queda guardado. Cuando vuelvas a empezar, sigue desde donde quedó.",
      aceptar: "Sí, cancelar", cancelar: "Seguir", peligro: true,
    });
    if (ok) api("/api/cancelar", {});
  },
  marcar: async (b) => {
    const r = await api("/api/checklist", { item: b.dataset.item, hecho: b.dataset.hecho !== "1" });
    if (r.ok) { S.app = r.app; $("#lista-pasos").innerHTML = pasosCambio(); actualizarPasos(); }
  },
};

document.addEventListener("click", (e) => {
  const ir = e.target.closest("[data-ir]");
  if (ir) { e.preventDefault(); return irA(ir.dataset.ir); }
  const seg = e.target.closest("[data-seguridad]");
  if (seg) {
    const lado = seg.closest("[data-lado]").dataset.lado;
    S.config[lado].seguridad = seg.dataset.seguridad;
    if (seg.dataset.seguridad === "ssl" && S.config[lado].puerto === 143) S.config[lado].puerto = 993;
    if (seg.dataset.seguridad !== "ssl" && S.config[lado].puerto === 993) S.config[lado].puerto = 143;
    S.pruebas[lado] = null;
    $(`#servidor-${lado}`).outerHTML = tarjetaServidor(lado);
    guardarConfig();
    return;
  }
  const dia = e.target.closest("[data-dia]");
  if (dia) {
    const dias = new Set(S.automatica.dias);
    dias.has(dia.dataset.dia) ? dias.delete(dia.dataset.dia) : dias.add(dia.dataset.dia);
    if (!dias.size) return aviso("Elegí al menos un día.", "info");
    configurarAutomatica({ dias: [...dias] }).catch((err) => aviso(esc(err.message), "error"));
    return;
  }
  const fuente = e.target.closest("[data-fuente]");
  if (fuente) {
    S.fuente = fuente.dataset.fuente;
    escribir("fuente", S.fuente);
    $$("[data-fuente]").forEach((b) => { const si = b === fuente; b.classList.toggle("elegida", si); b.setAttribute("aria-pressed", si); });
    refrescarTrabajo();
    return;
  }
  const filtro = e.target.closest("[data-filtro-log]");
  if (filtro) {
    S.filtroLog = filtro.dataset.filtroLog;
    $$("[data-filtro-log]").forEach((b) => b.setAttribute("aria-pressed", b === filtro));
    const l = $("#lineas");
    l.innerHTML = S.log.filter(pasaFiltro).map(lineaLog).join("");
    l.scrollTop = l.scrollHeight;
    return;
  }
  const b = e.target.closest("[data-accion]");
  if (b && !b.disabled) {
    Promise.resolve(ACCIONES[b.dataset.accion]?.(b, e)).catch((err) => aviso(esc(err.message), "error"));
  }
});

document.addEventListener("input", (e) => {
  const t = e.target;
  if (t.dataset.servidor && t.dataset.servidor !== "proveedor" && t.type !== "checkbox") {
    const lado = t.closest("[data-lado]").dataset.lado;
    S.config[lado][t.dataset.servidor] = t.dataset.servidor === "puerto" ? Number(t.value) || 993 : t.value;
    S.pruebas[lado] = null;
    refrescarPrueba(lado);
    guardarConfig();
  } else if (t.dataset.general) {
    const k = t.dataset.general;
    S.config.general[k] = k === "excluir_carpetas" ? t.value.split(",").map((x) => x.trim()).filter(Boolean)
      : ["cuentas_a_la_vez", "lote_mb"].includes(k) ? Number(t.value) : t.value;
    if (k === "cuentas_a_la_vez") $("#salida-hilos").textContent = t.value;
    guardarConfig();
  } else if (t.hasAttribute("data-espacio-limite")) {
    cambiarLimite(t.closest("[data-espacio]").dataset.espacio, t.value);
  } else if (t.dataset.c) {
    const c = S.cuentas.find((x) => x.id === Number(t.closest(".cuenta").dataset.id));
    c[t.dataset.c] = t.value;
    if (t.dataset.c === "correo") {
      const e2 = $(`#estado-${c.id}`);
      if (e2) e2.innerHTML = estadoCuenta(c);
      actualizarPasos();
    }
    guardarCuentas();
  }
});

document.addEventListener("change", (e) => {
  const t = e.target;
  if (t.dataset.c === "correo") {  // correo recién escrito: se averigua su servidor
    const c = S.cuentas.find((x) => x.id === Number(t.closest(".cuenta")?.dataset.id));
    if (c) detectarServidorCuenta(c);
  }
  if (t.dataset.servidor === "proveedor") {
    const lado = t.closest("[data-lado]").dataset.lado;
    const s = S.config[lado], p = S.proveedores[t.value];
    const eraDeLista = Object.values(S.proveedores).some((x) => x.servidor && x.servidor === s.servidor);
    Object.assign(s, { proveedor: t.value, puerto: p.puerto, seguridad: p.seguridad });
    if (p.servidor) s.servidor = p.servidor;
    else if (eraDeLista) s.servidor = "";
    S.pruebas[lado] = null;
    $(`#servidor-${lado}`).outerHTML = tarjetaServidor(lado);
    guardarConfig();
  } else if (t.dataset.servidor === "verificar") {
    const lado = t.closest("[data-lado]").dataset.lado;
    S.config[lado].verificar = t.checked;
    S.pruebas[lado] = null;
    refrescarPrueba(lado);
    guardarConfig();
  } else if (t.hasAttribute("data-sel")) {
    const id = Number(t.closest(".cuenta").dataset.id);
    t.checked ? S.excluidas.delete(id) : S.excluidas.add(id);
    guardarExcluidas();
    const todas = $("[data-sel-todas]");
    if (todas) todas.checked = S.cuentas.every((c) => !S.excluidas.has(c.id));
    $("#resumen-cuentas").innerHTML = resumenCuentas();
  } else if (t.hasAttribute("data-sel-todas")) {
    S.cuentas.forEach((c) => (t.checked ? S.excluidas.delete(c.id) : S.excluidas.add(c.id)));
    $$("[data-sel]").forEach((x) => (x.checked = t.checked));
    guardarExcluidas();
    $("#resumen-cuentas").innerHTML = resumenCuentas();
  } else if (t.closest("[data-espacio]") && (t.dataset.regla || t.hasAttribute("data-regla-desde") || t.hasAttribute("data-espacio-desde") || t.dataset.pesado)) {
    const correo = t.closest("[data-espacio]").dataset.espacio;
    const d = S.espacio[correo];
    if (t.dataset.regla) cambiarFiltro(correo, { [t.dataset.regla]: t.checked });
    else if (t.hasAttribute("data-regla-desde")) {
      const mes = t.closest(".regla").querySelector("[data-espacio-desde]").value;
      cambiarFiltro(correo, { desde: t.checked ? `${mes || new Date().toISOString().slice(0, 7)}-01` : null });
    } else if (t.hasAttribute("data-espacio-desde")) {
      if (t.value) cambiarFiltro(correo, { desde: `${t.value}-01` });
    } else {
      const x = d.pesados.find((p) => p.clave === t.dataset.pesado);
      const excluir = new Set(d.filtro.excluir), incluir = new Set(d.filtro.incluir);
      if (t.checked) { excluir.delete(x.clave); if (x.motivo && x.motivo !== "manual") incluir.add(x.clave); }
      else { incluir.delete(x.clave); excluir.add(x.clave); }
      cambiarFiltro(correo, { excluir: [...excluir], incluir: [...incluir] });
    }
  } else if (t.hasAttribute("data-auto-activa")) {
    configurarAutomatica({ activa: t.checked }).catch((err) => aviso(esc(err.message), "error"));
  } else if (t.hasAttribute("data-auto-hora")) {
    if (t.value) configurarAutomatica({ hora: t.value }).catch((err) => aviso(esc(err.message), "error"));
  } else if (t.hasAttribute("data-recordar")) {
    S.recordar = t.checked;
    guardarCuentasYa().then(() => { aviso(t.checked ? "Claves guardadas y cifradas en este equipo." : "Se borraron las claves guardadas.", "ok"); refrescarAutomatica(); });
  } else if (t.id === "archivo-csv" && t.files[0]) {
    t.files[0].text().then((texto) => agregarCuentas(interpretarLineas(texto)));
    t.value = "";
  }
});

document.addEventListener("toggle", (e) => {
  if (e.target.id === "avanzadas") escribir("avanzadas", e.target.open ? "1" : "0");
  if (e.target.id === "registro") {
    escribir("registro", e.target.open ? "1" : "0");
    if (e.target.open) { const l = $("#lineas"); l.scrollTop = l.scrollHeight; }
  }
}, true);

// ------------------------------------------------------------ eventos en vivo
function manejar(ev) {
  if (ev.tipo === "cuentas") {
    for (const [correo, p] of Object.entries(ev.datos)) { S.progreso[correo] = p; muestrear(correo, p); }
    refrescarVivo();
  } else if (ev.tipo === "log") {
    S.log.push(ev.linea);
    if (S.log.length > 1500) S.log.splice(0, S.log.length - 1500);
    const l = $("#lineas");
    if (l && pasaFiltro(ev.linea)) {
      const abajo = l.scrollHeight - l.scrollTop - l.clientHeight < 40;
      if (l.children.length === 1 && l.textContent.includes("Sin actividad")) l.innerHTML = "";
      l.insertAdjacentHTML("beforeend", lineaLog(ev.linea));
      if (abajo) l.scrollTop = l.scrollHeight;
    }
    const cont = $("#contador-errores");
    if (cont && ev.linea.nivel === "ERROR") { cont.hidden = false; cont.textContent = S.log.filter((x) => x.nivel === "ERROR").length; }
  } else if (ev.tipo === "trabajo") {
    const antes = S.trabajo.estado;
    S.trabajo = ev.trabajo;
    if (ev.resultados) S.resultados = ev.resultados;
    if (ev.app) S.app = ev.app;
    if (["terminado", "cancelado"].includes(ev.trabajo.estado) && ACTIVOS.includes(antes)) avisoFinal();
    refrescarVivo(true);
  }
}

function avisoFinal() {
  const t = S.trabajo, res = S.resultados[t.accion] || {};
  api("/api/estado").then((d) => { S.local = d.local; refrescarVivo(true); }).catch(() => {});
  if (t.estado === "cancelado") return aviso("Tarea cancelada. Lo hecho hasta ahora quedó guardado.", "info");
  const n = t.cuentas.length;
  const bien = (f) => t.cuentas.filter((c) => res[c]?.ok && f(res[c].resultado)).length;
  if (t.accion === "probar_origen") {
    const k = bien((r) => r.origen.ok);
    return aviso(k === n ? (n === 1 ? "La cuenta conecta bien." : `Las ${fmtN(n)} cuentas conectan bien.`) : `${fmtN(n - k)} de ${fmtN(n)} cuentas tienen problemas. Mirá la columna Estado.`, k === n ? "ok" : "error");
  }
  if (t.accion === "probar_destino") {
    const k = bien((r) => r.destino.ok);
    return aviso(k === n ? "Las cuentas del servidor nuevo están listas." : `${fmtN(n - k)} de ${fmtN(n)} cuentas no entran en el servidor nuevo. ¿Ya las creaste allá?`, k === n ? "ok" : "error");
  }
  if (t.accion === "adjuntos" || t.accion === "adjuntos_todos") {
    const r = res[t.cuentas[0]];
    if (!r?.ok) return aviso(`No se pudieron guardar los adjuntos: ${esc(r?.error || "")}`, "error");
    return aviso(`Adjuntos guardados: ${plural(r.resultado.archivos, "archivo", "archivos")} (${fmtB(r.resultado.bytes)}), ${fmtN(r.resultado.nuevos)} nuevos.`, "ok");
  }
  if (t.accion === "verificar") {
    const todo = bien((r) => r.ok) === n;
    return aviso(todo ? "Verificación sin diferencias." : "La verificación encontró diferencias. Revisá el detalle.", todo ? "ok" : "error");
  }
  const ok = t.cuentas.filter((c) => res[c]?.ok).length;
  const que = t.accion === "respaldar" ? "Copia local lista" : "Migración lista";
  aviso(ok === n ? `${que}: terminó sin errores.` : `Terminó con errores en ${plural(n - ok, "cuenta", "cuentas")}.`, ok === n ? "ok" : "error");
}

function marcarConexion(ok) {
  if (S.conectado === ok) return;
  S.conectado = ok;
  const c = $("#conexion");
  c.classList.toggle("caida", !ok);
  c.lastChild.textContent = ok ? "Conectado" : "Desconectado";
  if (!ok) aviso("Se perdió la conexión con el migrador. Si cerraste su ventana negra, volvé a abrir Migrador.bat.", "error");
  else cargarEstado(false);
}

function conectarEventos() {
  const es = new EventSource(`/api/eventos?t=${encodeURIComponent(window.TOKEN)}`);
  es.onopen = () => marcarConexion(true);
  es.onerror = () => marcarConexion(false);
  es.onmessage = (ev) => manejar(JSON.parse(ev.data));
}

// ------------------------------------------------------------ inicio
async function cargarEstado(inicial = true) {
  const d = await api("/api/estado");
  Object.assign(S, {
    config: d.config, proveedores: d.proveedores, recordar: d.recordar, clavesCifrables: d.claves_cifrables !== false,
    trabajo: d.trabajo, progreso: d.progreso, log: d.log, resultados: d.resultados, app: d.app, local: d.local,
    automatica: d.automatica, filtros: d.filtros || {},
  });
  if (inicial) {
    S.cuentas = d.cuentas.map(nuevaCuenta);
    let excluidas = [];
    try { excluidas = JSON.parse(leer("excluidas", "[]")); } catch {}
    for (const c of S.cuentas) if (excluidas.includes(c.correo.toLowerCase())) S.excluidas.add(c.id);
    S.paso = "inicio";
  }
  render();
}

function aplicarTema() {
  const b = $("#tema");
  const oscuro = document.documentElement.dataset.theme === "dark" ||
    (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
  b.innerHTML = ic(oscuro ? "sun" : "moon");
  b.onclick = () => {
    document.documentElement.dataset.theme = oscuro ? "light" : "dark";
    escribir("tema", document.documentElement.dataset.theme);
    aplicarTema();
  };
}

$$("[data-icono]").forEach((el) => (el.innerHTML = ic(el.dataset.icono)));
aplicarTema();
cargarEstado().then(conectarEventos).catch((e) => {
  $("#vista").innerHTML = `<div class="banner error">${ic("warning-circle")}<span>No se pudo cargar el migrador: ${esc(e.message)}</span></div>`;
});
