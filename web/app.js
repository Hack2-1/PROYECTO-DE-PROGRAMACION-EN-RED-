const PRODUCTOS = [
  { id: 1, cat: "Abarrotes", nombre: "Aceite Vegetal 1L", precio: 42.0 },
  { id: 2, cat: "Bebidas", nombre: "Agua Purificada 1.5L", precio: 18.0 },
  { id: 3, cat: "Lácteos", nombre: "Leche Entera 1L", precio: 27.5 },
  { id: 4, cat: "Panadería", nombre: "Pan de Caja Integral", precio: 46.0 },
  { id: 5, cat: "Limpieza", nombre: "Detergente Multiusos", precio: 35.0 },
  { id: 6, cat: "Higiene", nombre: "Gel Antibacterial 250ml", precio: 32.0 },
];

const carrito = [];
const ventas = [];
const evidencias = [];
let cacheIncidencias = [];

function esc(texto) {
  return String(texto == null ? "" : texto)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function dinero(valor) {
  return "$" + Number(valor || 0).toFixed(2);
}

function cambiarTab(tabId) {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tabId);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === tabId);
  });
}

/* ================================================================== */
/* VISTA 1: TIENDA / PUNTO DE VENTA                                   */
/* ================================================================== */
function renderizarCatalogo() {
  const grid = document.getElementById("catalogo-grid");
  grid.innerHTML = PRODUCTOS.map((p) => `
    <div class="product-item">
      <div>
        <span class="product-cat">${esc(p.cat)}</span>
        <div class="product-name">${esc(p.nombre)}</div>
      </div>
      <div class="row" style="justify-content:space-between;">
        <span class="product-price">${dinero(p.precio)}</span>
        <button type="button" class="btn btn-sm btn-primary" onclick="agregarAlTicket(${p.id})">+ Agregar</button>
      </div>
    </div>
  `).join("");
}

function cambiarCaja() {
  const val = document.getElementById("selector-caja").value;
  document.getElementById("kpi-caja").textContent = val.split("(")[0].trim();
}

function agregarAlTicket(id) {
  const prod = PRODUCTOS.find((p) => p.id === id);
  if (!prod) return;
  const existente = carrito.find((item) => item.id === id);
  if (existente) {
    existente.cantidad += 1;
  } else {
    carrito.push({ ...prod, cantidad: 1 });
  }
  renderizarCarrito();
}

function quitarDelTicket(id) {
  const idx = carrito.findIndex((item) => item.id === id);
  if (idx >= 0) carrito.splice(idx, 1);
  renderizarCarrito();
}

function vaciarCarrito() {
  carrito.length = 0;
  renderizarCarrito();
}

function renderizarCarrito() {
  const cont = document.getElementById("carrito-lista");
  if (!carrito.length) {
    cont.innerHTML = '<p class="muted empty-msg">El ticket está vacío. Agrega productos del catálogo.</p>';
  } else {
    cont.innerHTML = carrito.map((item) => `
      <div class="cart-row">
        <div>
          <strong>${esc(item.nombre)}</strong>
          <div class="muted">${item.cantidad} x ${dinero(item.precio)}</div>
        </div>
        <div class="row">
          <strong>${dinero(item.cantidad * item.precio)}</strong>
          <button type="button" class="btn btn-sm btn-ghost" onclick="quitarDelTicket(${item.id})">x</button>
        </div>
      </div>
    `).join("");
  }

  const total = carrito.reduce((acc, i) => acc + i.cantidad * i.precio, 0);
  const subtotal = total / 1.16;
  const iva = total - subtotal;
  document.getElementById("ticket-subtotal").textContent = dinero(subtotal);
  document.getElementById("ticket-iva").textContent = dinero(iva);
  document.getElementById("ticket-total").textContent = dinero(total);
}

function cobrarVenta() {
  if (!carrito.length) {
    document.getElementById("msg-pos").textContent = "Agrega al menos un producto para cobrar.";
    return;
  }
  const total = carrito.reduce((acc, i) => acc + i.cantidad * i.precio, 0);
  const piezas = carrito.reduce((acc, i) => acc + i.cantidad, 0);
  const caja = document.getElementById("selector-caja").value;
  ventas.unshift({
    folio: `V-${String(ventas.length + 1).padStart(3, "0")}`,
    hora: new Date().toLocaleTimeString(),
    caja,
    piezas,
    total,
  });
  vaciarCarrito();
  const ingresos = ventas.reduce((acc, v) => acc + v.total, 0);
  document.getElementById("kpi-ventas-num").textContent = `${ventas.length} ticket(s)`;
  document.getElementById("kpi-ventas-monto").textContent = dinero(ingresos);
  document.getElementById("msg-pos").textContent = `Venta ${ventas[0].folio} cobrada por ${dinero(total)}.`;

  document.getElementById("tabla-ventas").innerHTML = ventas.slice(0, 8).map((v) => `
    <tr>
      <td><strong>${esc(v.folio)}</strong></td>
      <td>${esc(v.hora)}</td>
      <td>${esc(v.caja)}</td>
      <td>${v.piezas} pza(s)</td>
      <td><strong>${dinero(v.total)}</strong></td>
    </tr>
  `).join("");
}

