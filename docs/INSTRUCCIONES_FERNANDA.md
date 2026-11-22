# Instrucciones de Trabajo — Fernanda (F7, F8 y F9)

> **Rama asignada:** `feature/gestion-auditoria-cliente`  
> **Repositorio:** `https://github.com/Hack2-1/PROYECTO-DE-PROGRAMACION-EN-RED-.git`  
> **Rol en el equipo:** Actualización y borrado de incidencias (`PATCH`/`PUT`/`DELETE`), endpoints de auditoría (`/logs`, `/contadores`, `/alertas`) y cliente CLI administrativo con pruebas de concurrencia/fallos.

---

## 1. Preparación inicial en tu computadora

```bash
git clone https://github.com/Hack2-1/PROYECTO-DE-PROGRAMACION-EN-RED-.git
cd PROYECTO-DE-PROGRAMACION-EN-RED-
git checkout feature/gestion-auditoria-cliente
pip install -r requirements.txt
```

Para comprobar que la base del servidor (F1, F2 y F3 de Eddi) ya funciona en tu equipo:
```bash
python3 scripts/generar_certificados.py
python3 -m unittest discover -s tests -v
```

---

## 2. Reglas de archivos y seguridad (muy importante)

1. **Solo puedes modificar estos archivos:**
   - `manejador_http.py` (únicamente dentro del bloque `# ZONA FERNANDA (F7 y F8)`).
   - `cliente_admin.py`.
   - *(Opcional: puedes agregar tus propias pruebas unitarias en `tests/test_fernanda.py`, sin editar los archivos de pruebas existentes).*
2. **NO modifiques** `servidor_bitacora.py`, `almacen.py`, `notificador_telegram.py`, `config.py`, `scripts/generar_certificados.py`, ni el bloque `ZONA RODRIGO GARCIA` en `manejador_http.py`.
3. **NO crees archivo `.env` ni subas archivos sensibles a Git:**
   - Nunca subas `*.pem`, `.env`, `*.db` ni `*.json`.
   - En pruebas locales en tu laptop, el servidor detecta que no tienes `.env`, corre en modo local seguro (`SIN_CREDENCIALES`) y no interfiere con el Bot real de Telegram ni con el servidor central de Eddi.

---

## 3. Tus 3 funciones y cómo se conectan con los módulos de Eddi

Antes de programar, revisa `docs/CONTRATO_API.md` para confirmar todos los formatos JSON y códigos de estado HTTP.

### Función F7: Actualización parcial y reemplazo completo (`do_PATCH` y `do_PUT` en `manejador_http.py`)

Ambos métodos operan sobre `/incidencias/<id>`:

1. **Validaciones comunes al inicio de `do_PATCH` y `do_PUT`:**
   ```python
   if not self._verificar_api_key():
       return
   ruta, _ = self._ruta_y_query()
   incidencia_id, error_id = self._extraer_id_incidencia(ruta)
   if error_id is not None:
       self._enviar_error_json(error_id)
       return
   datos, error = self._leer_json_cuerpo()
   if error is not None:
       self._enviar_error_json(error)
       return
   ```
   *(Nota: `_extraer_id_incidencia(ruta)` valida que la ruta sea `/incidencias/<id>` con entero positivo y devuelve `(400, ...)` si no lo es).*

2. **`do_PATCH` (`PATCH /incidencias/<id>` — cambio de estado validado):**
   ```python
   almacen = self._obtener_almacen()
   try:
       actualizada = almacen.actualizar_estado(incidencia_id, datos.get("estado"))
   except ValueError as exc:
       self._enviar_json(400, {"error": str(exc)})
       return
   if actualizada is None:
       self._enviar_json(404, {"error": "Incidencia no encontrada"})
       return
   self._enviar_json(200, actualizada)
   ```
   *(El almacén valida que el estado sea `"abierta"`, `"en_proceso"` o `"resuelta"`).*

3. **`do_PUT` (`PUT /incidencias/<id>` — reemplazo completo reiniciando `estado="abierta"`):**
   ```python
   almacen = self._obtener_almacen()
   try:
       reemplazada = almacen.reemplazar_incidencia(
           incidencia_id, datos.get("tipo"), datos.get("descripcion")
       )
   except ValueError as exc:
       self._enviar_json(400, {"error": str(exc)})
       return
   if reemplazada is None:
       self._enviar_json(404, {"error": "Incidencia no encontrada"})
       return
   self._enviar_json(200, reemplazada)
   ```

---

### Función F8: Eliminación y endpoints de auditoría (`do_DELETE` y `manejar_get_auditoria` en `manejador_http.py`)

1. **`do_DELETE` (`DELETE /incidencias/<id>`):**
   ```python
   if not self._verificar_api_key():
       return
   ruta, _ = self._ruta_y_query()
   incidencia_id, error_id = self._extraer_id_incidencia(ruta)
   if error_id is not None:
       self._enviar_error_json(error_id)
       return
   eliminada = self._obtener_almacen().eliminar_incidencia(incidencia_id)
   if not eliminada:
       self._enviar_json(404, {"error": "Incidencia no encontrada"})
       return
   self._enviar_sin_contenido(204)
   ```

