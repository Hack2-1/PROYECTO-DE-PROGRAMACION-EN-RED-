# Contrato Técnico de API REST e Interfaces Internas

Este documento define el contrato único entre los módulos de **Eddi Michael** (`servidor_bitacora.py`, `almacen.py`, `notificador_telegram.py`), **Rodrigo García** (`manejador_http.py` F4/F5, `agente_puertos.py` F6) y **Fernanda** (`manejador_http.py` F7/F8, `cliente_admin.py` F9).

---

## 1. Vocabulario Controlado y Esquemas JSON

### 1.1 Incidencia (`incidencias.json`)
En disco (`incidencias.json`), el almacén D1 persiste el objeto:
```json
{
  "siguiente_id": 2,
  "incidencias": [
    {
      "id": 1,
      "tipo": "vulnerabilidad",
      "descripcion": "Puerto no autorizado abierto: 23",
      "estado": "abierta",
      "hora": "2026-11-20T15:30:00-06:00"
    }
  ]
}
```
> **Nota de compatibilidad:** `almacen.cargar()` también acepta leer una lista JSON directa `[...]` y calcula `siguiente_id = max(id) + 1` (o `1` si está vacía).

**Reglas de campos:**
- `id` (`int`): Autoincremental, único y monótono (no se reutiliza tras `DELETE`).
- `tipo` (`str`, obligatorio, no vacío): Valores sugeridos: `"incidente"`, `"vulnerabilidad"`, `"alerta"`.
  - Si `tipo` es `"incidente"` (o `"incidente_critico"`), dispara el umbral directo `1/1` en Telegram.
- `descripcion` (`str`, obligatorio, no vacío).
- `estado` (`str`): Vocabulario controlado estricto:
  - `"abierta"` (valor por defecto en `POST` si se omite; reiniciado automáticamente en `PUT`)
  - `"en_proceso"`
  - `"resuelta"`
- `hora` (`str`): Marca temporal ISO-8601 asignada por el servidor.

### 1.2 Bitácora de Telegram (`alertas_telegram.json`)
```json
[
  {
    "id_alerta": 1,
    "hora": "2026-11-20T15:31:00-06:00",
    "incidencia_id": 1,
    "tipo_incidencia": "incidente",
    "motivo": "UMBRAL_CRITICO_DIRECTO (1/1)",
    "estado_envio": "ENVIADO",
    "codigo_http": 200,
    "detalle": "Notificacion entregada a Telegram"
  }
]
```
Valores posibles de `estado_envio`: `"ENVIADO"`, `"ERROR_API"`, `"FALLIDO_SIN_INTERNET"` (`codigo_http = 503`), `"SIN_CREDENCIALES"`.

---

## 2. Endpoints REST sobre HTTPS (`https://<IP>:8443`)

| Método | Ruta | Responsable | Entrada JSON / Query | Respuestas |
| :--- | :--- | :--- | :--- | :--- |
| `GET` | `/salud` | Base (`main`) | — | `200 OK` estado del canal TLS |
| `POST` | `/incidencias` | Rodrigo (F4) | `{"tipo": str, "descripcion": str, "estado"?: str}` + `X-API-Key` (si `API_KEYS` activo) | `201 Created` / `400 Bad Request` / `401 Unauthorized` |
| `GET` | `/incidencias` | Rodrigo (F5) | `?tipo=...&estado=...` (opcionales) | `200 OK` lista JSON filtrada |
| `GET` | `/incidencias/<id>` | Rodrigo (F5) | `<id>` entero positivo | `200 OK` objeto / `400` ID no entero / `404` no existe |
| `PATCH` | `/incidencias/<id>` | Fernanda (F7) | `{"estado": "abierta" \| "en_proceso" \| "resuelta"}` | `200 OK` / `400` estado inválido / `404` |
| `PUT` | `/incidencias/<id>` | Fernanda (F7) | `{"tipo": str, "descripcion": str}` (reinicia `estado="abierta"`) | `200 OK` / `400` / `404` |
| `DELETE` | `/incidencias/<id>` | Fernanda (F8) | `<id>` entero positivo | `204 No Content` / `400` / `404` |
| `GET` | `/logs` | Fernanda (F8) | — | `200 OK` lista de bitácora HTTP y rechazos TLS |
| `GET` | `/contadores` | Fernanda (F8) | — | `200 OK` métricas por método y familia `2xx`/`4xx`/`5xx` |
| `GET` | `/alertas` | Fernanda (F8) | — | `200 OK` contenido de `alertas_telegram.json` |