async function reportarDesdeTienda() {
  const input = document.getElementById("tienda-incidente-txt");
  const caja = document.getElementById("selector-caja").value;
  const texto = input.value.trim() || "Falla operativa reportada desde mostrador";
  const resp = await fetch("/api/incidencias", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tipo: "incidente", descripcion: `${caja}: ${texto}` }),
  });
  const datos = await resp.json();
  registrarEvidencia("Tienda POST", "POST /incidencias", resp.status, `Incidencia #${datos.id || "?"} registrada`);
  input.value = "";
  document.getElementById("msg-pos").textContent = "Incidente enviado al servidor HTTPS (:8443) y notificado.";
  await cargarTodo();
}

/* ================================================================== */
/* VISTA 2: EVIDENCIAS DE FERNANDA (F7, F8 y F9)                      */
/* ================================================================== */
function registrarEvidencia(funcion, operacion, codigo, resumen) {
  evidencias.unshift({
    hora: new Date().toLocaleTimeString(),
    funcion,
    operacion,
    codigo,
    resumen,
  });
  if (evidencias.length > 30) evidencias.pop();
  document.getElementById("contador-evidencias").textContent = String(evidencias.length);
  document.getElementById("tabla-evidencias").innerHTML = evidencias.map((e) => `
    <tr>
      <td>${esc(e.hora)}</td>
      <td><span class="tag-fn">${esc(e.funcion)}</span></td>
      <td><code>${esc(e.operacion)}</code></td>
      <td><span class="${e.codigo >= 200 && e.codigo < 300 ? "ok-badge" : "err-badge"}">HTTP ${esc(e.codigo)}</span></td>
      <td>${esc(e.resumen)}</td>
    </tr>
  `).join("");
}

function limpiarBitacora() {
  evidencias.length = 0;
  document.getElementById("contador-evidencias").textContent = "0";
  document.getElementById("tabla-evidencias").innerHTML =
    '<tr><td colspan="5" class="muted">Historial limpio.</td></tr>';
}

function renderizarIncidencias() {
  const filtro = document.getElementById("filtro-estado").value;
  const lista = cacheIncidencias.filter((i) => !filtro || i.estado === filtro);
  const tbody = document.getElementById("tabla-incidencias");
  if (!lista.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="muted">No hay incidencias para mostrar.</td></tr>';
    return;
  }
  tbody.innerHTML = lista.slice().reverse().map((i) => `
    <tr>
      <td><strong>#${esc(i.id)}</strong></td>
      <td>${esc(i.hora)}</td>
      <td>${esc(i.tipo)}</td>
      <td>${esc(i.descripcion)}</td>
      <td><span class="estado ${esc(i.estado)}">${esc(i.estado)}</span></td>
      <td class="row">
        <button type="button" class="btn btn-sm btn-warn" onclick="cambiarEstado(${Number(i.id)}, 'en_proceso')">PATCH en_proceso</button>
        <button type="button" class="btn btn-sm btn-primary" onclick="cambiarEstado(${Number(i.id)}, 'resuelta')">PATCH resuelta</button>
        <button type="button" class="btn btn-sm btn-ghost" onclick="prepararPut(${Number(i.id)})">Cargar PUT</button>
        <button type="button" class="btn btn-sm btn-danger" onclick="eliminarIncidencia(${Number(i.id)})">DELETE</button>
      </td>
    </tr>
  `).join("");
}

function prepararPut(id) {
  const inc = cacheIncidencias.find((item) => item.id === id);
  if (!inc) return;
  document.getElementById("put-id").value = inc.id;
  document.getElementById("put-tipo").value = inc.tipo;
  document.getElementById("put-desc").value = inc.descripcion;
}

async function crearIncidencia(ev) {
  ev.preventDefault();
  const tipo = document.getElementById("nuevo-tipo").value;
  const descripcion = document.getElementById("nuevo-desc").value.trim();
  const r = await fetch("/api/incidencias", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tipo, descripcion }),
  });
  const d = await r.json();
  registrarEvidencia("F9 / F4", "POST /incidencias", r.status, `Creada incidencia #${d.id || "?"} (${d.estado || d.error || ""})`);
  document.getElementById("nuevo-desc").value = "";
  await cargarTodo();
}

