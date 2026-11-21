# Defensa Técnica ante Cuestionamientos del Profesor

Este documento responde punto por punto a las preguntas técnicas sobre flujo de datos, transporte, base de datos SQLite frente a JSON, comunicación con el chatbot y control de acceso del sistema **Bitácora de Incidencias en Red Local (Equipo 01)**.

---

## 1. ¿De dónde viene la información? (Origen de los datos)

La información nace en dos fuentes dentro de la red privada (LAN) de la MiPyME:

1. **Agentes de monitoreo en las terminales (`agente_puertos.py` — F6):**
   - Cada terminal ejecuta periódicamente un sondeo TCP local mediante `socket.connect_ex(("127.0.0.1", puerto))` sobre puertos sensibles definidos (`21/FTP`, `22/SSH`, `23/Telnet`, `445/SMB`, `3389/RDP`).
   - Cuando detecta un puerto abierto (`resultado == 0`) que no está en su lista blanca local, genera automáticamente un reporte de vulnerabilidad hacia el servidor central.
2. **Consola administrativa (`cliente_admin.py` — F9 / `curl`):**
   - El administrador o soporte técnico registra incidentes manuales (`POST`), consulta historial (`GET`) o actualiza el ciclo de vida (`PATCH`, `PUT`, `DELETE`).

---

## 2. ¿Qué datos viajan desde el cliente? (Carga útil / Payload)

Por la red **no viajan archivos de base de datos ni credenciales de Telegram**, únicamente estructuras JSON ligeras:

- **Desde el cliente hacia el servidor (`POST /incidencias`):**
  ```json
  {
    "tipo": "vulnerabilidad",
    "descripcion": "Puerto no autorizado abierto: 23",
    "estado": "abierta"
  }
  ```
  - `tipo` (obligatorio): `"incidente"`, `"vulnerabilidad"`, `"alerta"`, etc.
  - `descripcion` (obligatorio): detalle legible del evento detectado.
  - `estado` (opcional en `POST`, por defecto `"abierta"`): `"abierta"`, `"en_proceso"` o `"resuelta"`.

- **Enriquecimiento en el servidor (`almacen.py`):**
  Al recibir el JSON, el servidor asigna automáticamente:
  - `id`: folio autoincremental único y monótono.
  - `hora`: marca temporal ISO-8601 con zona horaria del servidor.
  - `fecha`: día calendario (`YYYY-MM-DD`) extraído de `hora` para indexación en SQLite.
  - `origen`: IP de la terminal cliente (opcional si el endpoint la pasa).

- **Respuesta del servidor al cliente (`201 Created` / `200 OK`):**
  Devuelve el objeto JSON completo de la incidencia creada o las listas filtradas / contadores / bitácora de auditoría.

---

## 3. ¿Cómo viaja la información y cómo se interpreta en el servidor?

1. **Transporte cifrado (F1 — `servidor_bitacora.py`):**
   - El servidor escucha en `0.0.0.0:8443/TCP` mediante `ThreadingHTTPServer`.
   - Cada conexión TCP entrante pasa por un **handshake TLS (`ssl.PROTOCOL_TLS_SERVER`, mínimo TLS 1.2)** en su propio hilo usando `certificado.pem` y `llave.pem`.
   - Los clientes validan la autenticidad del servidor con `verify="certificado.pem"`.
   - Si un cliente intenta enviar **HTTP sin cifrar**, el handshake falla, el socket se cierra y se registra un evento `TLS_RECHAZADO` en `/logs`.

2. **Interpretación y validación (`manejador_http.py`):**
   - Se parsea la ruta y la query string (`urlparse` / `parse_qs`).
   - En peticiones con cuerpo (`POST`, `PUT`, `PATCH`), `_leer_json_cuerpo()` lee exactamente `Content-Length` bytes (límite máximo `1 MiB`), decodifica UTF-8 y parsea a diccionario Python con `json.loads()`. Si el JSON está mal formado o no es un objeto, responde `400 Bad Request`.
   - Se valida el vocabulario controlado (`tipo` y `descripcion` no vacíos; `estado` estrictamente en `("abierta", "en_proceso", "resuelta")`).
   - Cada respuesta HTTP se audita automáticamente en `/logs` y `/contadores` (totales por método y familia `2xx`/`4xx`/`5xx`).

3. **Tolerancia a fallos:**
   - Excepciones de socket como `BrokenPipeError`, `ConnectionResetError` o `TimeoutError` se capturan por hilo en `handle_one_request()` sin detener el servidor ni corromper el almacenamiento.

---

## 4. ¿Por qué usar SQLite en vez de solo un archivo JSON plano? (Ejemplo: *"¿cómo estuvo el día miércoles?"*)

Inicialmente se planteó persistir únicamente en `incidencias.json`. Sin embargo, ante un crecimiento de registros históricos, leer y filtrar un archivo JSON plano obliga a **deserializar todo el archivo en memoria y recorrerlo secuencialmente ($O(N)$)**, además de reescribir el archivo completo ante cada cambio.

Para resolver esto sin romper la compatibilidad del contrato con el equipo, **`almacen.py` (F2) integra SQLite (`sqlite3`) como motor principal indexado (`bitacora.db`) y mantiene un espejo JSON (`incidencias.json` y `alertas_telegram.json`)**:

