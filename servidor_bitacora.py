"""F1 - Servidor concurrente sobre HTTPS/TLS (Eddi Michael).

ThreadingHTTPServer con handshake TLS por hilo: un cliente lento o que envia
HTTP plano no bloquea a los demas y el rechazo queda en /logs.
"""

import socket
import ssl
import sys
from http.server import ThreadingHTTPServer

import config
from almacen import AlmacenBitacora
from manejador_http import ManejadorBitacora
from notificador_telegram import BotComandos, NotificadorTelegram


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
            info_servidor={"puerto": config.PUERTO, "tls": "HTTPS/TLS, minimo TLS 1.2"},
        )
        bot.iniciar()
    print(
        "Bitacora HTTPS escuchando en https://%s:%d (Telegram: %s, comandos del bot: %s)"
        % (config.HOST, config.PUERTO, credenciales, "activos" if bot else "desactivados")
    )
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nDeteniendo servidor...")
    finally:
        if bot:
            bot.detener()
        servidor.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