async function cambiarEstado(id, estado) {
  const r = await fetch(`/api/incidencias/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ estado }),
  });
  const d = await r.json();
  registrarEvidencia("F7 PATCH", `PATCH /incidencias/${id}`, r.status, `Estado cambiado a ${d.estado || d.error || ""}`);
  await cargarTodo();
}

async function reemplazarIncidencia(ev) {
  ev.preventDefault();
  const id = document.getElementById("put-id").value;
  const tipo = document.getElementById("put-tipo").value.trim();
  const descripcion = document.getElementById("put-desc").value.trim();
  const r = await fetch(`/api/incidencias/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tipo, descripcion }),
  });
  const d = await r.json();
  registrarEvidencia("F7 PUT", `PUT /incidencias/${id}`, r.status, `Reemplazada y reiniciada a ${d.estado || d.error || ""}`);
  await cargarTodo();
}

async function eliminarIncidencia(id) {
  const r = await fetch(`/api/incidencias/${id}`, { method: "DELETE" });
  const resumen = r.status === 204 ? `Incidencia #${id} eliminada (204 No Content)` : "No se pudo eliminar";
  registrarEvidencia("F8 DELETE", `DELETE /incidencias/${id}`, r.status, resumen);
  await cargarTodo();
}

async function probarConcurrencia() {
  const r = await fetch("/api/evidencia/concurrencia", { method: "POST" });
  const d = await r.json();
  const texto = `${d.exito ? "CORRECTA" : "FALLIDA"}: ${d.hilos} hilos -> [${(d.codigos || []).join(", ")}] en ${d.duracion_ms} ms`;
  document.getElementById("resultado-f9").textContent = texto;
  registrarEvidencia("F9 Concurrencia", "3 hilos GET /salud", r.status, texto);
  await cargarTodo();
}

async function probarTolerancia() {
  const r = await fetch("/api/evidencia/tolerancia", { method: "POST" });
  const d = await r.json();
  const texto = `${d.exito ? "CORRECTA" : "FALLIDA"}: corte TLS simulado, /salud posterior HTTP ${d.salud_posterior}`;
  document.getElementById("resultado-f9").textContent = texto;
  registrarEvidencia("F9 Tolerancia", "Desconexion abrupta TLS", r.status, texto);
  await cargarTodo();
}

function renderizarAuditoria(contadores, alertas, logs) {
  document.getElementById("total-peticiones-badge").textContent = `${contadores.total || 0} peticiones`;
  const fam = contadores.por_familia || {};
  const met = contadores.por_metodo || {};
  const tiles = [
    ["Familia 2xx", fam["2xx"] || 0],
    ["Familia 4xx", fam["4xx"] || 0],
    ["Familia 5xx", fam["5xx"] || 0],
    ...Object.entries(met).map(([m, n]) => [`Método ${m}`, n]),
  ];
  document.getElementById("panel-contadores").innerHTML = tiles.map(([k, v]) => `
    <div class="metric-tile"><span>${esc(k)}</span><strong>${esc(v)}</strong></div>
  `).join("");

  document.getElementById("total-alertas-badge").textContent = `${alertas.length} alertas`;
  const tbAlertas = document.getElementById("tabla-alertas");
  tbAlertas.innerHTML = !alertas.length
    ? '<tr><td colspan="5" class="muted">Sin alertas registradas todavía.</td></tr>'
    : alertas.slice(-6).reverse().map((a) => `
      <tr>
        <td>#${esc(a.id_alerta)}</td>
        <td>${esc(a.hora)}</td>
        <td>#${esc(a.incidencia_id)}</td>
        <td>${esc(a.motivo)}</td>
        <td><span class="${a.estado_envio === "ENVIADO" ? "ok-badge" : "err-badge"}">${esc(a.estado_envio)} (${esc(a.codigo_http)})</span></td>
      </tr>
    `).join("");

  const tbLogs = document.getElementById("tabla-logs");
  tbLogs.innerHTML = !logs.length
    ? '<tr><td colspan="6" class="muted">Sin eventos registrados aún.</td></tr>'
    : logs.slice(-10).reverse().map((l) => `
      <tr>
        <td>#${esc(l.id_log)}</td>
        <td>${esc(l.hora)}</td>
        <td><strong>${esc(l.metodo || l.tipo)}</strong></td>
        <td>${esc(l.ruta || l.detalle)}</td>
        <td>${l.codigo ? `<span class="${l.codigo < 400 ? "ok-badge" : "err-badge"}">${esc(l.codigo)}</span>` : "—"}</td>
        <td>${esc(l.cliente)}</td>
      </tr>
    `).join("");
}