1. **Tablas e índices en `bitacora.db`:**
   - Tabla `incidencias` con columna `fecha` (`YYYY-MM-DD`) e índices B-Tree dedicados:
     - `idx_incidencias_fecha` sobre `incidencias(fecha)`
     - `idx_incidencias_estado` sobre `incidencias(estado)`
     - `idx_incidencias_tipo` sobre `incidencias(tipo)`
   - Tabla `alertas_telegram` con índice `idx_alertas_fecha` sobre `alertas_telegram(fecha)`.
   - Configurado con `PRAGMA journal_mode=WAL;` y candado de sincronización (`threading.Lock`) para lecturas y escrituras concurrentes seguras.

2. **Cómo resuelve una consulta histórica (ej. `/dia miercoles`):**
   - El bot convierte `"miercoles"` a la fecha exacta ISO-8601 más reciente (por ejemplo `2026-11-18`).
   - `almacen.resumen_por_fecha("2026-11-18")` ejecuta consultas SQL directas (`WHERE fecha = ?` con `GROUP BY estado` y `GROUP BY tipo`) aprovechando `idx_incidencias_fecha` e `idx_alertas_fecha`.
   - La búsqueda pasa de un escaneo lineal del JSON ($O(N)$) a una búsqueda indexada B-Tree ($O(\log N)$) en milisegundos, sin cargar miles de registros de otros días ni bloquear el resto del sistema.

---

## 5. ¿Cómo se comunica el servidor con el Chatbot de Telegram?

La comunicación se divide en dos flujos independientes, ambos utilizando **únicamente conexiones HTTPS salientes hacia `api.telegram.org`** (sin abrir puertos entrantes en el firewall ni exponer la LAN de la MiPyME a Internet):

1. **Alertas automáticas por umbral (`notificador_telegram.py` — F3):**
   - Al registrarse una nueva incidencia, se evalúa el umbral:
     - **Umbral crítico directo (1/1):** si `tipo` es `"incidente"` o `"incidente_critico"`.
     - **Umbral por acumulación:** si hay $\ge 3$ incidencias en estado `"abierta"`.
   - Si supera el umbral, el servidor ejecuta `requests.post("https://api.telegram.org/bot<TOKEN>/sendMessage", ..., timeout=5)` dentro de un bloque `try/except`.
   - Si no hay Internet, registra `FALLIDO_SIN_INTERNET` (`codigo_http = 503`) en `alertas_telegram` (SQLite y JSON) y el monitoreo local continúa operando sin interrupciones.

2. **Consultas interactivas del administrador (`bot_comandos.py` — mejora F3):**
   - Un hilo secundario (`daemon=True`) ejecuta **Long Polling** sobre `GET https://api.telegram.org/bot<TOKEN>/getUpdates?timeout=25`.
   - Al arrancar, descarta mensajes viejos acumulados mientras el servidor estaba apagado (`offset = -1`).
   - Cuando el administrador escribe comandos como `/estado`, `/incidencias`, `/dia miercoles`, `/fecha 2026-11-18`, `/contadores`, `/alertas` o `/ayuda`:
     1. Verifica el `chat.id` remitente.
     2. Consulta en tiempo real a `AlmacenBitacora` (memoria para contadores/logs y **SQLite indexado** para consultas por día).
     3. Responde al chat mediante `POST .../sendMessage`.
   - Si se pierde Internet temporalmente, el hilo aplica *backoff* exponencial (`5s` hasta `60s`) sin afectar el servidor HTTPS de la LAN.

---

## 6. ¿Quiénes pueden acceder a la información? (Control de acceso)

El acceso está segregado en tres niveles:

1. **Acceso al Chatbot de Telegram (solo administrador autorizado):**
   - El bot valida estrictamente que `chat.id` pertenezca a `TELEGRAM_ADMIN_IDS` (que incluye `TELEGRAM_CHAT_ID`, configurado en `.env` únicamente en el servidor central de Eddi).
   - Cualquier mensaje de otro usuario de Telegram es **ignorado silenciosamente** y queda registrado en `/logs` con el evento `BOT_NO_AUTORIZADO` y el ID del remitente.

2. **Acceso al Servidor Central, Llave Privada y Base de Datos (solo Eddi Michael):**
   - El archivo `.env` (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`), la llave privada TLS (`llave.pem`), la base SQLite (`bitacora.db`) y los archivos JSON residen únicamente en el nodo servidor de Eddi y están excluidos del repositorio en `.gitignore`.
   - Sus compañeros (Rodrigo y Fernanda) trabajan únicamente en sus zonas asignadas (`manejador_http.py`, `agente_puertos.py`, `cliente_admin.py`) sin acceso al token ni a `llave.pem`, verificado antes de cada integración mediante `scripts/verificar_zonas.py`.

3. **Acceso de los Nodos en la LAN (Agentes y Cliente Admin):**
   - Las terminales solo reciben el certificado público `certificado.pem` para establecer el canal cifrado TLS (`verify="certificado.pem"`) contra la IP del servidor en el puerto `8443`.
