"""F1 - Servidor concurrente sobre HTTPS/TLS y monitor de umbrales (Eddi Michael).

ThreadingHTTPServer con handshake TLS por hilo: un cliente lento o que envia
HTTP plano no bloquea a los demas y el rechazo queda en /logs.
Incluye MonitorRecursosServidor (cada 30s) para vigilar CPU, RAM, disco y
alteraciones de seguridad, guardando evidencia en SQLite/JSON y alertando a Telegram.
"""

import os
import shutil
import socket
import ssl
import sys
import threading
import time
from http.server import ThreadingHTTPServer

import config
from almacen import AlmacenBitacora
from manejador_http import ManejadorBitacora
from notificador_telegram import BotComandos, NotificadorTelegram


def _leer_tiempos_cpu():
    with open("/proc/stat", "r", encoding="utf-8") as archivo:
        partes = archivo.readline().split()
    valores = [int(v) for v in partes[1:]]
    idle = valores[3] + (valores[4] if len(valores) > 4 else 0)
    return sum(valores), idle


def _leer_memoria_linux():
    info = {}
    with open("/proc/meminfo", "r", encoding="utf-8") as archivo:
        for linea in archivo:
            clave, resto = linea.split(":", 1)
            info[clave] = int(resto.strip().split()[0])
    total_kb = info["MemTotal"]
    disponible_kb = info.get(
        "MemAvailable",
        info.get("MemFree", 0) + info.get("Buffers", 0) + info.get("Cached", 0),
    )
    usada_kb = max(0, total_kb - disponible_kb)
    porcentaje = round(100.0 * usada_kb / total_kb, 1) if total_kb else 0.0
    return porcentaje, round(usada_kb / 1024.0, 1), round(total_kb / 1024.0, 1)


def obtener_metricas_sistema(intervalo_cpu=0.1, ruta_disco="/"):
    """Lee uso real de CPU (%), RAM (%) y disco (%) en Linux usando biblioteca estandar."""
    cpu_pct = 0.0
    try:
        total1, idle1 = _leer_tiempos_cpu()
        if intervalo_cpu > 0:
            time.sleep(intervalo_cpu)
        total2, idle2 = _leer_tiempos_cpu()
        delta_total = total2 - total1
        delta_idle = idle2 - idle1
        if delta_total > 0:
            cpu_pct = round(max(0.0, min(100.0, 100.0 * (1.0 - delta_idle / delta_total))), 1)
    except OSError:
        cpu_pct = 0.0

    ram_pct, ram_usada_mb, ram_total_mb = 0.0, 0.0, 0.0
    try:
        ram_pct, ram_usada_mb, ram_total_mb = _leer_memoria_linux()
    except (OSError, KeyError, ValueError):
        pass

    disco_pct = 0.0
    try:
        uso = shutil.disk_usage(ruta_disco)
        if uso.total:
            disco_pct = round(100.0 * uso.used / uso.total, 1)
    except OSError:
        pass

    return {
        "cpu_porcentaje": cpu_pct,
        "ram_porcentaje": ram_pct,
        "ram_usada_mb": ram_usada_mb,
        "ram_total_mb": ram_total_mb,
        "disco_porcentaje": disco_pct,
    }


class MonitorRecursosServidor:
    """Vigila cada N segundos CPU, RAM, disco y alteraciones de seguridad del servidor."""

    EVENTOS_ALTERACION = ("TLS_RECHAZADO", "API_KEY_RECHAZADA")

    def __init__(
        self,
        almacen,
        notificador,
        umbral_cpu=85,
        umbral_ram=85,
        umbral_disco=90,
        intervalo=30,
    ):
        self.almacen = almacen
        self.notificador = notificador
        self.umbral_cpu = umbral_cpu
        self.umbral_ram = umbral_ram
        self.umbral_disco = umbral_disco
        self.intervalo = intervalo
        self._ultimo_id_log = 0
        self._detener = threading.Event()
        self._hilo = None

    def _hay_incidencia_abierta(self, prefijo):
        for inc in self.almacen.listar_incidencias(estado="abierta"):
            if str(inc.get("descripcion", "")).startswith(prefijo):
                return True
        return False

    def _registrar_y_alertar(self, tipo, descripcion):
        incidencia, lista = self.almacen.crear_incidencia(
            tipo, descripcion, origen="servidor-monitor"
        )
        if self.notificador is not None:
            self.notificador.evaluar_umbral_telegram(incidencia, lista)
        return incidencia

    def evaluar_una_vez(self, metricas=None):
        """Evalua recursos y alteraciones de seguridad; registra y alerta si superan umbral."""
        datos = metricas if metricas is not None else obtener_metricas_sistema(intervalo_cpu=0.1)
        creadas = []

        reglas = (
            (
                "cpu_porcentaje",
                self.umbral_cpu,
                "incidente",
                "Uso critico de CPU en servidor:",
            ),
            (
                "ram_porcentaje",
                self.umbral_ram,
                "incidente",
                "Uso critico de memoria RAM en servidor:",
            ),
            (
                "disco_porcentaje",
                self.umbral_disco,
                "alerta",
                "Espacio en disco critico en servidor:",
            ),
        )
        for clave, umbral, tipo, prefijo in reglas:
            valor = datos.get(clave)
            if valor is None or valor < umbral:
                continue
            if self._hay_incidencia_abierta(prefijo):
                continue
            descripcion = "%s %.1f%% (supera umbral de %d%%)" % (prefijo, float(valor), umbral)
            creadas.append(self._registrar_y_alertar(tipo, descripcion))

        logs = self.almacen.obtener_logs()
        nuevos_rechazos = 0
        max_id = self._ultimo_id_log
        for entrada in logs:
            id_log = entrada.get("id_log", 0)
            if id_log <= self._ultimo_id_log:
                continue
            if id_log > max_id:
                max_id = id_log
            if entrada.get("tipo") in self.EVENTOS_ALTERACION:
                nuevos_rechazos += 1
        self._ultimo_id_log = max_id

        if nuevos_rechazos > 0:
            descripcion = (
                "Alteracion de seguridad en servidor: %d intento(s) de acceso rechazados (TLS/API-Key)"
                % nuevos_rechazos
            )
            creadas.append(self._registrar_y_alertar("incidente", descripcion))

        return creadas

    def _bucle(self):
        while not self._detener.wait(self.intervalo):
            try:
                self.evaluar_una_vez()
            except Exception as exc:
                print("[monitor] Error en evaluacion de recursos (%s)" % type(exc).__name__, file=sys.stderr)

    def iniciar(self):
        self._hilo = threading.Thread(target=self._bucle, name="monitor-recursos", daemon=True)
        self._hilo.start()

    def detener(self):
        self._detener.set()


