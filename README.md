# Bitácora de Incidencias en Red Local (Equipo 01)

Sistema ligero de monitoreo de incidencias para MiPyMEs sobre HTTPS/TLS con alerta por umbrales vía Bot de Telegram.
Programación en Red (NRC 19141, UV).

## Inicio rápido

```bash
pip install -r requirements.txt
python3 scripts/generar_certificados.py      # certificado.pem y llave.pem
cp .env.example .env                         # llenar token y chat id de Telegram
python3 servidor_bitacora.py                 # https://<IP>:8443
curl --cacert certificado.pem https://localhost:8443/salud
python3 -m unittest discover -s tests -v
```

## Archivos

| Archivo | Responsable | Función |
| :--- | :--- | :--- |
| `servidor_bitacora.py` | Eddi | F1 servidor concurrente HTTPS/TLS |
| `almacen.py` | Eddi | F2 persistencia SQLite (`bitacora.db`) + espejo JSON con `threading.Lock` |
| `notificador_telegram.py` | Eddi | F3 umbrales (Push 5s) + Bot de Telegram (Polling `/dia`, `/fecha`, `/estado`) |
| `manejador_http.py` | Rodrigo (F4, F5) / Fernanda (F7, F8) | Endpoints REST |
| `agente_puertos.py` | Rodrigo | F6 agente de puertos |
| `cliente_admin.py` | Fernanda | F9 cliente CLI |

## Documentación

- [Contrato de API](docs/CONTRATO_API.md)
- [Guía de equipo y Git](docs/GUIA_EQUIPO_GIT.md)
- [Contexto del proyecto](docs/CONTEXTO_PROYECTO.md)
- [Documento base de la práctica 11](docs/documentacion_practica11.txt)

## Telegram

La administración del Bot (`@monitor_incidentes_bot`), el archivo `.env` (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`)
y la ejecución del servidor central con polling activo son **exclusivos de Eddi Michael** (`TELEGRAM_CHAT_ID` autorizado).
Los demás integrantes trabajan **sin `.env`** (modo local `SIN_CREDENCIALES` y comandos inactivos) o conectándose
como clientes HTTPS al servidor de Eddi usando únicamente el certificado público `certificado.pem`.

Con el servidor de Eddi en marcha, el administrador autorizado puede consultar el estado desde el chat del bot
(solo responde a `TELEGRAM_CHAT_ID` y a los ids de `ADMIN_CHAT_IDS`; cualquier otro chat es rechazado y auditado):

| Comando | Respuesta |
| :--- | :--- |
| `/estado` | Servidor activo, uptime, puerto/TLS, incidencias, peticiones, rechazos TLS |
| `/incidencias` | Conteo por estado y últimas abiertas |
| `/dia <dia\|fecha>` | Reporte indexado en SQLite por día (ej. `/dia miercoles`, `/dia hoy`, `/dia 2026-11-18`) |
| `/contadores` | Peticiones por método y familia 2xx/4xx/5xx |
| `/alertas` | Últimas alertas enviadas |
| `/ayuda` | Lista de comandos |

> Si `API_KEYS` está configurado en `.env`, los clientes (`agente_puertos.py` y `cliente_admin.py`)
> deben enviar la cabecera `X-API-Key` en las peticiones protegidas (si falta o es inválida responde `401`).
> Solo **un** proceso a la vez puede escuchar comandos con el mismo token. Si otro compañero levanta el servidor con
> el mismo token, uno de los dos verá un aviso 409; usen `BOT_COMANDOS=0` en el segundo.

```bash
python3 notificador_telegram.py --verificar   # valida el token (getMe)
python3 notificador_telegram.py --prueba      # envía un mensaje de prueba
```
