"""Manejador HTTP base del sistema de bitacora de incidencias.

Contiene las utilidades compartidas, GET /salud, la auditoria automatica
(logs y contadores) y el enrutamiento. Cada integrante implementa SOLO sus
zonas marcadas (ver docs/GUIA_EQUIPO_GIT.md).
"""

import json
import re
import ssl
import sys
import traceback
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

TAMANO_MAXIMO_CUERPO = 1024 * 1024  # 1 MiB


class ManejadorBitacora(BaseHTTPRequestHandler):
    server_version = "BitacoraEquipo01/1.0"
    timeout = 30  # evita hilos colgados por clientes que no envian datos

    # ------------------------------------------------------------------
    # Acceso a colaboradores (inyectados por servidor_bitacora.py)
    # ------------------------------------------------------------------
    def _obtener_almacen(self):
        return getattr(self.server, "almacen", None)

    def _obtener_notificador(self):
        return getattr(self.server, "notificador", None)

    # ------------------------------------------------------------------
    # Utilidades compartidas
    # ------------------------------------------------------------------
    def _ruta_y_query(self):
        """Devuelve (ruta_normalizada, query_dict) sin barra final."""
        partes = urlparse(self.path)
        ruta = partes.path or "/"
        if len(ruta) > 1:
            ruta = ruta.rstrip("/") or "/"
        return ruta, parse_qs(partes.query)

    def _leer_json_cuerpo(self):
        """Devuelve (datos, None) o (None, (codigo, mensaje)). Solo objetos JSON."""
        longitud_txt = self.headers.get("Content-Length")
        if longitud_txt is None:
            return None, (400, "Se requiere cuerpo JSON (falta Content-Length)")
        try:
            longitud = int(longitud_txt)
        except ValueError:
            return None, (400, "Content-Length invalido")
        if longitud <= 0:
            return None, (400, "El cuerpo JSON no puede estar vacio")
        if longitud > TAMANO_MAXIMO_CUERPO:
            return None, (413, "Cuerpo demasiado grande")
        crudo = self.rfile.read(longitud)
        try:
            datos = json.loads(crudo.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None, (400, "JSON invalido")
        if not isinstance(datos, dict):
            return None, (400, "El cuerpo debe ser un objeto JSON")
        return datos, None

    def _extraer_id_incidencia(self, ruta):
        """Devuelve (id, None) o (None, (400, mensaje)) para /incidencias/<id>."""
        coincidencia = re.fullmatch(r"/incidencias/([^/]+)", ruta)
        if not coincidencia:
            return None, (400, "Ruta de incidencia invalida")
        texto = coincidencia.group(1)
        if not re.fullmatch(r"[0-9]+", texto) or int(texto) <= 0:
            return None, (400, "El ID debe ser un entero positivo")
        return int(texto), None

    def _registrar_peticion(self, codigo):
        almacen = self._obtener_almacen()
        if almacen is None:
            return
        try:
            ruta = urlparse(self.path).path if getattr(self, "path", None) else "-"
            almacen.registrar_peticion(
                getattr(self, "command", None) or "DESCONOCIDO",
                ruta,
                codigo,
                self.client_address[0] if self.client_address else "-",
            )
        except Exception:  # la auditoria nunca debe romper la respuesta
            traceback.print_exc(file=sys.stderr)

    def _enviar_json(self, codigo, payload):
        cuerpo = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._registrar_peticion(codigo)
        self._respuesta_enviada = True
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _enviar_sin_contenido(self, codigo=204):
        self._registrar_peticion(codigo)
        self._respuesta_enviada = True
        self.send_response(codigo)
        self.send_header("Connection", "close")
        self.end_headers()

    def _enviar_error_json(self, error):
        """Atajo para el par (codigo, mensaje) que devuelven los helpers."""
        self._enviar_json(error[0], {"error": error[1]})

    def _verificar_api_key(self):
        """Valida la cabecera X-API-Key cuando config.API_KEYS tiene claves activas."""
        api_keys = getattr(self.server, "api_keys", None)
        if not api_keys:
            return True
        clave = (self.headers.get("X-API-Key") or "").strip()
        if clave in api_keys:
            return True
        almacen = self._obtener_almacen()
        if almacen is not None:
            almacen.registrar_evento(
                "API_KEY_RECHAZADA",
                self.client_address[0] if self.client_address else "-",
                "Peticion sin X-API-Key valida",
            )
        self._enviar_json(401, {"error": "X-API-Key invalida o ausente"})
        return False

    # ------------------------------------------------------------------
    # Tolerancia a fallos y errores homogeneos en JSON
    # ------------------------------------------------------------------
    def send_error(self, code, message=None, explain=None):
        self.close_connection = True
        try:
            texto = message or self.responses.get(code, ("Error",))[0]
            self._enviar_json(code, {"error": texto})
        except OSError:
            pass

    def handle_one_request(self):
        self._respuesta_enviada = False
        try:
            super().handle_one_request()
        except OSError as exc:  # BrokenPipe, ConnectionReset, timeout, SSL...
            self.close_connection = True
            almacen = self._obtener_almacen()
            if almacen is not None:
                almacen.registrar_evento(
                    "CONEXION_INTERRUMPIDA",
                    self.client_address[0] if self.client_address else "-",
                    type(exc).__name__,
                )
        except Exception:
            traceback.print_exc(file=sys.stderr)
            self.close_connection = True
            if not self._respuesta_enviada:
                try:
                    self._enviar_json(500, {"error": "Error interno del servidor"})
                except OSError:
                    pass

    def log_message(self, formato, *args):
        sys.stderr.write(
            "[%s] %s %s\n"
            % (datetime.now().strftime("%H:%M:%S"), self.client_address[0], formato % args)
        )

    # ------------------------------------------------------------------
    # Enrutamiento
    # ------------------------------------------------------------------
    def do_GET(self):
        ruta, _ = self._ruta_y_query()
        if ruta == "/salud":
            self.manejar_salud()
        elif ruta == "/incidencias" or ruta.startswith("/incidencias/"):
            self.manejar_get_incidencias()
        elif ruta in ("/logs", "/contadores", "/alertas"):
            self.manejar_get_auditoria()
        else:
            self._enviar_json(404, {"error": "Ruta no encontrada"})

    def manejar_salud(self):
        conexion = self.connection
        cifrado = conexion.cipher() if isinstance(conexion, ssl.SSLSocket) else None
        self._enviar_json(
            200,
            {
                "estado": "ok",
                "tls": isinstance(conexion, ssl.SSLSocket),
                "version_tls": conexion.version() if cifrado else None,
                "cifrado": cifrado[0] if cifrado else None,
                "hora": datetime.now().astimezone().isoformat(timespec="seconds"),
            },
        )

    def _no_implementado(self, funcion, responsable):
        self._enviar_json(
            501, {"error": "No implementado", "funcion": funcion, "responsable": responsable}
        )

    # ==================================================================
    # ZONA RODRIGO GARCIA (F4 y F5) - rama feature/registro-consultas-agente
    # ==================================================================
    def do_POST(self):
        # F4: POST /incidencias (validar, almacen.crear_incidencia, notificador).
        self._no_implementado("F4", "Rodrigo Garcia")

    def manejar_get_incidencias(self):
        # F5: GET /incidencias (?tipo=&estado=) y GET /incidencias/<id>.
        self._no_implementado("F5", "Rodrigo Garcia")

    # ==================================================================
    # ZONA FERNANDA (F7 y F8) - rama feature/gestion-auditoria-cliente
    # ==================================================================

    def do_PATCH(self):
        # F7: Cambiar el estado de una incidencia.
        if not self._verificar_api_key():
            return

        ruta, _ = self._ruta_y_query()
        incidencia_id, error_id = self._extraer_id_incidencia(ruta)

        if error_id is not None:
            self._enviar_error_json(error_id)
            return

        datos, error = self._leer_json_cuerpo()
        if error is not None:
            self._enviar_error_json(error)
            return

        almacen = self._obtener_almacen()
        try:
            actualizada = almacen.actualizar_estado(
                incidencia_id, datos.get("estado")
            )
        except ValueError as exc:
            self._enviar_json(400, {"error": str(exc)})
            return

        if actualizada is None:
            self._enviar_json(404, {"error": "Incidencia no encontrada"})
            return

        self._enviar_json(200, actualizada)

    def do_PUT(self):
        # F7: Reemplazar completamente una incidencia.
        if not self._verificar_api_key():
            return

        ruta, _ = self._ruta_y_query()
        incidencia_id, error_id = self._extraer_id_incidencia(ruta)

        if error_id is not None:
            self._enviar_error_json(error_id)
            return

        datos, error = self._leer_json_cuerpo()
        if error is not None:
            self._enviar_error_json(error)
            return

        almacen = self._obtener_almacen()
        try:
            reemplazada = almacen.reemplazar_incidencia(
                incidencia_id,
                datos.get("tipo"),
                datos.get("descripcion")
            )
        except ValueError as exc:
            self._enviar_json(400, {"error": str(exc)})
            return

        if reemplazada is None:
            self._enviar_json(404, {"error": "Incidencia no encontrada"})
            return

        self._enviar_json(200, reemplazada)


    def do_DELETE(self):
        # F8: Eliminar una incidencia por su ID.
        if not self._verificar_api_key():
            return

        ruta, _ = self._ruta_y_query()
        incidencia_id, error_id = self._extraer_id_incidencia(ruta)

        if error_id is not None:
            self._enviar_error_json(error_id)
            return

        eliminada = self._obtener_almacen().eliminar_incidencia(incidencia_id)

        if not eliminada:
            self._enviar_json(404, {"error": "Incidencia no encontrada"})
            return

        self._enviar_sin_contenido(204)

    def manejar_get_auditoria(self):
        # F8: Consultar registros, contadores y alertas.
        if not self._verificar_api_key():
            return

        ruta, _ = self._ruta_y_query()
        almacen = self._obtener_almacen()

        if ruta == "/logs":
            self._enviar_json(200, almacen.obtener_logs())

        elif ruta == "/contadores":
            self._enviar_json(200, almacen.obtener_contadores())

        elif ruta == "/alertas":
            self._enviar_json(200, almacen.cargar_alertas())

        else:
            self._enviar_json(404, {"error": "Ruta no encontrada"})