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
| `almacen.py` | Eddi | F2 persistencia JSON con `threading.Lock` |
| `notificador_telegram.py` | Eddi | F3 umbrales + Bot de Telegram |
| `manejador_http.py` | Rodrigo (F4, F5) / Fernanda (F7, F8) | Endpoints REST |
| `agente_puertos.py` | Rodrigo | F6 agente de puertos |
| `cliente_admin.py` | Fernanda | F9 cliente CLI |

## Documentación

- [Contrato de API](docs/CONTRATO_API.md)
- [Guía de equipo y Git](docs/GUIA_EQUIPO_GIT.md)
- [Contexto del proyecto](docs/CONTEXTO_PROYECTO.md)
- [Documento base de la práctica 11](docs/documentacion_practica11.txt)

## Telegram

```bash
python3 notificador_telegram.py --verificar   # valida el token (getMe)
python3 notificador_telegram.py --prueba      # envía un mensaje de prueba
```
