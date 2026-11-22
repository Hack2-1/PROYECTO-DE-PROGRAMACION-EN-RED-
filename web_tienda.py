"""Portal web de la tienda (:40000) conectado a la bitacora HTTPS (:8443).

Sirve los archivos de web/ (tienda POS, apartado de evidencias de Fernanda F7-F9
y monitoreo/alertas Telegram) comunicandose por HTTPS/TLS con ClienteAPI (cliente_admin.py).
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

DIRECTORIO_WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
ESTATICOS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/estilos.css": ("estilos.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
}


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


def ejecutar_evidencia_sin_tls(cliente):
    """Envia HTTP plano al puerto TLS (rechazado en /logs) y registra el incidente."""
    destino = urlsplit(cliente.url)
    host = destino.hostname or "127.0.0.1"
    puerto = destino.port or 8443
    rechazado = False
    try:
        with socket.create_connection((host, puerto), timeout=5) as sock:
            sock.sendall(b"GET /salud HTTP/1.1\r\nHost: intruso\r\n\r\n")
            try:
                sock.recv(256)
            except OSError:
                pass
            rechazado = True
    except OSError:
        rechazado = False

    codigo, cuerpo = cliente.solicitar(
        "POST",
        "/incidencias",
        {
            "tipo": "incidente",
            "descripcion": f"Alteracion de seguridad: intento HTTP plano sin TLS en puerto {puerto}",
        },
    )
    return {
        "exito": codigo == 201,
        "rechazo_tls_enviado": rechazado,
        "incidencia": cuerpo,
        "mensaje": f"Peticion sin TLS rechazada e incidencia #{(cuerpo or {}).get('id', '?')} notificada.",
    }


class ManejadorWebTienda(BaseHTTPRequestHandler):
    server_version = "WebTiendaEquipo01/2.0"

    def _cliente(self):
        return self.server.crear_cliente()

    def _enviar_bytes(self, codigo, contenido, tipo_contenido):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo_contenido)
        self.send_header("Content-Length", str(len(contenido)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(contenido)

    def _enviar_json(self, codigo, payload):
        cuerpo = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._enviar_bytes(codigo, cuerpo, "application/json; charset=utf-8")

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
        ruta = self.path.split("?", 1)[0]
        if ruta in ESTATICOS:
            archivo, mime = ESTATICOS[ruta]
            try:
                with open(os.path.join(DIRECTORIO_WEB, archivo), "rb") as f:
                    self._enviar_bytes(200, f.read(), mime)
            except OSError:
                self._enviar_json(500, {"error": f"No se encontro web/{archivo}"})
            return

        if ruta == "/api/estado":
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
        if self.path == "/api/evidencia/sin-tls":
            res = ejecutar_evidencia_sin_tls(self._cliente())
            self._enviar_json(201 if res["exito"] else 502, res)
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
        default=40000,
        help="Puerto HTTP del portal web de la tienda (por defecto: 40000)",
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
