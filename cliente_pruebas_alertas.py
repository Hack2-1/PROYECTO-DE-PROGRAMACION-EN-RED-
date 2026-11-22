"""Cliente generador de incidencias de prueba y evidencia de alertas en Telegram.

Permite simular los escenarios de umbral del proyecto (pico de CPU, saturacion
de RAM, alteracion de seguridad sin TLS y acumulacion >= 3 incidencias abiertas)
para verificar en vivo que el servidor las registra en SQLite/JSON y envia las
alertas correspondientes al Bot de Telegram (@monitor_incidentes_bot).
"""

import argparse
import os
import socket
import sys
from urllib.parse import urlsplit

import requests

from agente_puertos import ejecutar_escaneo


def _cabeceras(api_key=None, con_json=False):
    headers = {}
    if con_json:
        headers["Content-Type"] = "application/json"
    if api_key:
        headers["X-API-Key"] = api_key
    return headers


def _get_json(url_servidor, ruta, ruta_certificado, api_key=None):
    url = f"{url_servidor.rstrip('/')}{ruta}"
    try:
        resp = requests.get(
            url,
            headers=_cabeceras(api_key=api_key),
            verify=ruta_certificado,
            timeout=10,
        )
        return resp.status_code, resp.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"[AVISO] Error al consultar {ruta}: {exc}")
        return None, None


def enviar_incidencia_prueba(url_servidor, ruta_certificado, tipo, descripcion, api_key=None):
    """Envia POST /incidencias al servidor HTTPS y devuelve (codigo_http, cuerpo)."""
    url = f"{url_servidor.rstrip('/')}/incidencias"
    payload = {"tipo": tipo, "descripcion": descripcion}
    try:
        resp = requests.post(
            url,
            json=payload,
            headers=_cabeceras(api_key=api_key, con_json=True),
            verify=ruta_certificado,
            timeout=10,
        )
        try:
            cuerpo = resp.json()
        except ValueError:
            cuerpo = {"respuesta": resp.text}
        if resp.status_code == 201:
            print(
                f"[OK] Incidencia #{cuerpo.get('id')} registrada "
                f"({cuerpo.get('tipo')}): {cuerpo.get('descripcion')}"
            )
        else:
            print(f"[AVISO] Servidor respondio HTTP {resp.status_code}: {cuerpo}")
        return resp.status_code, cuerpo
    except requests.RequestException as exc:
        print(f"[ERROR] No se pudo conectar con {url}: {exc}")
        return None, None


def obtener_evidencia_alertas(url_servidor, ruta_certificado, api_key=None):
    """Consulta /salud, /incidencias, /alertas y /contadores como evidencia."""
    cod_salud, salud = _get_json(url_servidor, "/salud", ruta_certificado, api_key)
    cod_inc, incidencias = _get_json(url_servidor, "/incidencias", ruta_certificado, api_key)
    cod_al, alertas = _get_json(url_servidor, "/alertas", ruta_certificado, api_key)
    cod_cnt, contadores = _get_json(url_servidor, "/contadores", ruta_certificado, api_key)

    return {
        "salud": salud if cod_salud == 200 and isinstance(salud, dict) else {},
        "incidencias": incidencias if cod_inc == 200 and isinstance(incidencias, list) else [],
        "alertas": alertas if cod_al == 200 and isinstance(alertas, list) else [],
        "contadores": contadores if cod_cnt == 200 and isinstance(contadores, dict) else {},
    }


def escenario_umbral_cpu(url, cert, api_key=None, porcentaje=96.0):
    """Dispara umbral critico directo (1/1) simulando pico de CPU."""
    print(f"\n--- Escenario 1: Pico de CPU ({porcentaje:.1f}%) ---")
    descripcion = (
        f"Uso critico de CPU en servidor: {porcentaje:.1f}% (supera umbral de 85%)"
    )
    return enviar_incidencia_prueba(url, cert, "incidente", descripcion, api_key=api_key)


def escenario_umbral_ram(url, cert, api_key=None, porcentaje=93.5):
    """Dispara umbral critico directo (1/1) simulando saturacion de RAM."""
    print(f"\n--- Escenario 2: Saturacion de RAM ({porcentaje:.1f}%) ---")
    descripcion = (
        f"Saturacion de memoria RAM en servidor: {porcentaje:.1f}% (supera umbral de 85%)"
    )
    return enviar_incidencia_prueba(url, cert, "incidente", descripcion, api_key=api_key)


