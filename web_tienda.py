"""Portal web basico de la tienda (:8080) conectado a la bitacora HTTPS (:8443).

Utiliza ClienteAPI de cliente_admin.py (F9 - Fernanda) para consumir el servidor
central por HTTPS/TLS (verify="certificado.pem") e incluye un apartado dedicado
para levantar y mostrar en vivo las evidencias de Fernanda (F7, F8 y F9).
"""

import argparse
import errno
import json
import os
import re
import socket
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from cliente_admin import ClienteAPI

HTML_PORTAL = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MiPyME Tienda Local — Operacion y Evidencias F7-F9</title>
  <style>
    :root {
      --bg: #f4f6f9;
      --card: #ffffff;
      --ink: #1e293b;
      --muted: #64748b;
      --line: #e2e8f0;
      --teal: #0f766e;
      --purple: #6d28d9;
      --purple-soft: #f5f3ff;
      --blue: #1d4ed8;
      --ok: #15803d;
      --warn: #b45309;
      --bad: #b91c1c;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
      background: var(--bg);
      color: var(--ink);
      line-height: 1.45;
    }
    header {
      background: linear-gradient(120deg, #0f172a, #1e293b);
      color: #fff;
      padding: 18px 24px;
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
    }
    header h1 { margin: 0; font-size: 1.25rem; }
    header p { margin: 2px 0 0; font-size: 0.88rem; color: #cbd5e1; }
    .pill {
      display: inline-block;
      padding: 5px 12px;
      border-radius: 999px;
      font-size: 0.82rem;
      font-weight: 600;
      background: #14532d;
      color: #bbf7d0;
    }
    .pill.offline { background: #7f1d1d; color: #fecaca; }
    main { max-width: 1180px; margin: 20px auto; padding: 0 16px 40px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; }
    .card {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 16px;
      box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
      margin-bottom: 16px;
    }
    .card h2 { margin: 0 0 10px; font-size: 1.05rem; }
    .card h3 { margin: 0 0 8px; font-size: 0.96rem; }
    .evidencias {
      border: 2px solid #ddd6fe;
      background: linear-gradient(180deg, var(--purple-soft) 0%, #ffffff 110px);
    }
    .tag {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 6px;
      font-size: 0.75rem;
      font-weight: 700;
      background: #ede9fe;
      color: var(--purple);
      margin-right: 6px;
    }
    .kpi { font-size: 1.5rem; font-weight: 700; margin: 4px 0; }
    .muted { color: var(--muted); font-size: 0.85rem; }
    button, input, select {
      font: inherit;
      padding: 7px 11px;
      border-radius: 7px;
      border: 1px solid #cbd5e1;
    }
    button {
      cursor: pointer;
      border: 0;
      background: var(--teal);
      color: #fff;
      font-weight: 600;
      font-size: 0.85rem;
    }
    button:hover { opacity: 0.92; }
    button.purple { background: var(--purple); }
    button.blue { background: var(--blue); }
    button.warn { background: var(--warn); }
    button.danger { background: var(--bad); }
    button.ghost { background: #e2e8f0; color: var(--ink); }
    .row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
    table { width: 100%; border-collapse: collapse; font-size: 0.86rem; margin-top: 8px; }
    th, td { text-align: left; padding: 8px 6px; border-bottom: 1px solid var(--line); vertical-align: top; }
    th { color: var(--muted); font-weight: 600; font-size: 0.78rem; text-transform: uppercase; }
    .estado { padding: 2px 8px; border-radius: 999px; font-size: 0.76rem; font-weight: 700; }
    .abierta { background: #fee2e2; color: #991b1b; }
    .en_proceso { background: #fef3c7; color: #92400e; }
    .resuelta { background: #dcfce7; color: #166534; }
    pre {
      background: #0f172a;
      color: #e2e8f0;
      padding: 12px;
      border-radius: 8px;
      overflow-x: auto;
      font-size: 0.8rem;
      max-height: 240px;
      margin: 8px 0 0;
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>MiPyME Tienda Local "La Esquina" — Portal Operativo</h1>
      <p>Alojado en :8080 · Conectado por HTTPS/TLS (:8443) usando cliente_admin.py (Equipo 01)</p>
    </div>
    <div class="row">
      <span id="badge-tls" class="pill">Conectando...</span>
      <button class="ghost" onclick="cargarTodo()">Actualizar</button>
    </div>
  </header>

  <main>
    <!-- SECCION 1: OPERACION BASICA DEL NEGOCIO -->
    <section class="card">
      <h2>1. Operacion del Negocio (Cajas y Salud del Servidor)</h2>
      <div class="grid">
        <div class="card" style="margin:0">
          <h3>Punto de Venta — Mostrador</h3>
          <div class="kpi" id="ventas-hoy">3 articulos activos</div>
          <p class="muted">Caja 1 (192.168.1.21) y Caja 2 (192.168.1.22) operando en red local.</p>
          <div class="row">
            <button onclick="simularVenta()">Registrar venta normal</button>
            <button class="danger" onclick="reportarEventoTienda()">Simular alerta de caja</button>
          </div>
          <p id="msg-tienda" class="muted" style="margin-top:8px;"></p>
        </div>

        <div class="card" style="margin:0">
          <h3>Canal Seguro HTTPS / Recursos</h3>
          <div class="kpi" id="kpi-recursos">CPU --% | RAM --%</div>
          <p class="muted" id="detalle-tls">Verificando handshake TLS...</p>
        </div>

        <div class="card" style="margin:0">
          <h3>Resumen de Incidencias</h3>
          <div class="kpi" id="kpi-incidencias">0 abiertas</div>
          <p class="muted" id="detalle-alertas">0 alertas enviadas a Telegram</p>
        </div>
      </div>
    </section>

    <!-- SECCION 2: APARTADO DE EVIDENCIAS DE FERNANDA (F7, F8 y F9) -->
    <section class="card evidencias">
      <h2><span class="tag">FERNANDA</span> Apartado de Evidencias: F7, F8 y F9 (Gestion, Auditoria y Pruebas)</h2>
      <p class="muted">
        Cada boton ejecuta peticiones reales contra el servidor HTTPS (:8443) usando <code>ClienteAPI</code>
        de <code>cliente_admin.py</code> y registra el resultado en la bitacora de evidencia inferior.
      </p>

      <!-- F9: PRUEBAS DE CONCURRENCIA, TOLERANCIA Y REGISTRO -->
      <div class="grid" style="margin-top:12px;">
        <div class="card" style="margin:0">
          <h3><span class="tag">F9</span> Pruebas de Concurrencia y Fallos</h3>
          <p class="muted">Demostracion automatica exigida en <code>cliente_admin.py</code>:</p>
          <div class="row">
            <button class="purple" onclick="probarConcurrencia()">3 hilos HTTPS simultaneos</button>
            <button class="warn" onclick="probarTolerancia()">Desconexion abrupta TLS</button>
          </div>
        </div>

        <div class="card" style="margin:0">
          <h3><span class="tag">F9</span> Registrar Incidencia (POST)</h3>
          <form class="row" onsubmit="crearIncidencia(event)">
            <select id="nuevo-tipo">
              <option value="alerta">alerta</option>
              <option value="vulnerabilidad">vulnerabilidad</option>
              <option value="incidente">incidente (alerta Telegram)</option>
            </select>
            <input id="nuevo-desc" type="text" placeholder="Descripcion del evento" required style="flex:1; min-width:160px;">
            <button class="blue" type="submit">Enviar POST</button>
          </form>
        </div>

        <div class="card" style="margin:0">
          <h3><span class="tag">F7</span> Reemplazo Completo (PUT)</h3>
          <form class="row" onsubmit="reemplazarIncidencia(event)">
            <input id="put-id" type="number" min="1" placeholder="ID" required style="width:72px;">
            <input id="put-tipo" type="text" value="alerta" required style="width:110px;">
            <input id="put-desc" type="text" placeholder="Nueva descripcion (reinicia a abierta)" required style="flex:1; min-width:130px;">
            <button class="purple" type="submit">Ejecutar PUT</button>
          </form>
        </div>
      </div>

      <!-- F7 & F8: GESTION CRUD EN TABLA -->
      <div style="margin-top:16px;">
        <h3><span class="tag">F7 / F8</span> Incidencias en SQLite — PATCH (estado), PUT (reemplazo) y DELETE (204)</h3>
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Hora</th>
              <th>Tipo</th>
              <th>Descripcion</th>
              <th>Estado</th>
              <th>Acciones Fernanda (F7 / F8)</th>
            </tr>
          </thead>
          <tbody id="tabla-incidencias">
            <tr><td colspan="6" class="muted">Cargando incidencias...</td></tr>
          </tbody>
        </table>
      </div>

      <!-- F8: METRICAS DE AUDITORIA -->
      <div class="grid" style="margin-top:16px;">
        <div class="card" style="margin:0">
          <h3><span class="tag">F8</span> GET /contadores</h3>
          <pre id="vista-contadores">{}</pre>
        </div>
        <div class="card" style="margin:0">
          <h3><span class="tag">F8</span> GET /alertas (Telegram)</h3>
          <pre id="vista-alertas">[]</pre>
        </div>
        <div class="card" style="margin:0">
          <h3><span class="tag">F8</span> GET /logs (Ultimos 8)</h3>
          <pre id="vista-logs">[]</pre>
        </div>
      </div>

      <!-- LOG EN VIVO DE EVIDENCIAS -->
      <div style="margin-top:16px;">
        <div class="row" style="justify-content:space-between;">
          <h3>Bitacora de Evidencias Ejecutadas</h3>
          <button class="ghost" onclick="limpiarBitacora()">Limpiar pantalla</button>
        </div>
        <pre id="bitacora-evidencia">Listo para ejecutar pruebas de F7, F8 y F9...</pre>
      </div>
    </section>
  </main>

  <script>
    let ventas = 0;
    const evidencias = [];

    function esc(texto) {
      return String(texto == null ? "" : texto)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }

    function registrarEvidencia(funcion, codigo, detalle) {
      const hora = new Date().toLocaleTimeString();
      const linea = `[${hora}] ${funcion} -> HTTP ${codigo} | ${JSON.stringify(detalle)}`;
      evidencias.unshift(linea);
      if (evidencias.length > 25) evidencias.pop();
      document.getElementById("bitacora-evidencia").textContent = evidencias.join("\\n");
    }

    function limpiarBitacora() {
      evidencias.length = 0;
      document.getElementById("bitacora-evidencia").textContent = "Bitacora limpia.";
    }

    function simularVenta() {
      ventas += 1;
      document.getElementById("msg-tienda").textContent = `Venta #${ventas} procesada localmente en mostrador.`;
    }

    async function reportarEventoTienda() {
      const r = await fetch("/api/incidencias", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          tipo: "incidente",
          descripcion: "Caja 1: Alerta de seguridad manual desde portal web de la tienda"
        })
      });
      const datos = await r.json();
      registrarEvidencia("Tienda POST /incidencias", r.status, datos);
      document.getElementById("msg-tienda").textContent = "Alerta enviada al servidor (:8443) y evaluada en Telegram.";
      await cargarTodo();
    }

    async function cargarTodo() {
      const resp = await fetch("/api/estado");
      const data = await resp.json();
      const badge = document.getElementById("badge-tls");

      if (!data.conectado) {
        badge.textContent = "Sin conexion con :8443";
        badge.classList.add("offline");
        return;
      }
      badge.classList.remove("offline");
      badge.textContent = `HTTPS ${data.salud.version_tls || "TLS"} conectado`;

      const rec = (data.salud && data.salud.recursos) || {};
      document.getElementById("kpi-recursos").textContent =
        `CPU ${rec.cpu_porcentaje ?? "--"}% | RAM ${rec.ram_porcentaje ?? "--"}%`;
      document.getElementById("detalle-tls").textContent =
        `Disco ${rec.disco_porcentaje ?? "--"}% · Cifrado: ${data.salud.cifrado || "TLS"}`;

      const incs = Array.isArray(data.incidencias) ? data.incidencias : [];
      const abiertas = incs.filter(i => i.estado === "abierta").length;
      const alertas = Array.isArray(data.alertas) ? data.alertas : [];
      document.getElementById("kpi-incidencias").textContent = `${abiertas} abiertas (${incs.length} total)`;
      document.getElementById("detalle-alertas").textContent = `${alertas.length} alerta(s) en alertas_telegram`;

      const tbody = document.getElementById("tabla-incidencias");
      if (!incs.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="muted">Sin incidencias registradas todavia.</td></tr>';
      } else {
        tbody.innerHTML = incs.slice().reverse().map(i => `
          <tr>
            <td><strong>#${esc(i.id)}</strong></td>
            <td>${esc(i.hora)}</td>
            <td>${esc(i.tipo)}</td>
            <td>${esc(i.descripcion)}</td>
            <td><span class="estado ${esc(i.estado)}">${esc(i.estado)}</span></td>
            <td class="row">
              <button class="warn" onclick="cambiarEstado(${Number(i.id)}, 'en_proceso')">PATCH en_proceso</button>
              <button onclick="cambiarEstado(${Number(i.id)}, 'resuelta')">PATCH resuelta</button>
              <button class="ghost" onclick="prepararPut(${Number(i.id)}, '${esc(i.tipo)}', '${esc(i.descripcion)}')">Cargar PUT</button>
              <button class="danger" onclick="eliminarIncidencia(${Number(i.id)})">DELETE</button>
            </td>
          </tr>
        `).join("");
      }

      document.getElementById("vista-contadores").textContent = JSON.stringify(data.contadores || {}, null, 2);
      document.getElementById("vista-alertas").textContent = JSON.stringify(alertas.slice(-5), null, 2);
      const logs = Array.isArray(data.logs) ? data.logs : [];
      document.getElementById("vista-logs").textContent = JSON.stringify(logs.slice(-8), null, 2);
    }

    function prepararPut(id, tipo, desc) {
      document.getElementById("put-id").value = id;
      document.getElementById("put-tipo").value = tipo;
      document.getElementById("put-desc").value = desc;
    }

    async function crearIncidencia(ev) {
      ev.preventDefault();
      const tipo = document.getElementById("nuevo-tipo").value;
      const descripcion = document.getElementById("nuevo-desc").value.trim();
      const r = await fetch("/api/incidencias", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({tipo, descripcion})
      });
      const datos = await r.json();
      registrarEvidencia("F9 POST /incidencias", r.status, datos);
      document.getElementById("nuevo-desc").value = "";
      await cargarTodo();
    }

    async function cambiarEstado(id, estado) {
      const r = await fetch(`/api/incidencias/${id}`, {
        method: "PATCH",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({estado})
      });
      const datos = await r.json();
      registrarEvidencia(`F7 PATCH /incidencias/${id}`, r.status, datos);
      await cargarTodo();
    }

    async function reemplazarIncidencia(ev) {
      ev.preventDefault();
      const id = document.getElementById("put-id").value;
      const tipo = document.getElementById("put-tipo").value.trim();
      const descripcion = document.getElementById("put-desc").value.trim();
      const r = await fetch(`/api/incidencias/${id}`, {
        method: "PUT",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({tipo, descripcion})
      });
      const datos = await r.json();
      registrarEvidencia(`F7 PUT /incidencias/${id}`, r.status, datos);
      await cargarTodo();
    }

    async function eliminarIncidencia(id) {
      const r = await fetch(`/api/incidencias/${id}`, {method: "DELETE"});
      const datos = r.status === 204 ? {eliminado: true} : await r.json();
      registrarEvidencia(`F8 DELETE /incidencias/${id}`, r.status, datos);
      await cargarTodo();
    }

    async function probarConcurrencia() {
      const r = await fetch("/api/evidencia/concurrencia", {method: "POST"});
      const datos = await r.json();
      registrarEvidencia("F9 Concurrencia (3 hilos)", r.status, datos);
      await cargarTodo();
    }

    async function probarTolerancia() {
      const r = await fetch("/api/evidencia/tolerancia", {method: "POST"});
      const datos = await r.json();
      registrarEvidencia("F9 Tolerancia a fallos TLS", r.status, datos);
      await cargarTodo();
    }

    cargarTodo();
    setInterval(cargarTodo, 15000);
  </script>
</body>
</html>
"""


def ejecutar_evidencia_concurrencia(cliente):
    """Ejecuta 3 consultas GET /salud simultaneas por HTTPS usando ClienteAPI."""
    codigos = [None] * 3
    inicio = time.monotonic()

    def tarea(indice):
        codigo, _ = cliente.solicitar("GET", "/salud")
        codigos[indice] = codigo

    hilos = [threading.Thread(target=tarea, args=(i,)) for i in range(3)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()

    duracion_ms = round((time.monotonic() - inicio) * 1000, 1)
    return {
        "funcion": "F9 Concurrencia (3 hilos HTTPS simultaneos)",
        "exito": all(c == 200 for c in codigos),
        "hilos": 3,
        "codigos": codigos,
        "duracion_ms": duracion_ms,
    }


def ejecutar_evidencia_tolerancia(cliente):
    """Abre un socket TLS, envia peticion truncada, cierra abruptamente y verifica /salud."""
    destino = urlsplit(cliente.url)
    host = destino.hostname or "127.0.0.1"
    puerto = destino.port or 8443
    desconexion_simulada = False

    try:
        contexto = ssl.create_default_context(cafile=cliente.certificado)
        with socket.create_connection((host, puerto), timeout=5) as conexion:
            with contexto.wrap_socket(conexion, server_hostname=host) as tls:
                peticion = (
                    "POST /incidencias HTTP/1.1\r\n"
                    f"Host: {host}\r\n"
                    "Content-Type: application/json\r\n"
                    "Content-Length: 1000\r\n"
                    "\r\n"
                    '{"tipo":"prueba",'
                )
                tls.sendall(peticion.encode("utf-8"))
                desconexion_simulada = True
    except (OSError, ssl.SSLError):
        desconexion_simulada = False

    codigo_salud, _ = cliente.solicitar("GET", "/salud")
    return {
        "funcion": "F9 Tolerancia a Fallos (desconexion abrupta TLS)",
        "exito": codigo_salud == 200,
        "desconexion_simulada": desconexion_simulada,
        "salud_posterior": codigo_salud,
    }


class ManejadorWebTienda(BaseHTTPRequestHandler):
    server_version = "WebTiendaEquipo01/1.0"

    def _cliente(self):
        return self.server.crear_cliente()

    def _enviar_html(self, codigo, html):
        cuerpo = html.encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _enviar_json(self, codigo, payload):
        cuerpo = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _enviar_204(self):
        self.send_response(204)
        self.send_header("Connection", "close")
        self.end_headers()

    def _leer_json(self):
        try:
            longitud = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if longitud <= 0:
            return {}
        try:
            datos = json.loads(self.rfile.read(longitud).decode("utf-8"))
            return datos if isinstance(datos, dict) else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

    def _reenviar(self, metodo, ruta_destino, datos=None):
        codigo, cuerpo = self._cliente().solicitar(metodo, ruta_destino, datos=datos)
        if codigo is None:
            self._enviar_json(502, {"error": "No se pudo conectar con el servidor central HTTPS"})
            return
        if codigo == 204:
            self._enviar_204()
            return
        self._enviar_json(codigo, cuerpo if cuerpo is not None else {})

    def _extraer_id_api(self):
        coincidencia = re.fullmatch(r"/api/incidencias/([0-9]+)", self.path)
        return int(coincidencia.group(1)) if coincidencia else None

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._enviar_html(200, HTML_PORTAL)
            return
        if self.path == "/api/estado":
            cliente = self._cliente()
            c_salud, salud = cliente.solicitar("GET", "/salud")
            if c_salud is None:
                self._enviar_json(200, {"conectado": False})
                return
            _, incidencias = cliente.solicitar("GET", "/incidencias")
            _, contadores = cliente.solicitar("GET", "/contadores")
            _, alertas = cliente.solicitar("GET", "/alertas")
            _, logs = cliente.solicitar("GET", "/logs")
            self._enviar_json(
                200,
                {
                    "conectado": True,
                    "salud": salud,
                    "incidencias": incidencias if isinstance(incidencias, list) else [],
                    "contadores": contadores if isinstance(contadores, dict) else {},
                    "alertas": alertas if isinstance(alertas, list) else [],
                    "logs": logs if isinstance(logs, list) else [],
                },
            )
            return
        self._enviar_json(404, {"error": "Ruta no encontrada"})

    def do_POST(self):
        if self.path == "/api/incidencias":
            datos = self._leer_json()
            if datos is None:
                self._enviar_json(400, {"error": "JSON invalido"})
                return
            self._reenviar("POST", "/incidencias", datos=datos)
            return
        if self.path == "/api/evidencia/concurrencia":
            self._enviar_json(200, ejecutar_evidencia_concurrencia(self._cliente()))
            return
        if self.path == "/api/evidencia/tolerancia":
            self._enviar_json(200, ejecutar_evidencia_tolerancia(self._cliente()))
            return
        self._enviar_json(404, {"error": "Ruta no encontrada"})

    def do_PATCH(self):
        incidencia_id = self._extraer_id_api()
        if incidencia_id is None:
            self._enviar_json(404, {"error": "Ruta no encontrada"})
            return
        datos = self._leer_json()
        if datos is None:
            self._enviar_json(400, {"error": "JSON invalido"})
            return
        self._reenviar("PATCH", f"/incidencias/{incidencia_id}", datos=datos)

    def do_PUT(self):
        incidencia_id = self._extraer_id_api()
        if incidencia_id is None:
            self._enviar_json(404, {"error": "Ruta no encontrada"})
            return
        datos = self._leer_json()
        if datos is None:
            self._enviar_json(400, {"error": "JSON invalido"})
            return
        self._reenviar("PUT", f"/incidencias/{incidencia_id}", datos=datos)

    def do_DELETE(self):
        incidencia_id = self._extraer_id_api()
        if incidencia_id is None:
            self._enviar_json(404, {"error": "Ruta no encontrada"})
            return
        self._reenviar("DELETE", f"/incidencias/{incidencia_id}")

    def log_message(self, formato, *args):
        sys.stderr.write("[web_tienda] %s %s\n" % (self.client_address[0], formato % args))


class ServidorWebTienda(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, direccion, url_bitacora, ruta_certificado, api_key=None):
        self.url_bitacora = url_bitacora
        self.ruta_certificado = ruta_certificado
        self.api_key = api_key
        super().__init__(direccion, ManejadorWebTienda)

    def crear_cliente(self):
        return ClienteAPI(self.url_bitacora, self.ruta_certificado, api_key=self.api_key)


def construir_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0", help="Interfaz web (por defecto: 0.0.0.0)")
    parser.add_argument(
        "--puerto",
        "--port",
        dest="puerto",
        type=int,
        default=8080,
        help="Puerto HTTP del portal web de la tienda (por defecto: 8080)",
    )
    parser.add_argument(
        "--url-bitacora",
        default=os.environ.get("BITACORA_URL", "https://localhost:8443"),
        help="URL del servidor central HTTPS (por defecto: https://localhost:8443)",
    )
    parser.add_argument(
        "--cert",
        default=os.environ.get("BITACORA_CERT", "certificado.pem"),
        help="Ruta al certificado TLS del servidor central (por defecto: certificado.pem)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("BITACORA_API_KEY", ""),
        help="Clave X-API-Key opcional para conectarse a :8443",
    )
    return parser


def main(argv=None):
    args = construir_parser().parse_args(argv)
    api_key = args.api_key.strip() or None
    try:
        servidor = ServidorWebTienda(
            (args.host, args.puerto),
            args.url_bitacora,
            args.cert,
            api_key=api_key,
        )
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            print(
                f"El puerto {args.puerto} ya esta en uso. Prueba con: "
                f"python3 web_tienda.py --puerto {args.puerto + 1}",
                file=sys.stderr,
            )
        else:
            print(f"No se pudo abrir {args.host}:{args.puerto} ({exc})", file=sys.stderr)
        return 1

    print(
        f"Web de la Tienda escuchando en http://{args.host}:{args.puerto} "
        f"(conectado a {args.url_bitacora})"
    )
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nDeteniendo portal web...")
    finally:
        servidor.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