def crear_contexto_tls(ruta_certificado, ruta_llave):
    contexto = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    contexto.minimum_version = ssl.TLSVersion.TLSv1_2
    contexto.load_cert_chain(certfile=ruta_certificado, keyfile=ruta_llave)
    return contexto


class ServidorBitacoraHTTPS(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    timeout_handshake = 10

    def __init__(
        self,
        direccion,
        almacen,
        notificador,
        contexto_tls,
        manejador=ManejadorBitacora,
        api_keys=None,
    ):
        self.almacen = almacen
        self.notificador = notificador
        self.contexto_tls = contexto_tls
        self.api_keys = set(api_keys or ())
        self.obtener_metricas = obtener_metricas_sistema
        super().__init__(direccion, manejador)

    def process_request_thread(self, request, client_address):
        """Handshake TLS dentro del hilo del cliente (no bloquea el accept)."""
        try:
            request.settimeout(self.timeout_handshake)
            conexion = self.contexto_tls.wrap_socket(request, server_side=True)
        except (ssl.SSLError, OSError) as exc:
            motivo = getattr(exc, "reason", None) or type(exc).__name__
            self.almacen.registrar_evento(
                "TLS_RECHAZADO", client_address[0], "Handshake TLS fallido (%s)" % motivo
            )
            self.shutdown_request(request)
            return
        super().process_request_thread(conexion, client_address)

    def handle_error(self, request, client_address):
        # Errores de socket esperados (desconexiones) no deben ensuciar la consola.
        if isinstance(sys.exc_info()[1], (OSError, ssl.SSLError)):
            return
        super().handle_error(request, client_address)


def main():
    for ruta in (config.RUTA_CERTIFICADO, config.RUTA_LLAVE):
        try:
            open(ruta, "rb").close()
        except OSError:
            print("No se encontro %s. Ejecuta: python3 scripts/generar_certificados.py" % ruta, file=sys.stderr)
            return 1
    try:
        contexto = crear_contexto_tls(config.RUTA_CERTIFICADO, config.RUTA_LLAVE)
    except (ssl.SSLError, OSError) as exc:
        print("Certificado o llave invalidos: %s" % exc, file=sys.stderr)
        return 1

    almacen = AlmacenBitacora(config.RUTA_INCIDENCIAS, config.RUTA_ALERTAS)
    notificador = NotificadorTelegram(
        config.TELEGRAM_BOT_TOKEN,
        config.TELEGRAM_CHAT_ID,
        almacen,
        umbral=config.UMBRAL_ABIERTAS,
        timeout=config.TELEGRAM_TIMEOUT,
    )
    try:
        servidor = ServidorBitacoraHTTPS(
            (config.HOST, config.PUERTO),
            almacen,
            notificador,
            contexto,
            api_keys=config.API_KEYS,
        )
    except OSError as exc:
        print("No se pudo abrir %s:%d (%s)" % (config.HOST, config.PUERTO, exc), file=sys.stderr)
        return 1

    credenciales = "activo" if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID else "SIN credenciales"
    bot = None
    if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID and config.BOT_COMANDOS:
        bot = BotComandos(
            config.TELEGRAM_BOT_TOKEN,
            config.ADMIN_CHAT_IDS,
            almacen,
            info_servidor={
                "puerto": config.PUERTO,
                "tls": "HTTPS/TLS, minimo TLS 1.2",
                "obtener_metricas": obtener_metricas_sistema,
            },
        )
        bot.iniciar()

    monitor = None
    if config.MONITOR_SERVIDOR:
        monitor = MonitorRecursosServidor(
            almacen,
            notificador,
            umbral_cpu=config.UMBRAL_CPU,
            umbral_ram=config.UMBRAL_RAM,
            umbral_disco=config.UMBRAL_DISCO,
            intervalo=config.INTERVALO_MONITOR,
        )
        monitor.iniciar()

    print(
        "Bitacora HTTPS escuchando en https://%s:%d (Telegram: %s, bot: %s, monitor %ds: %s)"
        % (
            config.HOST,
            config.PUERTO,
            credenciales,
            "activos" if bot else "desactivados",
            config.INTERVALO_MONITOR,
            "activo" if monitor else "desactivado",
        )
    )
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nDeteniendo servidor...")
    finally:
        if monitor:
            monitor.detener()
        if bot:
            bot.detener()
        servidor.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