def escenario_alteracion_seguridad(url, cert, api_key=None):
    """Provoca un rechazo TLS con HTTP plano y reporta alteracion de seguridad."""
    print("\n--- Escenario 3: Alteracion de seguridad (intento sin TLS) ---")
    partes = urlsplit(url)
    host = partes.hostname or "127.0.0.1"
    puerto = partes.port or 8443
    try:
        with socket.create_connection((host, puerto), timeout=5) as sock:
            sock.sendall(b"GET /salud HTTP/1.1\r\nHost: prueba\r\n\r\n")
            try:
                sock.recv(256)
            except OSError:
                pass
        print(f"[INFO] Peticion HTTP plano rechazada por TLS en {host}:{puerto}.")
    except OSError as exc:
        print(f"[AVISO] No se pudo enviar sonda HTTP plano: {exc}")

    descripcion = (
        f"Alteracion de seguridad en servidor: intento de acceso sin TLS detectado en puerto {puerto}"
    )
    return enviar_incidencia_prueba(url, cert, "incidente", descripcion, api_key=api_key)


def escenario_acumulacion_tres_abiertas(url, cert, api_key=None):
    """Registra 3 incidencias abiertas para activar UMBRAL_ACUMULACION (>= 3)."""
    print("\n--- Escenario 4: Acumulacion de 3 incidencias abiertas ---")
    eventos = (
        ("vulnerabilidad", "Caja 1: Puerto no autorizado abierto: 21 (FTP)"),
        ("vulnerabilidad", "Caja 2: Puerto no autorizado abierto: 445 (SMB)"),
        ("alerta", "Espacio en disco critico en servidor: 91.0% (supera umbral de 90%)"),
    )
    resultados = []
    for tipo, descripcion in eventos:
        resultados.append(enviar_incidencia_prueba(url, cert, tipo, descripcion, api_key=api_key))
    return resultados


def escenario_puerto_no_autorizado(url, cert, api_key=None, puerto_preferido=2323):
    """Abre un puerto TCP sin autorizacion y deja que agente_puertos.py lo detecte."""
    print(f"\n--- Escenario 5: Puerto TCP abierto sin autorizacion ({puerto_preferido}) ---")
    servidor_prueba = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor_prueba.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        try:
            servidor_prueba.bind(("127.0.0.1", puerto_preferido))
        except OSError:
            servidor_prueba.bind(("127.0.0.1", 0))
        servidor_prueba.listen(1)
        puerto_abierto = servidor_prueba.getsockname()[1]
        print(f"[INFO] Servicio temporal escuchando sin autorizacion en 127.0.0.1:{puerto_abierto}.")
        return ejecutar_escaneo(
            host="127.0.0.1",
            puertos=[puerto_abierto],
            lista_blanca=[],
            url_servidor=url,
            ruta_certificado=cert,
            api_key=api_key,
        )
    finally:
        servidor_prueba.close()


def mostrar_evidencia(url, cert, api_key=None):
    """Imprime evidencia legible de incidencias y alertas enviadas a Telegram."""
    evidencia = obtener_evidencia_alertas(url, cert, api_key=api_key)
    salud = evidencia["salud"]
    incidencias = evidencia["incidencias"]
    alertas = evidencia["alertas"]
    contadores = evidencia["contadores"]

    print("\n==================== EVIDENCIA DEL SISTEMA ====================")
    if salud:
        recursos = salud.get("recursos", {})
        print(
            f"Servidor: {salud.get('estado', '?').upper()} | "
            f"TLS: {salud.get('version_tls')} | "
            f"CPU: {recursos.get('cpu_porcentaje', '?')}% | "
            f"RAM: {recursos.get('ram_porcentaje', '?')}% | "
            f"Disco: {recursos.get('disco_porcentaje', '?')}%"
        )
    else:
        print("Servidor: sin respuesta en /salud")

    if contadores:
        print(
            f"Trafico auditado: {contadores.get('total', 0)} peticiones | "
            f"Por familia: {contadores.get('por_familia', {})}"
        )

    print(f"\nIncidencias registradas en SQLite/JSON ({len(incidencias)}):")
    for inc in incidencias[-8:]:
        print(
            f"  #{inc.get('id')} | {inc.get('hora')} | "
            f"[{inc.get('tipo')}] ({inc.get('estado')}) {inc.get('descripcion')}"
        )

    print(f"\nBitacora de alertas hacia Telegram ({len(alertas)}):")
    if not alertas:
        print("  (Aun no hay alertas registradas)")
    for al in alertas[-10:]:
        print(
            f"  Alerta #{al.get('id_alerta')} | {al.get('hora')} | "
            f"Incidencia #{al.get('incidencia_id')} | {al.get('motivo')} | "
            f"{al.get('estado_envio')} (HTTP {al.get('codigo_http')})"
        )
    print("===============================================================")
    return evidencia


