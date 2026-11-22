# Instrucciones de Trabajo — Rodrigo García (F4, F5 y F6)

> **Rama asignada:** `feature/registro-consultas-agente`  
> **Repositorio:** `https://github.com/Hack2-1/PROYECTO-DE-PROGRAMACION-EN-RED-.git`  
> **Rol en el equipo:** Registro de incidencias (`POST`), consultas con filtros (`GET`) y agente monitor de puertos TCP en la red local.

---

## 1. Preparación inicial en tu computadora

```bash
git clone https://github.com/Hack2-1/PROYECTO-DE-PROGRAMACION-EN-RED-.git
cd PROYECTO-DE-PROGRAMACION-EN-RED-
git checkout feature/registro-consultas-agente
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
   - `manejador_http.py` (únicamente dentro del bloque `# ZONA RODRIGO GARCIA (F4 y F5)`).
   - `agente_puertos.py`.
   - *(Opcional: puedes agregar tus propias pruebas unitarias en `tests/test_rodrigo.py`, sin editar los archivos de pruebas existentes).*
2. **NO modifiques** `servidor_bitacora.py`, `almacen.py`, `notificador_telegram.py`, `config.py`, `scripts/generar_certificados.py`, ni el bloque `ZONA FERNANDA` en `manejador_http.py`.
3. **NO crees archivo `.env` ni subas archivos sensibles a Git:**
   - Nunca subas `*.pem`, `.env`, `*.db` ni `*.json`.
   - En pruebas locales en tu laptop, el servidor detecta que no tienes `.env`, corre en modo local seguro (`SIN_CREDENCIALES`) y no interfiere con el Bot real de Telegram ni con el servidor central de Eddi.

---

## 3. Tus 3 funciones y cómo se conectan con los módulos de Eddi

Antes de programar, revisa `docs/CONTRATO_API.md` para confirmar todos los formatos JSON y códigos de estado HTTP.

### Función F4: Registro y validación de incidencias (`do_POST` en `manejador_http.py`)

Atiende `POST /incidencias` y conecta la petición entrante con **F2 (`almacen.py` / SQLite)** y **F3 (`notificador_telegram.py`)**:

1. Verifica la ruta:
   ```python
   ruta, _ = self._ruta_y_query()
   if ruta != "/incidencias":
       self._enviar_json(404, {"error": "Ruta no encontrada"})
       return
   ```
2. Valida la API Key (si el servidor tiene `API_KEYS` activo en `.env`, responderá `401` automáticamente si falta o es incorrecta):
   ```python
   if not self._verificar_api_key():
       return
   ```
3. Lee y valida el JSON del cuerpo:
   ```python
   datos, error = self._leer_json_cuerpo()
   if error is not None:
       self._enviar_error_json(error)
       return
   ```
4. Guarda la incidencia en SQLite (`bitacora.db`) y `incidencias.json` llamando al almacén de Eddi:
   ```python
   almacen = self._obtener_almacen()
   try:
       incidencia, lista = almacen.crear_incidencia(
           datos.get("tipo"),
           datos.get("descripcion"),
           datos.get("estado", "abierta"),
           origen=self.client_address[0] if self.client_address else None,
       )
   except ValueError as exc:
       self._enviar_json(400, {"error": str(exc)})
       return
   ```
5. Evalúa el umbral de alertas de Telegram llamando al notificador de Eddi (**fuera** de cualquier candado, justo después de guardar):
   ```python
   notificador = self._obtener_notificador()
   if notificador is not None:
       notificador.evaluar_umbral_telegram(incidencia, lista)
   ```
6. Responde con código `201 Created`:
   ```python
   self._enviar_json(201, incidencia)
   ```

> **Nota:** Al llamar a `self._enviar_json(...)`, `ManejadorBitacora` registra automáticamente la petición en `/logs` y `/contadores`.

---

### Función F5: Consultas con filtros y detalle (`manejar_get_incidencias` en `manejador_http.py`)

`do_GET` ya enruta automáticamente `/incidencias` y `/incidencias/<id>` hacia `manejar_get_incidencias(self)`:

1. Valida `X-API-Key`:
   ```python
   if not self._verificar_api_key():
       return
   ```
2. Obtén ruta, query string y el almacén:
   ```python
   ruta, query = self._ruta_y_query()
   almacen = self._obtener_almacen()
   ```
3. **Caso listado (`GET /incidencias?tipo=...&estado=...`):**
   - Si `ruta == "/incidencias"`:
     ```python
     tipo = query.get("tipo", [None])[0]
     estado = query.get("estado", [None])[0]
     lista = almacen.listar_incidencias(tipo=tipo, estado=estado)
     self._enviar_json(200, lista)
     return
     ```
