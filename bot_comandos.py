"""F3 (mejora) - Bot de Telegram con comandos para el administrador (Eddi Michael).

Un hilo en segundo plano hace long polling a getUpdates (solo conexiones
salientes: no hay que abrir puertos). Solo responde a los chat_id autorizados.

Comandos: /estado /incidencias /contadores /alertas /ayuda
"""

import sys
import threading
import time
from datetime import datetime

import requests

from notificador_telegram import API

MAX_TEXTO = 4000  # Telegram admite 4096 caracteres por mensaje

AYUDA = (
    "Comandos disponibles:\n"
    "/estado - estado general del servidor\n"
    "/incidencias - resumen y ultimas abiertas\n"
    "/contadores - peticiones por metodo y familia\n"
    "/alertas - ultimas alertas enviadas\n"
    "/ayuda - esta lista"
)


class ErrorTelegram(Exception):
    def __init__(self, codigo):
        super().__init__("Telegram respondio HTTP %d" % codigo)
        self.codigo = codigo


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
        comando = texto.strip().split()[0].lower().split("@")[0] if texto.strip() else ""
        manejadores = {
            "/start": lambda: AYUDA,
            "/ayuda": lambda: AYUDA,
            "/estado": self._estado,
            "/incidencias": self._incidencias,
            "/contadores": self._contadores,
            "/alertas": self._alertas,
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
        return (
            "SERVIDOR: ACTIVO\n"
            "Uptime: %s\n"
            "Escucha: puerto %s (%s)\n"
            "Incidencias: %d abiertas, %d en proceso, %d resueltas\n"
            "Peticiones: %d (2xx: %d, 4xx: %d, 5xx: %d)\n"
            "Rechazos TLS recientes: %d\n"
            "Hora: %s"
            % (
                _formatear_uptime(time.time() - self.inicio),
                self.info_servidor.get("puerto", "?"),
                self.info_servidor.get("tls", "HTTPS/TLS"),
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
    # Comunicacion con Telegram
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