def ejecutar_demo_completa(url, cert, api_key=None):
    escenario_umbral_cpu(url, cert, api_key=api_key)
    escenario_umbral_ram(url, cert, api_key=api_key)
    escenario_alteracion_seguridad(url, cert, api_key=api_key)
    escenario_acumulacion_tres_abiertas(url, cert, api_key=api_key)
    escenario_puerto_no_autorizado(url, cert, api_key=api_key)
    return mostrar_evidencia(url, cert, api_key=api_key)


def menu_interactivo(url, cert, api_key=None):
    while True:
        print("\n=== CLIENTE DE PRUEBAS DE INCIDENCIAS Y ALERTAS TELEGRAM ===")
        print("1. Levantar alerta critica por pico de CPU (96.0%)")
        print("2. Levantar alerta critica por saturacion de RAM (93.5%)")
        print("3. Simular alteracion de seguridad (HTTP plano sin TLS)")
        print("4. Levantar alerta por acumulacion (3 incidencias abiertas)")
        print("5. Provocar puerto TCP abierto sin autorizacion (deteccion real con sockets)")
        print("6. Ejecutar demostracion completa (todos los escenarios tecnicos)")
        print("7. Ver evidencia actual (/incidencias y /alertas Telegram)")
        print("0. Salir")

        opcion = input("Opcion: ").strip()
        if opcion == "0":
            print("Cliente finalizado.")
            break
        if opcion == "1":
            escenario_umbral_cpu(url, cert, api_key=api_key)
        elif opcion == "2":
            escenario_umbral_ram(url, cert, api_key=api_key)
        elif opcion == "3":
            escenario_alteracion_seguridad(url, cert, api_key=api_key)
        elif opcion == "4":
            escenario_acumulacion_tres_abiertas(url, cert, api_key=api_key)
        elif opcion == "5":
            escenario_puerto_no_autorizado(url, cert, api_key=api_key)
        elif opcion == "6":
            ejecutar_demo_completa(url, cert, api_key=api_key)
        elif opcion == "7":
            mostrar_evidencia(url, cert, api_key=api_key)
        else:
            print("Opcion no valida.")


def construir_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=os.environ.get("BITACORA_URL", "https://localhost:8443"),
        help="URL del servidor central (por defecto: https://localhost:8443)",
    )
    parser.add_argument(
        "--cert",
        default=os.environ.get("BITACORA_CERT", "certificado.pem"),
        help="Ruta al certificado TLS del servidor (por defecto: certificado.pem)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("BITACORA_API_KEY", ""),
        help="Clave X-API-Key opcional",
    )
    parser.add_argument(
        "--escenario",
        choices=("cpu", "ram", "alteracion", "acumulacion", "puerto", "demo"),
        help="Ejecuta directamente un escenario sin abrir el menu",
    )
    parser.add_argument("--cpu", action="store_true", help="Simula pico de CPU 96%")
    parser.add_argument("--ram", action="store_true", help="Simula saturacion de RAM 93.5%")
    parser.add_argument("--alteracion", action="store_true", help="Simula alteracion sin TLS")
    parser.add_argument("--acumulacion", action="store_true", help="Crea 3 incidencias abiertas")
    parser.add_argument("--puerto", action="store_true", help="Abre puerto TCP sin autorizacion y lo detecta")
    parser.add_argument("--demo", action="store_true", help="Ejecuta todos los escenarios")
    parser.add_argument("--evidencia", action="store_true", help="Muestra tabla de evidencia")
    return parser


def main():
    args = construir_parser().parse_args()
    api_key = args.api_key.strip() or None

    acciones = False
    if args.demo or args.escenario == "demo":
        ejecutar_demo_completa(args.url, args.cert, api_key=api_key)
        return 0
    if args.cpu or args.escenario == "cpu":
        escenario_umbral_cpu(args.url, args.cert, api_key=api_key)
        acciones = True
    if args.ram or args.escenario == "ram":
        escenario_umbral_ram(args.url, args.cert, api_key=api_key)
        acciones = True
    if args.alteracion or args.escenario == "alteracion":
        escenario_alteracion_seguridad(args.url, args.cert, api_key=api_key)
        acciones = True
    if args.acumulacion or args.escenario == "acumulacion":
        escenario_acumulacion_tres_abiertas(args.url, args.cert, api_key=api_key)
        acciones = True
    if args.puerto or args.escenario == "puerto":
        escenario_puerto_no_autorizado(args.url, args.cert, api_key=api_key)
        acciones = True
    if args.evidencia:
        mostrar_evidencia(args.url, args.cert, api_key=api_key)
        acciones = True

    if not acciones:
        menu_interactivo(args.url, args.cert, api_key=api_key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
