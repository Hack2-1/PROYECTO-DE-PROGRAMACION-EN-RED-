"""Configuracion central: variables de entorno y archivo .env (sin dependencias)."""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _cargar_env(ruta):
    if not os.path.exists(ruta):
        return
    with open(ruta, "r", encoding="utf-8") as archivo:
        for linea in archivo:
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            clave, valor = linea.split("=", 1)
            clave = clave.strip()
            valor = valor.strip().strip('"').strip("'")
            os.environ.setdefault(clave, valor)  # el entorno real tiene prioridad


_cargar_env(os.path.join(BASE_DIR, ".env"))


def _entero(nombre, defecto):
    try:
        return int(os.environ.get(nombre, defecto))
    except ValueError:
        return defecto


def _ruta(nombre, defecto):
    ruta = os.environ.get(nombre, defecto)
    return ruta if os.path.isabs(ruta) else os.path.join(BASE_DIR, ruta)


HOST = os.environ.get("BITACORA_HOST", "0.0.0.0")
PUERTO = _entero("BITACORA_PORT", 8443)
RUTA_CERTIFICADO = _ruta("RUTA_CERTIFICADO", "certificado.pem")
RUTA_LLAVE = _ruta("RUTA_LLAVE", "llave.pem")
RUTA_INCIDENCIAS = _ruta("RUTA_INCIDENCIAS", "incidencias.json")
RUTA_ALERTAS = _ruta("RUTA_ALERTAS", "alertas_telegram.json")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_TIMEOUT = _entero("TELEGRAM_TIMEOUT", 5)
# Administradores autorizados a usar comandos (ids separados por coma); siempre incluye el chat id.
_crudos_admins = (
    os.environ.get("ADMIN_CHAT_IDS", "")
    + ","
    + os.environ.get("TELEGRAM_ADMIN_IDS", "")
    + ","
    + TELEGRAM_CHAT_ID
)
ADMIN_CHAT_IDS = {i.strip() for i in _crudos_admins.split(",") if i.strip()}
TELEGRAM_ADMIN_IDS = ADMIN_CHAT_IDS
API_KEYS = {k.strip() for k in os.environ.get("API_KEYS", "").split(",") if k.strip()}
BOT_COMANDOS = os.environ.get("BOT_COMANDOS", "1").strip() not in ("0", "false", "no")
UMBRAL_ABIERTAS = _entero("UMBRAL_ABIERTAS", 3)

# Monitoreo automatico por umbrales del servidor (cada INTERVALO_MONITOR segundos)
UMBRAL_CPU = _entero("UMBRAL_CPU", 85)
UMBRAL_RAM = _entero("UMBRAL_RAM", 85)
UMBRAL_DISCO = _entero("UMBRAL_DISCO", 90)
INTERVALO_MONITOR = _entero("INTERVALO_MONITOR", 30)
MONITOR_SERVIDOR = os.environ.get("MONITOR_SERVIDOR", "1").strip() not in ("0", "false", "no")
