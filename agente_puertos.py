"""F6 - Agente monitor de puertos TCP y recursos en la LAN (Rodrigo Garcia).

Implementa el Algoritmo 3: sondea puertos criticos locales mediante sockets TCP,
vigila umbrales locales de CPU/RAM cada 30s y reporta por HTTPS al servidor central.
"""

import argparse
import os
import socket
import time

import requests

try:
    from servidor_bitacora import obtener_metricas_sistema as _obtener_metricas_srv
except ImportError:
    _obtener_metricas_srv = None

PUERTOS_CRITICOS_DEFECTO = [21, 22, 23, 445, 3389]


def parsear_puertos(texto):
    """Convierte una cadena separada por comas (ej. '21,22,23') a lista de enteros."""
    if not texto:
        return []
    puertos = []
    for item in texto.split(","):
        item = item.strip()
        if item:
            puertos.append(int(item))
    return puertos


def verificar_puerto_abierto(host, puerto, timeout=1.5):
    """Devuelve True si el puerto TCP responde en el host indicado."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        resultado = sock.connect_ex((host, puerto))
        return resultado == 0


def obtener_recursos_locales(intervalo_cpu=0.1):
    """Lee CPU (%) y RAM (%) locales sin dependencias externas."""
    if _obtener_metricas_srv is not None:
        datos = _obtener_metricas_srv(intervalo_cpu=intervalo_cpu)
        return datos["cpu_porcentaje"], datos["ram_porcentaje"]

    cpu_pct, ram_pct = 0.0, 0.0
    try:
        with open("/proc/stat", "r", encoding="utf-8") as f:
            p1 = [int(v) for v in f.readline().split()[1:]]
        time.sleep(intervalo_cpu)
        with open("/proc/stat", "r", encoding="utf-8") as f:
            p2 = [int(v) for v in f.readline().split()[1:]]
        dt = sum(p2) - sum(p1)
        di = (p2[3] + (p2[4] if len(p2) > 4 else 0)) - (p1[3] + (p1[4] if len(p1) > 4 else 0))
        if dt > 0:
            cpu_pct = round(max(0.0, min(100.0, 100.0 * (1.0 - di / dt))), 1)
    except OSError:
        pass
    try:
        info = {}
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for linea in f:
                k, r = linea.split(":", 1)
                info[k] = int(r.strip().split()[0])
        tot = info["MemTotal"]
        disp = info.get("MemAvailable", info.get("MemFree", 0))
        if tot:
            ram_pct = round(100.0 * max(0, tot - disp) / tot, 1)
    except (OSError, KeyError, ValueError):
        pass
    return cpu_pct, ram_pct


def reportar_evento(url_servidor, tipo, descripcion, ruta_certificado, api_key=None):
    """Envia un POST /incidencias cifrado por HTTPS al servidor central."""
    url = f"{url_servidor.rstrip('/')}/incidencias"
    payload = {"tipo": tipo, "descripcion": descripcion}
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key

    try:
        respuesta = requests.post(
            url,
            json=payload,
            headers=headers,
            verify=ruta_certificado,
            timeout=10,
        )
        if respuesta.status_code == 201:
            print(f"[OK] Incidencia reportada al servidor (201 Created): {descripcion}")
            return True
        print(
            f"[AVISO] El servidor respondio {respuesta.status_code} "
            f"al reportar '{descripcion}': {respuesta.text}"
        )
    except requests.RequestException as exc:
        print(f"[AVISO] No se pudo conectar con {url} para reportar: {exc}")
    return False


def reportar_incidencia(url_servidor, puerto, ruta_certificado, api_key=None):
    """Envia un POST /incidencias por puerto abierto no autorizado."""
    return reportar_evento(
        url_servidor,
        "vulnerabilidad",
        f"Puerto no autorizado abierto: {puerto}",
        ruta_certificado,
        api_key=api_key,
    )


def ejecutar_escaneo(
    host,
    puertos,
    lista_blanca,
    url_servidor,
    ruta_certificado,
    api_key=None,
    puertos_previos=None,
):
    """Recorre la lista de puertos criticos y reporta los abiertos fuera de la lista blanca."""
    blanca = set(lista_blanca)
    abiertos_actuales = []

    for puerto in puertos:
        if verificar_puerto_abierto(host, puerto) and puerto not in blanca:
            abiertos_actuales.append(puerto)
            if puertos_previos is None or puerto not in puertos_previos:
                print(f"[ALERTA] Puerto no autorizado abierto detectado: {puerto}")
                reportar_incidencia(url_servidor, puerto, ruta_certificado, api_key=api_key)

    if not abiertos_actuales:
        print("[INFO] Escaneo de puertos completado: sin puertos no autorizados abiertos.")
    return abiertos_actuales


def verificar_recursos_locales(
    url_servidor,
    ruta_certificado,
    api_key=None,
    umbral_cpu=85.0,
    umbral_ram=85.0,
    simular_cpu=None,
    simular_ram=None,
    activos_previos=None,
):
    """Evalua CPU y RAM locales; reporta incidente si supera umbral (evitando duplicados en bucle)."""
    cpu_real, ram_real = obtener_recursos_locales(intervalo_cpu=0.1)
    cpu = float(simular_cpu) if simular_cpu is not None else cpu_real
    ram = float(simular_ram) if simular_ram is not None else ram_real
    previos = activos_previos or set()
    activos = set()

    if cpu >= umbral_cpu:
        activos.add("cpu")
        if "cpu" not in previos:
            desc = f"Uso critico de CPU detectado: {cpu:.1f}% (supera umbral de {umbral_cpu:g}%)"
            print(f"[ALERTA] {desc}")
            reportar_evento(url_servidor, "incidente", desc, ruta_certificado, api_key=api_key)

    if ram >= umbral_ram:
        activos.add("ram")
        if "ram" not in previos:
            desc = f"Uso critico de RAM detectado: {ram:.1f}% (supera umbral de {umbral_ram:g}%)"
            print(f"[ALERTA] {desc}")
            reportar_evento(url_servidor, "incidente", desc, ruta_certificado, api_key=api_key)

    if not activos:
        print(f"[INFO] Recursos OK (CPU: {cpu:.1f}% < {umbral_cpu:g}% | RAM: {ram:.1f}% < {umbral_ram:g}%).")
    return activos


def construir_parser():
    parser = argparse.ArgumentParser(
        description="F6 - Agente monitor de puertos TCP y recursos en la LAN."
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("BITACORA_URL", "https://127.0.0.1:8443"),
        help="URL base del servidor central (por defecto: https://127.0.0.1:8443)",
    )
    parser.add_argument(
        "--cert",
        default=os.environ.get("BITACORA_CERT", "certificado.pem"),
        help="Ruta al certificado TLS del servidor (por defecto: certificado.pem)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("BITACORA_API_KEY", ""),
        help="Clave X-API-Key opcional para autenticarse con el servidor",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host local a escanear (por defecto: 127.0.0.1)",
    )
    parser.add_argument(
        "--puertos",
        default="",
        help="Lista de puertos a vigilar separados por coma (por defecto: 21,22,23,445,3389)",
    )
    parser.add_argument(
        "--lista-blanca",
        default="",
        help="Puertos permitidos separados por coma que se ignoraran (ej. 22)",
    )
    parser.add_argument(
        "--umbral-cpu",
        type=float,
        default=85.0,
        help="Porcentaje de CPU a partir del cual se reporta incidente (por defecto: 85)",
    )
    parser.add_argument(
        "--umbral-ram",
        type=float,
        default=85.0,
        help="Porcentaje de RAM a partir del cual se reporta incidente (por defecto: 85)",
    )
    parser.add_argument(
        "--simular-cpu",
        type=float,
        default=None,
        help="Simula un porcentaje de CPU para demostracion en vivo (ej. 96)",
    )
    parser.add_argument(
        "--simular-ram",
        type=float,
        default=None,
        help="Simula un porcentaje de RAM para demostracion en vivo (ej. 92)",
    )
    parser.add_argument(
        "--intervalo",
        type=int,
        default=30,
        help="Segundos entre cada escaneo continuo (por defecto: 30)",
    )
    parser.add_argument(
        "--una-vez",
        action="store_true",
        help="Ejecuta un solo ciclo de escaneo y termina",
    )
    return parser


def main():
    parser = construir_parser()
    args = parser.parse_args()

    puertos = parsear_puertos(args.puertos) if args.puertos else PUERTOS_CRITICOS_DEFECTO
    lista_blanca = parsear_puertos(args.lista_blanca)
    api_key = args.api_key.strip() or None

    print(
        f"[INICIO] Monitoreando {args.host} | Puertos: {puertos} | "
        f"CPU>={args.umbral_cpu:g}% RAM>={args.umbral_ram:g}% | Servidor: {args.url}"
    )

    puertos_previos = set()
    recursos_previos = set()
    try:
        while True:
            abiertos = ejecutar_escaneo(
                host=args.host,
                puertos=puertos,
                lista_blanca=lista_blanca,
                url_servidor=args.url,
                ruta_certificado=args.cert,
                api_key=api_key,
                puertos_previos=puertos_previos,
            )
            puertos_previos = set(abiertos)
            recursos_previos = verificar_recursos_locales(
                url_servidor=args.url,
                ruta_certificado=args.cert,
                api_key=api_key,
                umbral_cpu=args.umbral_cpu,
                umbral_ram=args.umbral_ram,
                simular_cpu=args.simular_cpu,
                simular_ram=args.simular_ram,
                activos_previos=recursos_previos,
            )
            if args.una_vez:
                break
            time.sleep(args.intervalo)
    except KeyboardInterrupt:
        print("\n[FIN] Agente detenido por el usuario.")


if __name__ == "__main__":
    main()