4. **Caso detalle (`GET /incidencias/<id>`):**
   - Extrae y valida el ID entero positivo:
     ```python
     incidencia_id, error_id = self._extraer_id_incidencia(ruta)
     if error_id is not None:
         self._enviar_error_json(error_id)
         return
     incidencia = almacen.obtener_incidencia(incidencia_id)
     if incidencia is None:
         self._enviar_json(404, {"error": "Incidencia no encontrada"})
         return
     self._enviar_json(200, incidencia)
     ```

---

### Función F6: Agente monitor de puertos TCP en la LAN (`agente_puertos.py`)

Implementa el Algoritmo 3 de `docs/documentacion_practica11.txt`:

1. **Lista de puertos críticos a vigilar:** `[21, 22, 23, 445, 3389]` (puedes permitir personalizarla y definir una lista blanca de puertos permitidos en el equipo, por defecto vacía o configurable).
2. **Sondeo con sockets TCP:**
   - Para cada puerto, crea un socket `socket.socket(socket.AF_INET, socket.SOCK_STREAM)`, establece `settimeout(1.5)`, ejecuta `resultado = sock.connect_ex(("127.0.0.1", puerto))` y cierra el socket siempre (`try/finally` o `with`).
3. **Envío cifrado HTTPS al servidor central de Eddi:**
   - Si `resultado == 0` y el puerto **no** está en la lista blanca:
     ```python
     payload = {
         "tipo": "vulnerabilidad",
         "descripcion": f"Puerto no autorizado abierto: {puerto}",
     }
     ```
   - Envía la petición con `requests.post(f"{url_servidor}/incidencias", json=payload, headers=headers, verify=ruta_certificado, timeout=10)`.
     - **Importante:** usar `timeout=10` (porque si el servidor dispara alerta a Telegram y no hay Internet, el servidor tarda hasta 5 s esperando a Telegram antes de responder `201`).
     - Incluir soporte para `X-API-Key` en `headers` si se configura por argumento/variable de entorno.
   - Envuelve la llamada en `try/except requests.RequestException` para imprimir un aviso controlado sin detener el agente si el servidor no responde temporalmente.
4. **Configuración por línea de comandos (`argparse`) o variables de entorno:**
   - Permitir indicar `--url` (ej. `https://127.0.0.1:8443` o `https://192.168.1.50:8443`), `--cert` (por defecto `certificado.pem`), `--api-key`, `--intervalo` / `--una-vez`.

---

## 4. Pruebas locales y subida a GitHub

1. **Probar servidor + tus endpoints localmente:**
   - Terminal 1: `python3 servidor_bitacora.py`
   - Terminal 2:
     ```bash
     curl --cacert certificado.pem https://localhost:8443/salud
     curl --cacert certificado.pem -X POST https://localhost:8443/incidencias \
       -H "Content-Type: application/json" \
       -d '{"tipo":"vulnerabilidad","descripcion":"Prueba puerto 23"}'
     curl --cacert certificado.pem "https://localhost:8443/incidencias?tipo=vulnerabilidad"
     python3 agente_puertos.py --url https://localhost:8443 --cert certificado.pem --una-vez
     ```
2. **Correr pruebas unitarias y verificar estado de Git:**
   ```bash
   python3 -m unittest discover -s tests -v
   git status
   ```
   *(Confirma que solo modificaste `manejador_http.py`, `agente_puertos.py` y tus pruebas opcionales).*
3. **Subir tus commits a tu rama:**
   ```bash
   git add manejador_http.py agente_puertos.py
   git commit -m "feat(f4,f5,f6): registro POST, consultas GET y agente de puertos TCP"
   git push origin feature/registro-consultas-agente
   ```

---

## 5. Cómo se vincula en tiempo real durante la exposición en clase

En la presentación con el profesor (3 laptops en la misma red Wi-Fi / Hotspot):

1. Eddi levanta el servidor central en su laptop (donde están `bitacora.db` y el Bot de Telegram) y te comparte únicamente:
   - Su **IP local** (ej. `192.168.1.50`).
   - El archivo público **`certificado.pem`** (y la `X-API-Key` si está activa).
2. En **tu laptop** colocas ese `certificado.pem` y ejecutas tu agente apuntando a la IP de Eddi:
   ```bash
   python3 agente_puertos.py --url https://192.168.1.50:8443 --cert certificado.pem
   ```
3. Cada puerto no autorizado detectado en tu máquina viajará en vivo cifrado por HTTPS (`:8443`) hasta la laptop de Eddi, se guardará en su SQLite (`bitacora.db`) y disparará la alerta por umbral en Telegram en tiempo real.
