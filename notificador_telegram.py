"""F3 (Extra) - Motor de umbrales y Bot de Telegram con bitacora (Eddi Michael).

Uso manual:
    python3 notificador_telegram.py --verificar   # getMe
    python3 notificador_telegram.py --prueba      # sendMessage de prueba
"""

import argparse
import sys

import requests

import config

TIPOS_CRITICOS = ("incidente", "incidente_critico")
API = "https://api.telegram.org/bot%s/%s"


class NotificadorTelegram:
    def __init__(self, token, chat_id, almacen, umbral=3, timeout=5):
        self.token = token
        self.chat_id = chat_id
        self.almacen = almacen
        self.umbral = umbral
        self.timeout = timeout

    def _motivo(self, incidencia_nueva, lista_incidencias):
        """Devuelve el motivo del umbral o None si queda bajo umbral."""
        if str(incidencia_nueva.get("tipo", "")).lower() in TIPOS_CRITICOS:
            return "UMBRAL_CRITICO_DIRECTO (1/1)"
        abiertas = sum(1 for i in lista_incidencias if i.get("estado") == "abierta")
        if abiertas >= self.umbral:
            return "UMBRAL_ACUMULACION (%d abiertas >= %d)" % (abiertas, self.umbral)
        return None

    @staticmethod
    def _texto(incidencia, motivo):
        return (
            "ALERTA DE RED - Incidencia #%s\n"
            "Tipo: %s\n"
            "Descripcion: %s\n"
            "Motivo: %s\n"
            "Hora: %s"
            % (
                incidencia.get("id"),
                incidencia.get("tipo"),
                incidencia.get("descripcion"),
                motivo,
                incidencia.get("hora"),
            )
        )

    def evaluar_umbral_telegram(self, incidencia_nueva, lista_incidencias):
        """Evalua el umbral y, si aplica, notifica y registra. Nunca lanza excepciones."""
        try:
            motivo = self._motivo(incidencia_nueva, lista_incidencias)
            if motivo is None:
                return {"alerta": False, "resultado": "BAJO_UMBRAL"}
            evento = {
                "incidencia_id": incidencia_nueva.get("id"),
                "tipo_incidencia": incidencia_nueva.get("tipo"),
                "motivo": motivo,
            }
            evento.update(self._enviar(self._texto(incidencia_nueva, motivo)))
            registro = self.almacen.registrar_alerta(evento)
            registro["alerta"] = True
            return registro
        except Exception as exc:  # el hilo HTTP jamas debe caerse por la alerta
            return {"alerta": False, "resultado": "ERROR_INTERNO", "detalle": type(exc).__name__}

    def _enviar(self, texto):
        if not self.token or not self.chat_id:
            return {
                "estado_envio": "SIN_CREDENCIALES",
                "codigo_http": None,
                "detalle": "Falta TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID en .env",
            }
        try:
            respuesta = requests.post(
                API % (self.token, "sendMessage"),
                json={"chat_id": self.chat_id, "text": texto},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            # Solo el nombre de la excepcion: el mensaje podria incluir el token en la URL.
            return {
                "estado_envio": "FALLIDO_SIN_INTERNET",
                "codigo_http": 503,
                "detalle": "Sin conexion con Telegram (%s)" % type(exc).__name__,
            }
        if respuesta.status_code == 200:
            return {
                "estado_envio": "ENVIADO",
                "codigo_http": 200,
                "detalle": "Notificacion entregada a Telegram",
            }
        return {
            "estado_envio": "ERROR_API",
            "codigo_http": respuesta.status_code,
            "detalle": "Telegram respondio con codigo %d" % respuesta.status_code,
        }


def _cli():
    parser = argparse.ArgumentParser(description="Utilidades del Bot de Telegram")
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--verificar", action="store_true", help="valida el token (getMe)")
    grupo.add_argument("--prueba", action="store_true", help="envia un mensaje de prueba")
    args = parser.parse_args()

    if not config.TELEGRAM_BOT_TOKEN:
        print("Falta TELEGRAM_BOT_TOKEN en .env", file=sys.stderr)
        return 1
    try:
        if args.verificar:
            resp = requests.get(API % (config.TELEGRAM_BOT_TOKEN, "getMe"), timeout=10)
            datos = resp.json()
            if resp.status_code == 200 and datos.get("ok"):
                print("Token valido. Bot: @%s" % datos["result"].get("username"))
                return 0
            print("Token rechazado por Telegram (HTTP %d)" % resp.status_code, file=sys.stderr)
            return 1
        if not config.TELEGRAM_CHAT_ID:
            print("Falta TELEGRAM_CHAT_ID en .env", file=sys.stderr)
            return 1
        resp = requests.post(
            API % (config.TELEGRAM_BOT_TOKEN, "sendMessage"),
            json={"chat_id": config.TELEGRAM_CHAT_ID, "text": "Prueba de la Bitacora de Incidencias (Equipo 01)"},
            timeout=10,
        )
        if resp.status_code == 200:
            print("Mensaje de prueba enviado.")
            return 0
        print("Telegram respondio HTTP %d: %s" % (resp.status_code, resp.text), file=sys.stderr)
        return 1
    except requests.RequestException as exc:
        print("No se pudo contactar a Telegram (%s)" % type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(_cli())
