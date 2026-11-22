"""F3 (Extra) - Motor de umbrales y Bot de Telegram (Eddi Michael).

Incluye:
- NotificadorTelegram: evaluacion de umbrales y envio push (timeout=5) con
  bitacora en SQLite + alertas_telegram.json.
- BotComandos: hilo de long polling (getUpdates) con lista blanca
  (ADMIN_CHAT_IDS) y comandos /estado, /incidencias, /dia, /fecha,
  /contadores, /alertas y /ayuda.

Uso manual:
    python3 notificador_telegram.py --verificar   # getMe
    python3 notificador_telegram.py --prueba      # sendMessage de prueba
"""

import argparse
import re
import sys
import threading
import time
import unicodedata
from datetime import datetime, timedelta

import requests

import config

TIPOS_CRITICOS = ("incidente", "incidente_critico")
API = "https://api.telegram.org/bot%s/%s"
MAX_TEXTO = 4000  # Telegram admite 4096 caracteres por mensaje
DIAS_SEMANA = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")

AYUDA = (
    "Comandos disponibles:\n"
    "/estado - estado general del servidor\n"
    "/incidencias - resumen y ultimas abiertas\n"
    "/dia <dia|fecha> - reporte de un dia (ej. /dia miercoles, /dia ayer, /dia 2026-11-18)\n"
    "/contadores - peticiones por metodo y familia\n"
    "/alertas - ultimas alertas enviadas\n"
    "/ayuda - esta lista"
)


class ErrorTelegram(Exception):
    def __init__(self, codigo):
        super().__init__("Telegram respondio HTTP %d" % codigo)
        self.codigo = codigo


def _normalizar_texto(texto):
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFD", str(texto)) if unicodedata.category(c) != "Mn"
    )
    return sin_acentos.strip().lower()


def resolver_fecha_dia(argumento, referencia=None):
    """Resuelve 'hoy', 'ayer', dia de la semana o 'YYYY-MM-DD' -> (fecha_iso, nombre_dia)."""
    ref = referencia or datetime.now().astimezone().date()
    limpio = _normalizar_texto(argumento)
    if not limpio or limpio == "hoy":
        fecha = ref
    elif limpio == "ayer":
        fecha = ref - timedelta(days=1)
    elif limpio in DIAS_SEMANA:
        objetivo = DIAS_SEMANA.index(limpio)
        retroceso = (ref.weekday() - objetivo) % 7
        fecha = ref - timedelta(days=retroceso)
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", limpio):
        fecha = datetime.strptime(limpio, "%Y-%m-%d").date()
    else:
        raise ValueError("Formato de fecha no reconocido: %s" % argumento)
    return fecha.isoformat(), DIAS_SEMANA[fecha.weekday()]


def _formatear_uptime(segundos):
    segundos = int(segundos)
    horas, resto = divmod(segundos, 3600)
    minutos, seg = divmod(resto, 60)
    if horas:
        return "%dh %02dm %02ds" % (horas, minutos, seg)
    return "%dm %02ds" % (minutos, seg)


def _recortar(texto, largo=60):
    texto = " ".join(str(texto).split())
    return texto if len(texto) <= largo else texto[: largo - 3] + "..."


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