> **Nota sobre tiempos de espera en clientes (`agente_puertos.py` y `cliente_admin.py`):**  
> `notificador_telegram.py` usa `timeout=5` para la API de Telegram. Por ello, cuando no hay Internet, una petición `POST /incidencias` que dispare alerta puede tardar hasta 5 segundos en responder `201`. Se recomienda usar `timeout=10` en los clientes que envían `POST /incidencias` (o configurar un timeout >= 6 s) y `verify="certificado.pem"`.

---

## 3. Interfaces Internas Expuestas por Eddi Michael

En `manejador_http.py`, los métodos acceden al almacén y al notificador mediante:
```python
almacen = self._obtener_almacen()
notificador = self._obtener_notificador()
```
Además, el registro en `/logs` y `/contadores` ocurre **automáticamente** cada vez que se responde con `self._enviar_json(codigo, payload)` o `self._enviar_sin_contenido(204)`.

### 3.1 Métodos de `almacen` (`AlmacenBitacora`)
- `almacen.crear_incidencia(tipo, descripcion, estado="abierta", origen=None) -> tuple[dict, list[dict]]`  
  Lanza `ValueError` si `tipo`/`descripcion` están vacíos o si `estado` no pertenece a `("abierta", "en_proceso", "resuelta")`.  
  Retorna `(incidencia_creada, snapshot_incidencias)` ya persistido en disco bajo `threading.Lock()`.
- `almacen.listar_incidencias(tipo=None, estado=None) -> list[dict]`
- `almacen.obtener_incidencia(incidencia_id: int) -> dict | None`
- `almacen.actualizar_estado(incidencia_id: int, nuevo_estado: str) -> dict | None` (lanza `ValueError` si estado inválido)
- `almacen.reemplazar_incidencia(incidencia_id: int, tipo: str, descripcion: str) -> dict | None` (reinicia `estado="abierta"`, lanza `ValueError` si campos vacíos)
- `almacen.eliminar_incidencia(incidencia_id: int) -> bool`
- `almacen.obtener_logs() -> list[dict]`
- `almacen.obtener_contadores() -> dict`
- `almacen.cargar_alertas() -> list[dict]`

### 3.2 Módulo F3 (`notificador_telegram.py`: `NotificadorTelegram` + `BotComandos`)
- `notificador.evaluar_umbral_telegram(incidencia_nueva, lista_incidencias) -> dict`  
  Debe llamarse **después** de `almacen.crear_incidencia(...)` (fuera del candado).  
  Nunca lanza excepciones hacia el hilo HTTP; ante fallos de red registra `FALLIDO_SIN_INTERNET` en `alertas_telegram.json`.
- `BotComandos` (en `notificador_telegram.py`): hilo en segundo plano con long polling (`getUpdates`), lista blanca `ADMIN_CHAT_IDS` y consulta indexada en SQLite (`/dia`, `/fecha`, `/estado`, `/incidencias`, `/contadores`, `/alertas`).

### 3.3 Utilidades disponibles en `ManejadorBitacora`
- `self._verificar_api_key()` (si `API_KEYS` está configurado en `.env`, valida la cabecera `X-API-Key`; si falla, registra `API_KEY_RECHAZADA`, responde `401` y devuelve `False`)
- `ruta, query = self._ruta_y_query()`
- `datos, error = self._leer_json_cuerpo()` (si `error` no es `None`, responde `self._enviar_json(error[0], {"error": error[1]})`)
- `incidencia_id, error_id = self._extraer_id_incidencia(ruta)` (si `error_id`, responde `400`)
- `self._enviar_json(codigo, payload)`
- `self._enviar_sin_contenido(204)`
