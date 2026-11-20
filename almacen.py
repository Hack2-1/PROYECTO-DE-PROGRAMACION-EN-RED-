"""F2 - Persistencia concurrente en JSON con candado (Eddi Michael).

Almacen D1 (incidencias.json), bitacora de Telegram (alertas_telegram.json)
y auditoria en memoria (logs y contadores HTTP).
"""

import json
import os
import threading
import time
from collections import deque
from datetime import datetime

ESTADOS_VALIDOS = ("abierta", "en_proceso", "resuelta")
MAX_LOGS = 1000


def _ahora():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _familia(codigo):
    if 200 <= codigo < 300:
        return "2xx"
    if 400 <= codigo < 500:
        return "4xx"
    if 500 <= codigo < 600:
        return "5xx"
    return "otros"


def _texto_obligatorio(valor, campo):
    if not isinstance(valor, str) or not valor.strip():
        raise ValueError("El campo '%s' es obligatorio y no puede estar vacio" % campo)
    return valor.strip()


def _validar_estado(estado):
    if estado not in ESTADOS_VALIDOS:
        raise ValueError(
            "Estado invalido: debe ser uno de %s" % ", ".join(ESTADOS_VALIDOS)
        )
    return estado


class AlmacenBitacora:
    def __init__(self, ruta_incidencias="incidencias.json", ruta_alertas="alertas_telegram.json"):
        self.ruta_incidencias = ruta_incidencias
        self.ruta_alertas = ruta_alertas
        self._lock = threading.Lock()          # incidencias.json
        self._lock_alertas = threading.Lock()  # alertas_telegram.json
        self._lock_auditoria = threading.Lock()  # logs y contadores
        self._incidencias = []
        self._siguiente_id = 1
        self._logs = deque(maxlen=MAX_LOGS)
        self._id_log = 0
        self._contadores = {"total": 0, "por_metodo": {}, "por_familia": {}, "por_metodo_familia": {}}
        self.cargar()

    # ------------------------------------------------------------------
    # Persistencia
    # ------------------------------------------------------------------
    @staticmethod
    def _escribir_atomico(ruta, datos):
        temporal = "%s.tmp.%d.%d" % (ruta, os.getpid(), threading.get_ident())
        try:
            with open(temporal, "w", encoding="utf-8") as archivo:
                json.dump(datos, archivo, ensure_ascii=False, indent=2)
                archivo.flush()
                os.fsync(archivo.fileno())
            os.replace(temporal, ruta)
        finally:
            if os.path.exists(temporal):
                os.remove(temporal)

    @staticmethod
    def _leer_json(ruta):
        """Lee un JSON; si esta corrupto lo aparta y devuelve None."""
        if not os.path.exists(ruta):
            return None
        try:
            with open(ruta, "r", encoding="utf-8") as archivo:
                return json.load(archivo)
        except (json.JSONDecodeError, UnicodeDecodeError):
            os.replace(ruta, "%s.corrupto-%d" % (ruta, int(time.time())))
            return None

    def cargar(self):
        """Carga incidencias.json (objeto con siguiente_id o lista directa)."""
        with self._lock:
            datos = self._leer_json(self.ruta_incidencias)
            declarado = 1
            if isinstance(datos, dict):
                lista = datos.get("incidencias", [])
                declarado = datos.get("siguiente_id", 1)
            elif isinstance(datos, list):
                lista = datos
            else:
                lista = []
            lista = [i for i in lista if isinstance(i, dict) and isinstance(i.get("id"), int)]
            maximo = max((i["id"] for i in lista), default=0)
            if not isinstance(declarado, int):
                declarado = 1
            self._incidencias = lista
            self._siguiente_id = max(declarado, maximo + 1)

    def _guardar_sin_lock(self):
        self._escribir_atomico(
            self.ruta_incidencias,
            {"siguiente_id": self._siguiente_id, "incidencias": self._incidencias},
        )

    def guardar(self):
        with self._lock:
            self._guardar_sin_lock()

    # ------------------------------------------------------------------
    # Incidencias (contrato docs/CONTRATO_API.md, seccion 3.1)
    # ------------------------------------------------------------------
    def crear_incidencia(self, tipo, descripcion, estado="abierta", origen=None):
        tipo = _texto_obligatorio(tipo, "tipo")
        descripcion = _texto_obligatorio(descripcion, "descripcion")
        estado = _validar_estado(estado)
        with self._lock:
            incidencia = {
                "id": self._siguiente_id,
                "tipo": tipo,
                "descripcion": descripcion,
                "estado": estado,
                "hora": _ahora(),
            }
            if origen:
                incidencia["origen"] = str(origen)
            self._incidencias.append(incidencia)
            self._siguiente_id += 1
            self._guardar_sin_lock()
            return dict(incidencia), [dict(i) for i in self._incidencias]

    def listar_incidencias(self, tipo=None, estado=None):
        with self._lock:
            return [
                dict(i)
                for i in self._incidencias
                if (not tipo or i.get("tipo") == tipo)
                and (not estado or i.get("estado") == estado)
            ]

    def _buscar(self, incidencia_id):
        for incidencia in self._incidencias:
            if incidencia["id"] == incidencia_id:
                return incidencia
        return None

    def obtener_incidencia(self, incidencia_id):
        with self._lock:
            encontrada = self._buscar(incidencia_id)
            return dict(encontrada) if encontrada else None

    def actualizar_estado(self, incidencia_id, nuevo_estado):
        _validar_estado(nuevo_estado)
        with self._lock:
            encontrada = self._buscar(incidencia_id)
            if encontrada is None:
                return None
            encontrada["estado"] = nuevo_estado
            self._guardar_sin_lock()
            return dict(encontrada)

    def reemplazar_incidencia(self, incidencia_id, tipo, descripcion):
        tipo = _texto_obligatorio(tipo, "tipo")
        descripcion = _texto_obligatorio(descripcion, "descripcion")
        with self._lock:
            encontrada = self._buscar(incidencia_id)
            if encontrada is None:
                return None
            encontrada.update({"tipo": tipo, "descripcion": descripcion, "estado": "abierta"})
            self._guardar_sin_lock()
            return dict(encontrada)

    def eliminar_incidencia(self, incidencia_id):
        with self._lock:
            encontrada = self._buscar(incidencia_id)
            if encontrada is None:
                return False
            self._incidencias.remove(encontrada)
            self._guardar_sin_lock()
            return True

    # ------------------------------------------------------------------
    # Bitacora de Telegram (alertas_telegram.json)
    # ------------------------------------------------------------------
    def cargar_alertas(self):
        with self._lock_alertas:
            datos = self._leer_json(self.ruta_alertas)
            return datos if isinstance(datos, list) else []

    def registrar_alerta(self, evento):
        """Agrega un evento asignandole id_alerta y hora; devuelve el evento."""
        with self._lock_alertas:
            datos = self._leer_json(self.ruta_alertas)
            alertas = datos if isinstance(datos, list) else []
            registro = {
                "id_alerta": max((a.get("id_alerta", 0) for a in alertas), default=0) + 1,
                "hora": _ahora(),
            }
            registro.update(evento)
            alertas.append(registro)
            self._escribir_atomico(self.ruta_alertas, alertas)
            return registro

    # ------------------------------------------------------------------
    # Auditoria en memoria (/logs y /contadores)
    # ------------------------------------------------------------------
    def registrar_peticion(self, metodo, ruta, codigo, cliente):
        familia = _familia(codigo)
        with self._lock_auditoria:
            self._id_log += 1
            self._logs.append(
                {
                    "id_log": self._id_log,
                    "hora": _ahora(),
                    "tipo": "HTTP",
                    "metodo": metodo,
                    "ruta": ruta,
                    "codigo": codigo,
                    "cliente": cliente,
                }
            )
            c = self._contadores
            c["total"] += 1
            c["por_metodo"][metodo] = c["por_metodo"].get(metodo, 0) + 1
            c["por_familia"][familia] = c["por_familia"].get(familia, 0) + 1
            fila = c["por_metodo_familia"].setdefault(metodo, {})
            fila[familia] = fila.get(familia, 0) + 1

    def registrar_evento(self, tipo, cliente, detalle):
        """Eventos no HTTP: TLS_RECHAZADO, CONEXION_INTERRUMPIDA..."""
        with self._lock_auditoria:
            self._id_log += 1
            self._logs.append(
                {
                    "id_log": self._id_log,
                    "hora": _ahora(),
                    "tipo": tipo,
                    "cliente": cliente,
                    "detalle": detalle,
                }
            )

    def obtener_logs(self):
        with self._lock_auditoria:
            return list(self._logs)

    def obtener_contadores(self):
        with self._lock_auditoria:
            c = self._contadores
            return {
                "total": c["total"],
                "por_metodo": dict(c["por_metodo"]),
                "por_familia": dict(c["por_familia"]),
                "por_metodo_familia": {m: dict(f) for m, f in c["por_metodo_familia"].items()},
            }