class BotComandos:
    def __init__(self, token, admin_ids, almacen, info_servidor=None, espera_poll=25):
        self.token = token
        self.admin_ids = {str(i) for i in admin_ids if str(i).strip()}
        self.almacen = almacen
        self.info_servidor = info_servidor or {}
        self.espera_poll = espera_poll
        self.inicio = time.time()
        self.ultimo_error = None
        self._offset = None
        self._detener = threading.Event()
        self._hilo = None

    # ------------------------------------------------------------------
    # Respuestas a comandos (logica pura, facil de probar)
    # ------------------------------------------------------------------
    def procesar_comando(self, texto):
        partes = texto.strip().split(maxsplit=1)
        comando = partes[0].lower().split("@")[0] if partes else ""
        argumento = partes[1] if len(partes) > 1 else ""
        manejadores = {
            "/start": lambda: AYUDA,
            "/ayuda": lambda: AYUDA,
            "/estado": self._estado,
            "/incidencias": self._incidencias,
            "/contadores": self._contadores,
            "/alertas": self._alertas,
            "/dia": lambda: self._reporte_dia(argumento),
            "/fecha": lambda: self._reporte_dia(argumento),
        }
        manejador = manejadores.get(comando)
        if manejador is None:
            return "Comando no reconocido. Usa /ayuda."
        try:
            return manejador()[:MAX_TEXTO]
        except Exception as exc:
            return "Error interno al consultar (%s)." % type(exc).__name__

    def _conteo_estados(self):
        conteo = {"abierta": 0, "en_proceso": 0, "resuelta": 0}
        for incidencia in self.almacen.listar_incidencias():
            estado = incidencia.get("estado")
            conteo[estado] = conteo.get(estado, 0) + 1
        return conteo

    def _estado(self):
        c = self.almacen.obtener_contadores()
        fam = c["por_familia"]
        e = self._conteo_estados()
        rechazos = sum(1 for l in self.almacen.obtener_logs() if l.get("tipo") == "TLS_RECHAZADO")
        linea_recursos = ""
        obtener_metricas = self.info_servidor.get("obtener_metricas")
        if callable(obtener_metricas):
            try:
                m = obtener_metricas(intervalo_cpu=0.05)
                linea_recursos = "Recursos: CPU %.1f%% | RAM %.1f%% | Disco %.1f%%\n" % (
                    m.get("cpu_porcentaje", 0.0),
                    m.get("ram_porcentaje", 0.0),
                    m.get("disco_porcentaje", 0.0),
                )
            except Exception:
                linea_recursos = ""
        return (
            "SERVIDOR: ACTIVO\n"
            "Uptime: %s\n"
            "Escucha: puerto %s (%s)\n"
            "%s"
            "Incidencias: %d abiertas, %d en proceso, %d resueltas\n"
            "Peticiones: %d (2xx: %d, 4xx: %d, 5xx: %d)\n"
            "Rechazos TLS recientes: %d\n"
            "Hora: %s"
            % (
                _formatear_uptime(time.time() - self.inicio),
                self.info_servidor.get("puerto", "?"),
                self.info_servidor.get("tls", "HTTPS/TLS"),
                linea_recursos,
                e["abierta"], e["en_proceso"], e["resuelta"],
                c["total"], fam.get("2xx", 0), fam.get("4xx", 0), fam.get("5xx", 0),
                rechazos,
                datetime.now().astimezone().isoformat(timespec="seconds"),
            )
        )

    def _incidencias(self):
        e = self._conteo_estados()
        lineas = [
            "Incidencias: %d abiertas, %d en proceso, %d resueltas"
            % (e["abierta"], e["en_proceso"], e["resuelta"])
        ]
        abiertas = self.almacen.listar_incidencias(estado="abierta")[-5:]
        if abiertas:
            lineas.append("\nUltimas abiertas:")
            for i in reversed(abiertas):
                lineas.append("#%s [%s] %s" % (i["id"], i["tipo"], _recortar(i["descripcion"])))
        else:
            lineas.append("\nNo hay incidencias abiertas.")
        return "\n".join(lineas)

    def _reporte_dia(self, argumento):
        try:
            fecha_iso, nombre_dia = resolver_fecha_dia(argumento)
        except ValueError:
            return "Formato invalido. Usa por ejemplo: /dia miercoles, /dia hoy, /dia ayer o /dia 2026-11-18"

        resumen = self.almacen.resumen_por_fecha(fecha_iso)
        lineas = ["Reporte del %s (%s) [SQLite indexado]" % (nombre_dia, fecha_iso)]
        if resumen["total"] == 0 and resumen["total_alertas"] == 0:
            lineas.append("Sin incidencias ni alertas registradas ese dia.")
            return "\n".join(lineas)

        e = resumen["por_estado"]
        lineas.append(
            "Incidencias: %d total (%d abiertas, %d en proceso, %d resueltas)"
            % (resumen["total"], e.get("abierta", 0), e.get("en_proceso", 0), e.get("resuelta", 0))
        )
        if resumen["por_tipo"]:
            tipos = ", ".join("%s: %d" % (t, n) for t, n in sorted(resumen["por_tipo"].items()))
            lineas.append("Por tipo: %s" % tipos)
        lineas.append("Alertas Telegram enviadas: %d" % resumen["total_alertas"])
        if resumen["incidencias"]:
            lineas.append("\nRegistros de ese dia:")
            for i in resumen["incidencias"][:5]:
                lineas.append(
                    "#%s [%s] (%s) %s"
                    % (i["id"], i["tipo"], i["estado"], _recortar(i["descripcion"]))
                )
        return "\n".join(lineas)

    def _contadores(self):
        c = self.almacen.obtener_contadores()
        if not c["total"]:
            return "Aun no hay peticiones registradas."
        lineas = ["Peticiones totales: %d" % c["total"], "\nPor metodo:"]
        lineas += ["%s: %d" % (m, n) for m, n in sorted(c["por_metodo"].items())]
        lineas.append("\nPor familia:")
        lineas += ["%s: %d" % (f, n) for f, n in sorted(c["por_familia"].items())]
        return "\n".join(lineas)

    def _alertas(self):
        alertas = self.almacen.cargar_alertas()[-5:]
        if not alertas:
            return "Aun no se han enviado alertas."
        lineas = ["Ultimas alertas:"]
        for a in reversed(alertas):
            lineas.append(
                "#%s %s - incidencia %s - %s - %s"
                % (a.get("id_alerta"), a.get("hora"), a.get("incidencia_id"), a.get("motivo"), a.get("estado_envio"))
            )
        return "\n".join(lineas)

    # ------------------------------------------------------------------
    # Comunicacion con Telegram (long polling)
    # ------------------------------------------------------------------
    def _consultar(self, offset, espera):
        parametros = {"timeout": espera, "allowed_updates": '["message"]'}
        if offset is not None:
            parametros["offset"] = offset
        r = requests.get(API % (self.token, "getUpdates"), params=parametros, timeout=espera + 10)
        if r.status_code != 200:
            raise ErrorTelegram(r.status_code)
        return r.json().get("result", [])

    def _enviar(self, chat_id, texto):
        try:
            requests.post(
                API % (self.token, "sendMessage"),
                json={"chat_id": chat_id, "text": texto},
                timeout=10,
            )
        except requests.RequestException:
            pass  # el administrador puede reintentar el comando

    def _descartar_pendientes(self):
        """Ignora mensajes viejos acumulados mientras el servidor estaba apagado."""
        pendientes = self._consultar(-1, 0)
        if pendientes:
            self._offset = pendientes[-1]["update_id"] + 1

    def _procesar_actualizacion(self, actualizacion):
        mensaje = actualizacion.get("message")
        if not mensaje:
            return
        chat_id = str(mensaje.get("chat", {}).get("id", ""))
        texto = mensaje.get("text") or ""
        if chat_id not in self.admin_ids:
            self.almacen.registrar_evento("BOT_NO_AUTORIZADO", chat_id, "Mensaje ignorado de chat no autorizado")
            return
        if not texto.startswith("/"):
            self._enviar(chat_id, "Usa /ayuda para ver los comandos.")
            return
        self._enviar(chat_id, self.procesar_comando(texto))

    def ciclo_una_vez(self):
        """Una consulta a getUpdates y procesamiento de lo recibido."""
        for actualizacion in self._consultar(self._offset, self.espera_poll):
            self._offset = actualizacion["update_id"] + 1
            self._procesar_actualizacion(actualizacion)

    # ------------------------------------------------------------------
    # Hilo en segundo plano
    # ------------------------------------------------------------------
    def _bucle(self):
        espera_error = 5
        inicializado = False
        while not self._detener.is_set():
            try:
                if not inicializado:
                    self._descartar_pendientes()
                    inicializado = True
                self.ciclo_una_vez()
                self.ultimo_error = None
                espera_error = 5
            except (requests.RequestException, ValueError, ErrorTelegram) as exc:
                if isinstance(exc, ErrorTelegram) and exc.codigo == 409:
                    aviso = "Otro proceso usa getUpdates con este mismo token (409)"
                else:
                    aviso = type(exc).__name__ if not isinstance(exc, ErrorTelegram) else str(exc)
                if aviso != self.ultimo_error:  # evita llenar la consola
                    print("[bot] %s; reintentando en %ds" % (aviso, espera_error), file=sys.stderr)
                self.ultimo_error = aviso
                self._detener.wait(espera_error)
                espera_error = min(espera_error * 2, 60)

    def iniciar(self):
        self._hilo = threading.Thread(target=self._bucle, name="bot-comandos", daemon=True)
        self._hilo.start()

    def detener(self):
        self._detener.set()


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
