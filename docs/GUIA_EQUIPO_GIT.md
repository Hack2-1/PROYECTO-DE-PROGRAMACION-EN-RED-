# Guía de Trabajo en Equipo y Flujo Git (`bitacora-equipo-01`)

Para mantener un historial limpio de commits por integrante y evitar conflictos de fusión (*merge conflicts*), seguimos esta organización:

---

## 1. Estructura de Ramas

- `main`: Rama estable con la arquitectura base, contratos y código integrado y probado.
- `feature/servidor-tls-alertas`: **Eddi Michael** (F1, F2, F3 + pruebas base).
- `feature/registro-consultas-agente`: **Rodrigo García** (F4, F5, F6).
- `feature/gestion-auditoria-cliente`: **Fernanda** (F7, F8, F9).

---

## 2. Cómo Evitar Conflictos en `manejador_http.py`

Tanto Rodrigo como Fernanda implementan métodos dentro de `manejador_http.py`. Para evitar choques:

1. `do_GET` ya está enrutado desde `main` hacia dos métodos separados:
   - **Rodrigo** solo modifica `do_POST` y `manejar_get_incidencias` (marcados bajo `ZONA RODRIGO GARCIA`), además de su archivo `agente_puertos.py`.
   - **Fernanda** solo modifica `do_PATCH`, `do_PUT`, `do_DELETE` y `manejar_get_auditoria` (marcados bajo `ZONA FERNANDA`), además de su archivo `cliente_admin.py`.
2. **Nunca** cambien la firma de `_enviar_json`, `_leer_json_cuerpo`, `do_GET` o los métodos de `almacen.py` sin acordarlo antes.

### 2.1 Archivos y Credenciales de Acceso Exclusivo (Eddi Michael)

Para mantener la estabilidad del servidor TLS y la seguridad del Bot de Telegram, se restringe el acceso de la siguiente forma:

- **Archivos bloqueados (solo Eddi Michael):** `servidor_bitacora.py`, `almacen.py`, `notificador_telegram.py` (que concentra toda la función F3: push de umbrales + polling de comandos), `config.py`, `scripts/generar_certificados.py` y las utilidades base de `manejador_http.py`. Rodrigo y Fernanda no deben modificar estos archivos ni cambiar su comportamiento.
- **Credenciales y Llave Privada (solo Eddi Michael):** El archivo `.env` (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `ADMIN_CHAT_IDS`, `API_KEYS`) y la llave privada `llave.pem` viven únicamente en el equipo de Eddi Michael.
  - **Pruebas en red local (LAN):** Eddi levanta el servidor central y solo comparte el archivo público `certificado.pem` para que `agente_puertos.py` y `cliente_admin.py` se conecten a `https://<IP_SERVIDOR_EDDI>:8443` usando `verify="certificado.pem"`.
  - **Pruebas unitarias/locales en otros equipos:** Si Rodrigo o Fernanda corren el servidor en su propia máquina para pruebas locales, deben hacerlo **sin `.env`** (modo local `SIN_CREDENCIALES` en `alertas_telegram.json` y sin polling del bot, evitando conflictos 409).
- **Verificación antes de integrar:** Antes de aceptar un Pull Request hacia `main`, ejecutar `python3 scripts/verificar_zonas.py` para confirmar que las ramas de Rodrigo y Fernanda no alteraron ningún archivo exclusivo de Eddi.

---

## 3. Orden Recomendado de Integración

1. **Paso 1 (Base + Eddi Michael):**  
   `feature/servidor-tls-alertas` se revisa y se fusiona a `main` mediante Pull Request.  
   Con esto `main` ya cuenta con servidor TLS funcional, `almacen.py` y `notificador_telegram.py`.
2. **Paso 2 (Rodrigo y Fernanda actualizan su rama desde `main`):**
   ```bash
   git checkout feature/registro-consultas-agente
   git merge main
   ```
   *(Igual para `feature/gestion-auditoria-cliente`)*.
3. **Paso 3 (Desarrollo y pruebas locales):**  
   Cada integrante trabaja en su rama asignada, realiza commits descriptivos de sus 3 funciones y verifica:
   ```bash
   python3 scripts/generar_certificados.py
   python3 -m unittest discover -s tests -v
   python3 servidor_bitacora.py
   ```
4. **Paso 4 (Pull Request hacia `main`):**  
   - Verificar `git status` (no subir `*.pem`, `.env`, `incidencias.json`, `alertas_telegram.json`, ni `__pycache__`).
   - Probar flujo completo con `curl --cacert certificado.pem`, `agente_puertos.py` y `cliente_admin.py`.
   - Abrir Pull Request hacia `main`.

---

## 4. Convención Sugerida de Commits

- `feat(f1): servidor HTTPS/TLS multihilo con rechazo de HTTP plano`
- `feat(f2): almacen JSON thread-safe con Lock y escritura atomica`
- `feat(f3): motor de umbrales y notificador de Telegram tolerante a fallos`
- `feat(f4): validacion y registro en POST /incidencias`
- `feat(f5): consultas con filtros y detalle en GET /incidencias`
- `feat(f6): agente monitor de puertos TCP en agente_puertos.py`
- `feat(f7): actualizacion PATCH y reemplazo PUT de incidencias`
- `feat(f8): DELETE y endpoints de auditoria /logs, /contadores, /alertas`
- `feat(f9): cliente CLI interactivo y pruebas de concurrencia`
