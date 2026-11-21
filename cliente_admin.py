
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
    parser.add_argument("--url", default="https://localhost:8443")
    parser.add_argument("--cert", default="certificado.pem")
    parser.add_argument("--api-key", default=None)
    args = parser.parse_args()

    cliente = ClienteAPI(args.url, args.cert, args.api_key)

    while True:
        print("\n=== CLIENTE ADMINISTRATIVO ===")
        print("1. Estado del servidor y TLS")
        print("2. Registrar incidencia")
        print("3. Listar incidencias")
        print("4. Consultar incidencia por ID")
        print("5. Cambiar estado (PATCH)")
        print("6. Reemplazar incidencia (PUT)")
        print("7. Eliminar incidencia (DELETE)")
        print("8. Consultar auditoria")
        print("0. Salir")

        opcion = input("Opcion: ").strip()

        if opcion == "0":
            print("Cliente finalizado.")
            break

        elif opcion == "1":
            codigo, datos = cliente.solicitar("GET", "/salud")

        elif opcion == "2":
            tipo = input("Tipo: ").strip()
            descripcion = input("Descripcion: ").strip()
            codigo, datos = cliente.solicitar(
                "POST", "/incidencias",
                {"tipo": tipo, "descripcion": descripcion}
            )

        elif opcion == "3":
            tipo = input("Filtrar por tipo (Enter para todos): ").strip()
            estado = input("Filtrar por estado (Enter para todos): ").strip()
            filtros = {}
            if tipo:
                filtros["tipo"] = tipo
            if estado:
                filtros["estado"] = estado
            codigo, datos = cliente.solicitar(
                "GET", "/incidencias", params=filtros
            )

        elif opcion in ("4", "5", "6", "7"):
            identificador = input("ID de incidencia: ").strip()
            if not identificador.isdigit() or int(identificador) <= 0:
                print("El ID debe ser un entero positivo.")
                continue

            ruta = f"/incidencias/{identificador}"

            if opcion == "4":
                codigo, datos = cliente.solicitar("GET", ruta)

            elif opcion == "5":
                estado = input(
                    "Nuevo estado (abierta/en_proceso/resuelta): "
                ).strip()
                codigo, datos = cliente.solicitar(
                    "PATCH", ruta, {"estado": estado}
                )

            elif opcion == "6":
                tipo = input("Nuevo tipo: ").strip()
                descripcion = input("Nueva descripcion: ").strip()
                codigo, datos = cliente.solicitar(
                    "PUT", ruta,
                    {"tipo": tipo, "descripcion": descripcion}
                )

            else:
                confirmar = input("Confirmar eliminacion (s/n): ").strip()
                if confirmar.lower() != "s":
                    print("Operacion cancelada.")
                    continue
                codigo, datos = cliente.solicitar("DELETE", ruta)

        elif opcion == "8":
            for ruta in ("/logs", "/contadores", "/alertas"):
                codigo, datos = cliente.solicitar("GET", ruta)
                print(f"\n{ruta}: HTTP {codigo}")
                print(datos)
            continue

        else:
            print("Opcion no valida.")
            continue

        if codigo is not None:
            print(f"\nHTTP {codigo}")
            if codigo == 204:
                print("Operacion completada sin contenido.")
            else:
                print(datos)

if __name__ == "__main__":
    main()