2. **`manejar_get_auditoria` (`GET /logs`, `GET /contadores`, `GET /alertas`):**
   `do_GET` ya enruta estas 3 rutas hacia `manejar_get_auditoria(self)`:
   ```python
   if not self._verificar_api_key():
       return
   ruta, _ = self._ruta_y_query()
   almacen = self._obtener_almacen()
   if ruta == "/logs":
       self._enviar_json(200, almacen.obtener_logs())
   elif ruta == "/contadores":
       self._enviar_json(200, almacen.obtener_contadores())
   elif ruta == "/alertas":
       self._enviar_json(200, almacen.cargar_alertas())
   else:
       self._enviar_json(404, {"error": "Ruta no encontrada"})
   ```

> **Nota:** Cada respuesta enviada mediante `_enviar_json` o `_enviar_sin_contenido` se contabiliza automáticamente en `/logs` y `/contadores`.

---

### Función F9: Cliente CLI administrativo y pruebas de concurrencia/fallos (`cliente_admin.py`)

Construye el cliente interactivo de consola usando `requests`:

1. **Configuración de conexión segura:**
   - Permite configurar la URL del servidor (ej. `https://localhost:8443` o `https://192.168.1.50:8443`), la ruta al certificado (`certificado.pem` para `verify=...`) y la cabecera opcional `X-API-Key`.
   - Usa **`timeout=10`** en las peticiones (especialmente `POST /incidencias`, porque si dispara alerta a Telegram y no hay Internet el servidor puede tardar hasta 5 s en responder `201`).
   - Envuelve las peticiones en `try/except requests.RequestException` para mostrar mensajes claros sin cerrar el menú si se pierde la red.

2. **Menú interactivo (consumo completo del CRUD + auditoría):**
   - Ver estado TLS (`GET /salud`).
   - Registrar nueva incidencia (`POST /incidencias`).
   - Listar incidencias con filtros opcionales `tipo` / `estado` (`GET /incidencias?tipo=...&estado=...`).
   - Consultar detalle por ID (`GET /incidencias/<id>`).
   - Cambiar estado (`PATCH /incidencias/<id>`).
   - Reemplazar incidencia (`PUT /incidencias/<id>`).
   - Eliminar incidencia (`DELETE /incidencias/<id>`).
   - Ver bitácora y métricas (`GET /logs`, `GET /contadores`, `GET /alertas`).

3. **Rutinas de demostración / estrés exigidas en la Práctica 11:**
   - **Prueba de concurrencia:** lanzar **3 o más hilos simultáneos** (`threading.Thread`) enviando peticiones `POST` o `GET` al servidor TLS y verificar que todas responden correctamente sin corromper `bitacora.db` ni `incidencias.json`.
   - **Prueba de tolerancia a fallos:** abrir un socket TCP/TLS hacia el servidor y cerrarlo abruptamente a mitad de la comunicación, comprobando inmediatamente después que `GET /salud` sigue respondiendo `200 OK`.

---

## 4. Pruebas locales y subida a GitHub

1. **Probar servidor + tus endpoints localmente:**
   - Terminal 1: `python3 servidor_bitacora.py`
   - Terminal 2:
     ```bash
     curl --cacert certificado.pem https://localhost:8443/logs
     curl --cacert certificado.pem https://localhost:8443/contadores
     curl --cacert certificado.pem https://localhost:8443/alertas
     python3 cliente_admin.py --url https://localhost:8443 --cert certificado.pem
     ```
   *(Para probar `PATCH`, `PUT` y `DELETE` antes de fusionar con Rodrigo, puedes usar una incidencia creada manualmente en tu entorno local o esperar al merge tras F4).*
2. **Correr pruebas unitarias y verificar estado de Git:**
   ```bash
   python3 -m unittest discover -s tests -v
   git status
   ```
   *(Confirma que solo modificaste `manejador_http.py`, `cliente_admin.py` y tus pruebas opcionales).*
3. **Subir tus commits a tu rama:**
   ```bash
   git add manejador_http.py cliente_admin.py
   git commit -m "feat(f7,f8,f9): PATCH/PUT/DELETE, endpoints de auditoria y cliente CLI"
   git push origin feature/gestion-auditoria-cliente
   ```

---

## 5. Cómo se vincula en tiempo real durante la exposición en clase

En la presentación con el profesor (3 laptops en la misma red Wi-Fi / Hotspot):

1. Eddi levanta el servidor central en su laptop (donde están `bitacora.db` y el Bot de Telegram) y te comparte únicamente:
   - Su **IP local** (ej. `192.168.1.50`).
   - El archivo público **`certificado.pem`** (y la `X-API-Key` si está activa).
2. En **tu laptop** colocas ese `certificado.pem` y ejecutas tu cliente apuntando a la IP de Eddi:
   ```bash
   python3 cliente_admin.py --url https://192.168.1.50:8443 --cert certificado.pem
   ```
3. Desde tu consola verás en tiempo real las incidencias que acaba de enviar la laptop de Rodrigo, podrás actualizar sus estados (`abierta` $\rightarrow$ `en_proceso` $\rightarrow$ `resuelta`) modificando en vivo la base de datos `bitacora.db` en la laptop de Eddi, y consultar `/logs`, `/contadores` y `/alertas`.