/* ================================================================== */
/* VISTA 3: MONITOREO DE SERVIDOR Y SIMULADOR TELEGRAM                */
/* ================================================================== */
function actualizarBarra(idBar, idLbl, pct) {
  const val = Math.max(0, Math.min(100, Number(pct || 0)));
  document.getElementById(idLbl).textContent = `${val.toFixed(1)}%`;
  const el = document.getElementById(idBar);
  el.style.width = `${val}%`;
  el.className = "meter-fill" + (val >= 85 ? " bad" : val >= 70 ? " warn" : "");
}

async function simularEscenario(tipo) {
  const mapa = {
    cpu: ["incidente", "Uso critico de CPU en servidor: 96.0% (supera umbral de 85%)"],
    ram: ["incidente", "Saturacion de memoria RAM en servidor: 93.5% (supera umbral de 85%)"],
  };
  if (tipo === "acumulacion") {
    const lote = [
      ["vulnerabilidad", "Caja 1: Puerto no autorizado abierto: 21 (FTP)"],
      ["vulnerabilidad", "Caja 2: Puerto no autorizado abierto: 445 (SMB)"],
      ["alerta", "Espacio en disco critico en servidor: 91.0% (supera umbral de 90%)"],
    ];
    for (const [t, desc] of lote) {
      await fetch("/api/incidencias", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tipo: t, descripcion: desc }),
      });
    }
    document.getElementById("msg-monitor").textContent = "Se registraron 3 incidencias abiertas; revisa la alerta por acumulación en Telegram.";
    registrarEvidencia("F3 / F4", "Acumulación >= 3", 201, "3 incidencias abiertas creadas -> UMBRAL_ACUMULACION");
  } else if (mapa[tipo]) {
    const [t, desc] = mapa[tipo];
    const r = await fetch("/api/incidencias", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tipo: t, descripcion: desc }),
    });
    const d = await r.json();
    document.getElementById("msg-monitor").textContent = `Incidencia #${d.id} guardada en SQLite y enviada a Telegram.`;
    registrarEvidencia("F3 / F4", `Simular ${tipo.toUpperCase()}`, r.status, desc);
  }
  await cargarTodo();
}

async function simularIntrusoTls() {
  const r = await fetch("/api/evidencia/sin-tls", { method: "POST" });
  const d = await r.json();
  document.getElementById("msg-monitor").textContent = d.mensaje || "Intento sin TLS simulado y reportado a Telegram.";
  registrarEvidencia("F1 / F3", "Intrusión sin TLS", r.status, d.mensaje || "TLS rechazado + incidente creado");
  await cargarTodo();
}

async function cargarTodo() {
  try {
    const resp = await fetch("/api/estado");
    const data = await resp.json();
    const badge = document.getElementById("badge-tls");

    if (!data.conectado) {
      badge.textContent = "Sin conexión con :8443";
      badge.classList.add("offline");
      document.getElementById("kpi-proteccion").textContent = "Desconectado";
      return;
    }

    badge.classList.remove("offline");
    badge.textContent = `HTTPS ${data.salud.version_tls || "TLS"} activo`;
    document.getElementById("kpi-proteccion").textContent = `${data.salud.version_tls || "TLS"} Activo`;

    const rec = (data.salud && data.salud.recursos) || {};
    actualizarBarra("bar-cpu", "lbl-cpu", rec.cpu_porcentaje);
    actualizarBarra("bar-ram", "lbl-ram", rec.ram_porcentaje);
    actualizarBarra("bar-disco", "lbl-disco", rec.disco_porcentaje);
    if (rec.ram_total_mb) {
      document.getElementById("lbl-ram-mb").textContent = `${rec.ram_usada_mb} / ${rec.ram_total_mb} MB`;
    }
    document.getElementById("lbl-tls-info").textContent = `Cifrado: ${data.salud.cifrado || "TLS"}`;

    cacheIncidencias = Array.isArray(data.incidencias) ? data.incidencias : [];
    renderizarIncidencias();
    renderizarAuditoria(
      data.contadores || {},
      Array.isArray(data.alertas) ? data.alertas : [],
      Array.isArray(data.logs) ? data.logs : []
    );
  } catch (err) {
    console.error(err);
  }
}

renderizarCatalogo();
renderizarCarrito();
cargarTodo();
setInterval(cargarTodo, 15000);
