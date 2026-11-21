"""F6 - Agente monitor de puertos TCP en la LAN (Rodrigo Garcia).

Implementa el Algoritmo 3: sondea puertos criticos locales mediante sockets TCP
y reporta puertos abiertos no autorizados por HTTPS al servidor central.
"""

import argparse
import os
import socket
import time

import requests

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


def reportar_incidencia(url_servidor, puerto, ruta_certificado, api_key=None):
    """Envia un POST /incidencias cifrado por HTTPS al servidor central."""
    url = f"{url_servidor.rstrip('/')}/incidencias"
    payload = {
        "tipo": "vulnerabilidad",
        "descripcion": f"Puerto no autorizado abierto: {puerto}",
    }
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
            print(f"[OK] Puerto {puerto} reportado al servidor (201 Created).")
        else:
            print(
                f"[AVISO] El servidor respondio {respuesta.status_code} "
                f"al reportar puerto {puerto}: {respuesta.text}"
            )
    except requests.RequestException as exc:
        print(
            f"[AVISO] No se pudo conectar con {url} para reportar puerto {puerto}: {exc}"
        )


def ejecutar_escaneo(host, puertos, lista_blanca, url_servidor, ruta_certificado, api_key=None):
    """Recorre la lista de puertos criticos y reporta los abiertos fuera de la lista blanca."""
    blanca = set(lista_blanca)
    abiertos_reportados = []

    for puerto in puertos:
        if verificar_puerto_abierto(host, puerto) and puerto not in blanca:
            print(f"[ALERTA] Puerto no autorizado abierto detectado: {puerto}")
            reportar_incidencia(url_servidor, puerto, ruta_certificado, api_key=api_key)
            abiertos_reportados.append(puerto)

    if not abiertos_reportados:
        print("[INFO] Escaneo completado: sin puertos no autorizados abiertos.")
    return abiertos_reportados


def construir_parser():
    parser = argparse.ArgumentParser(
        description="F6 - Agente monitor de puertos TCP en la LAN."
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
        f"Lista blanca: {lista_blanca} | Servidor: {args.url}"
    )

    try:
        while True:
            ejecutar_escaneo(
                host=args.host,
                puertos=puertos,
                lista_blanca=lista_blanca,
                url_servidor=args.url,
                ruta_certificado=args.cert,
                api_key=api_key,
            )
            if args.una_vez:
                break
            time.sleep(args.intervalo)
    except KeyboardInterrupt:
        print("\n[FIN] Agente detenido por el usuario.")


if __name__ == "__main__":
    main()