# Contexto del Proyecto (para continuar en un chat nuevo)

> Pega o menciona este archivo (`@docs/CONTEXTO_PROYECTO.md`) al iniciar una conversación nueva dentro del proyecto.

## Qué es
Proyecto integrador **Programación en Red (NRC 19141, UV)**: Sistema ligero de monitoreo de incidencias en red local para MiPyMEs sobre HTTPS/TLS con alerta por umbrales vía Bot de Telegram. Documento base: `docs/documentacion_practica11.txt`.

## Usuario y equipo
- **Eddi Michael Hernández Rodríguez** (el usuario): F1, F2, F3 + Bot de Telegram. Rama `feature/servidor-tls-alertas`.
- **Rodrigo García**: F4, F5, F6. Rama `feature/registro-consultas-agente`.
- **Fernanda**: F7, F8, F9. Rama `feature/gestion-auditoria-cliente`.
- El usuario delegó las decisiones técnicas al agente: priorizar estabilidad, funcionalidad y profesionalismo.

## Estado actual (2026-11-20)
- Repo Git con `main` (base común) y las 3 ramas `feature/...`. Rama activa: `feature/servidor-tls-alertas`.
- **Hecho (rama de Eddi):** `servidor_bitacora.py` (F1), `almacen.py` (F2), `notificador_telegram.py` (F3), `config.py`, `scripts/generar_certificados.py`, 18 pruebas en `tests/` (todas pasan con `python3 -m unittest discover -s tests -v`).
- **Base en `main`:** `manejador_http.py` con utilidades compartidas, `GET /salud`, auditoría automática; stubs 501 para F4, F5, F7, F8; stubs `agente_puertos.py` (F6) y `cliente_admin.py` (F9).
- Documentación del equipo: `docs/CONTRATO_API.md`, `docs/GUIA_EQUIPO_GIT.md`, `README.md`.

## Pendiente
- Crear el bot real en @BotFather, llenar `.env` (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) y probar `python3 notificador_telegram.py --verificar` / `--prueba`.
- Fusionar `feature/servidor-tls-alertas` a `main` (PR) para que Rodrigo y Fernanda hagan `git merge main`.
- Subir a GitHub (`bitacora-equipo-01`) si el equipo lo decide.
- Implementar F4-F9 (responsabilidad de Rodrigo y Fernanda; Eddi puede apoyar).

## Notas técnicas
- Certificados: `python3 scripts/generar_certificados.py` (genera `certificado.pem` y `llave.pem` con SAN; no se suben a Git).
- Timeout de Telegram = 5 s, así que los clientes que hagan `POST /incidencias` deben usar timeout >= 10 s.
- La ruta tiene espacios: `/home/Maicolhack/Documents/Programacion en red` (usar comillas en comandos).
