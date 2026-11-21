
"""F9 - Cliente administrativo de la bitácora."""

import argparse
import requests


class ClienteAPI:
    def __init__(self, url, certificado, api_key=None):
        self.url = url.rstrip("/")
        self.certificado = certificado
        self.cabeceras = {}

        if api_key:
            self.cabeceras["X-API-Key"] = api_key

    def solicitar(self, metodo, ruta, datos=None, params=None):
        """Envía una petición HTTPS al servidor."""
        try:
            respuesta = requests.request(
                metodo,
                f"{self.url}{ruta}",
                json=datos,
                params=params,
                headers=self.cabeceras,
                verify=self.certificado,
                timeout=10,
            )

            if respuesta.status_code == 204:
                return 204, None

            try:
                contenido = respuesta.json()
            except ValueError:
                contenido = {"respuesta": respuesta.text}

            return respuesta.status_code, contenido

        except requests.RequestException as error:
            print(f"Error de conexión: {error}")
            return None, None


def main():
    parser = argparse.ArgumentParser(
        description="Cliente administrativo de ciberseguridad"
    )
    parser.add_argument(
        "--url", default="https://localhost:8443"
    )
    parser.add_argument(
        "--cert", default="certificado.pem"
    )
    parser.add_argument("--api-key", default=None)
    args = parser.parse_args()

    cliente = ClienteAPI(args.url, args.cert, args.api_key)

    while True:
        print("\n=== CLIENTE ADMINISTRATIVO ===")
        print("1. Consultar estado del servidor")
        print("0. Salir")

        opcion = input("Selecciona una opción: ").strip()

        if opcion == "1":
            codigo, datos = cliente.solicitar("GET", "/salud")
            if codigo is not None:
                print(f"HTTP {codigo}: {datos}")
        elif opcion == "0":
            print("Cliente finalizado.")
            break
        else:
            print("Opción no válida.")


if __name__ == "__main__":
    main()
