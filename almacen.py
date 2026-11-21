"""F2 - Persistencia concurrente en SQLite indexado + JSON con candado (Eddi Michael).

Motor principal indexado SQLite (bitacora.db) con espejo JSON compatible
(incidencias.json y alertas_telegram.json) y auditoria en memoria.
"""

from contextlib import closing
import json
import os
import sqlite3
import threading
import time
from collections import deque
from datetime import datetime

ESTADOS_VALIDOS = ("abierta", "en_proceso", "resuelta")
MAX_LOGS = 1000


def _ahora():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _fecha_de_hora(hora):
    texto = str(hora or "").strip()
    return texto[:10] if len(texto) >= 10 else ""


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
    def __init__(
        self,
        ruta_incidencias="incidencias.json",
        ruta_alertas="alertas_telegram.json",
        ruta_db=None,
    ):
        self.ruta_incidencias = ruta_incidencias
        self.ruta_alertas = ruta_alertas
        if ruta_db is None:
            directorio = os.path.dirname(os.path.abspath(ruta_incidencias))
            self.ruta_db = os.path.join(directorio, "bitacora.db")
        else:
            self.ruta_db = ruta_db
        self._lock = threading.Lock()           # incidencias (JSON + SQLite)
        self._lock_alertas = threading.Lock()   # alertas_telegram (JSON + SQLite)
        self._lock_auditoria = threading.Lock() # logs y contadores en memoria
        self._lock_db = threading.Lock()        # serializa commits SQLite entre tablas
        self._incidencias = []
        self._siguiente_id = 1
        self._logs = deque(maxlen=MAX_LOGS)
        self._id_log = 0
        self._contadores = {"total": 0, "por_metodo": {}, "por_familia": {}, "por_metodo_familia": {}}
        self._inicializar_db()
        self.cargar()
        self._sincronizar_alertas_inicial()

    # ------------------------------------------------------------------
    # SQLite indexado (bitacora.db)
    # ------------------------------------------------------------------
    def _conectar_db(self):
        conn = sqlite3.connect(self.ruta_db, timeout=15.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _inicializar_db(self):
        directorio = os.path.dirname(os.path.abspath(self.ruta_db))
        if directorio:
            os.makedirs(directorio, exist_ok=True)
        with self._lock_db, closing(self._conectar_db()) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS incidencias (
                    id INTEGER PRIMARY KEY,
                    tipo TEXT NOT NULL,
                    descripcion TEXT NOT NULL,
                    estado TEXT NOT NULL,
                    hora TEXT NOT NULL,
                    fecha TEXT NOT NULL,
                    origen TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_incidencias_fecha ON incidencias(fecha);
                CREATE INDEX IF NOT EXISTS idx_incidencias_estado ON incidencias(estado);
                CREATE INDEX IF NOT EXISTS idx_incidencias_tipo ON incidencias(tipo);

                CREATE TABLE IF NOT EXISTS alertas_telegram (
                    id_alerta INTEGER PRIMARY KEY,
                    hora TEXT NOT NULL,
                    fecha TEXT NOT NULL,
                    incidencia_id INTEGER,
                    tipo_incidencia TEXT,
                    motivo TEXT,
                    estado_envio TEXT,
                    codigo_http INTEGER,
                    detalle TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_alertas_fecha ON alertas_telegram(fecha);
                """
            )
            conn.commit()

    def _sincronizar_incidencias_db(self):
        filas = [
            (
                i["id"],
                i.get("tipo", ""),
                i.get("descripcion", ""),
                i.get("estado", "abierta"),
                i.get("hora", ""),
                _fecha_de_hora(i.get("hora", "")),
                i.get("origen"),
            )
            for i in self._incidencias
        ]
        with self._lock_db, closing(self._conectar_db()) as conn:
            conn.execute("DELETE FROM incidencias")
            conn.executemany(
                """
                INSERT INTO incidencias (id, tipo, descripcion, estado, hora, fecha, origen)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                filas,
            )
            conn.commit()

    def _cargar_incidencias_desde_db(self):
        with self._lock_db, closing(self._conectar_db()) as conn:
            filas = conn.execute(
                "SELECT id, tipo, descripcion, estado, hora, origen FROM incidencias ORDER BY id ASC"
            ).fetchall()
        resultado = []
        for fila in filas:
            item = {
                "id": fila["id"],
                "tipo": fila["tipo"],
                "descripcion": fila["descripcion"],
                "estado": fila["estado"],
                "hora": fila["hora"],
            }
            if fila["origen"]:
                item["origen"] = fila["origen"]
            resultado.append(item)
        return resultado

    def _sincronizar_alertas_inicial(self):
        with self._lock_alertas:
            datos = self._leer_json(self.ruta_alertas)
            if not isinstance(datos, list) or not datos:
                return
            filas = [
                (
                    a.get("id_alerta"),
                    a.get("hora", ""),
                    _fecha_de_hora(a.get("hora", "")),
                    a.get("incidencia_id"),
                    a.get("tipo_incidencia"),
                    a.get("motivo"),
                    a.get("estado_envio"),
                    a.get("codigo_http"),
                    a.get("detalle"),
                )
                for a in datos
                if isinstance(a, dict) and isinstance(a.get("id_alerta"), int)
            ]
            if not filas:
                return
            with self._lock_db, closing(self._conectar_db()) as conn:
                conn.executemany(
                    """
                    INSERT OR IGNORE INTO alertas_telegram (
                        id_alerta, hora, fecha, incidencia_id, tipo_incidencia,
                        motivo, estado_envio, codigo_http, detalle
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    filas,
                )
                conn.commit()

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
        """Carga incidencias desde JSON (o SQLite si aun no hay JSON) y sincroniza."""
        with self._lock:
            archivo_existia = os.path.exists(self.ruta_incidencias)
            datos = self._leer_json(self.ruta_incidencias)
            declarado = 1
            if isinstance(datos, dict):
                lista = datos.get("incidencias", [])
                declarado = datos.get("siguiente_id", 1)
            elif isinstance(datos, list):
                lista = datos
            elif not archivo_existia:
                lista = self._cargar_incidencias_desde_db()
            else:
                lista = []
            lista = [i for i in lista if isinstance(i, dict) and isinstance(i.get("id"), int)]
            maximo = max((i["id"] for i in lista), default=0)
            if not isinstance(declarado, int):
                declarado = 1
            self._incidencias = lista
            self._siguiente_id = max(declarado, maximo + 1)
            self._sincronizar_incidencias_db()
            if not archivo_existia and lista:
                self._escribir_atomico(
                    self.ruta_incidencias,
                    {"siguiente_id": self._siguiente_id, "incidencias": self._incidencias},
                )

    def _guardar_json_sin_lock(self):
        self._escribir_atomico(
            self.ruta_incidencias,
            {"siguiente_id": self._siguiente_id, "incidencias": self._incidencias},
        )

    def _guardar_sin_lock(self):
        self._sincronizar_incidencias_db()
        self._guardar_json_sin_lock()

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
            hora = _ahora()
            incidencia = {
                "id": self._siguiente_id,
                "tipo": tipo,
                "descripcion": descripcion,
                "estado": estado,
                "hora": hora,
            }
            if origen:
                incidencia["origen"] = str(origen)
            with self._lock_db, closing(self._conectar_db()) as conn:
                conn.execute(
                    """
                    INSERT INTO incidencias (id, tipo, descripcion, estado, hora, fecha, origen)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        incidencia["id"],
                        tipo,
                        descripcion,
                        estado,
                        hora,
                        _fecha_de_hora(hora),
                        incidencia.get("origen"),
                    ),
                )
                conn.commit()
            self._incidencias.append(incidencia)
            self._siguiente_id += 1
            self._guardar_json_sin_lock()
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
            with self._lock_db, closing(self._conectar_db()) as conn:
                conn.execute(
                    "UPDATE incidencias SET estado = ? WHERE id = ?",
                    (nuevo_estado, incidencia_id),
                )
                conn.commit()
            encontrada["estado"] = nuevo_estado
            self._guardar_json_sin_lock()
            return dict(encontrada)

    def reemplazar_incidencia(self, incidencia_id, tipo, descripcion):
        tipo = _texto_obligatorio(tipo, "tipo")
        descripcion = _texto_obligatorio(descripcion, "descripcion")
        with self._lock:
            encontrada = self._buscar(incidencia_id)
            if encontrada is None:
                return None
            with self._lock_db, closing(self._conectar_db()) as conn:
                conn.execute(
                    "UPDATE incidencias SET tipo = ?, descripcion = ?, estado = 'abierta' WHERE id = ?",
                    (tipo, descripcion, incidencia_id),
                )
                conn.commit()
            encontrada.update({"tipo": tipo, "descripcion": descripcion, "estado": "abierta"})
            self._guardar_json_sin_lock()
            return dict(encontrada)

    def eliminar_incidencia(self, incidencia_id):
        with self._lock:
            encontrada = self._buscar(incidencia_id)
            if encontrada is None:
                return False
            with self._lock_db, closing(self._conectar_db()) as conn:
                conn.execute("DELETE FROM incidencias WHERE id = ?", (incidencia_id,))
                conn.commit()
            self._incidencias.remove(encontrada)
            self._guardar_json_sin_lock()
            return True

    def resumen_por_fecha(self, fecha_iso):
        """Consulta SQLite indexada (idx_incidencias_fecha / idx_alertas_fecha) por YYYY-MM-DD."""
        with self._lock_db, closing(self._conectar_db()) as conn:
            filas = conn.execute(
                """
                SELECT id, tipo, descripcion, estado, hora, origen
                FROM incidencias
                WHERE fecha = ?
                ORDER BY id DESC
                """,
                (fecha_iso,),
            ).fetchall()
            filas_estado = conn.execute(
                "SELECT estado, COUNT(*) AS total FROM incidencias WHERE fecha = ? GROUP BY estado",
                (fecha_iso,),
            ).fetchall()
            filas_tipo = conn.execute(
                "SELECT tipo, COUNT(*) AS total FROM incidencias WHERE fecha = ? GROUP BY tipo",
                (fecha_iso,),
            ).fetchall()
            fila_alertas = conn.execute(
                "SELECT COUNT(*) AS total FROM alertas_telegram WHERE fecha = ?",
                (fecha_iso,),
            ).fetchone()

        por_estado = {"abierta": 0, "en_proceso": 0, "resuelta": 0}
        for fila in filas_estado:
            por_estado[fila["estado"]] = fila["total"]
        por_tipo = {fila["tipo"]: fila["total"] for fila in filas_tipo}

        incidencias = []
        for fila in filas:
            item = {
                "id": fila["id"],
                "tipo": fila["tipo"],
                "descripcion": fila["descripcion"],
                "estado": fila["estado"],
                "hora": fila["hora"],
            }
            if fila["origen"]:
                item["origen"] = fila["origen"]
            incidencias.append(item)

        return {
            "fecha": fecha_iso,
            "total": len(incidencias),
            "por_estado": por_estado,
            "por_tipo": por_tipo,
            "total_alertas": fila_alertas["total"] if fila_alertas else 0,
            "incidencias": incidencias,
        }

    # ------------------------------------------------------------------
    # Bitacora de Telegram (alertas_telegram.json + SQLite)
    # ------------------------------------------------------------------
    def cargar_alertas(self):
        with self._lock_alertas:
            datos = self._leer_json(self.ruta_alertas)
            return datos if isinstance(datos, list) else []

    def registrar_alerta(self, evento):
        """Agrega un evento asignandole id_alerta y hora; persiste en SQLite y JSON."""
        with self._lock_alertas:
            datos = self._leer_json(self.ruta_alertas)
            alertas = datos if isinstance(datos, list) else []
            hora = _ahora()
            registro = {
                "id_alerta": max((a.get("id_alerta", 0) for a in alertas), default=0) + 1,
                "hora": hora,
            }
            registro.update(evento)
            with self._lock_db, closing(self._conectar_db()) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO alertas_telegram (
                        id_alerta, hora, fecha, incidencia_id, tipo_incidencia,
                        motivo, estado_envio, codigo_http, detalle
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        registro["id_alerta"],
                        registro["hora"],
                        _fecha_de_hora(registro["hora"]),
                        registro.get("incidencia_id"),
                        registro.get("tipo_incidencia"),
                        registro.get("motivo"),
                        registro.get("estado_envio"),
                        registro.get("codigo_http"),
                        registro.get("detalle"),
                    ),
                )
                conn.commit()
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
