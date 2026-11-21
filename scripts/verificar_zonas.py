"""Verifica que las ramas de equipo respeten las zonas de archivos permitidas.

Uso:
    python3 scripts/verificar_zonas.py [rama ...]
"""

import argparse
import os
import subprocess
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ARCHIVOS_PROTEGIDOS_EDDI = {
    "servidor_bitacora.py",
    "almacen.py",
    "notificador_telegram.py",
    "config.py",
    "scripts/generar_certificados.py",
}

PERMITIDOS_POR_RAMA = {
    "feature/registro-consultas-agente": {"manejador_http.py", "agente_puertos.py"},
    "feature/gestion-auditoria-cliente": {"manejador_http.py", "cliente_admin.py"},
}


def _git(*args):
    return subprocess.run(
        ["git", *args],
        cwd=RAIZ,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _es_permitido(ruta, permitidos):
    if ruta in permitidos:
        return True
    return ruta.startswith("tests/") and ruta not in ARCHIVOS_PROTEGIDOS_EDDI


def verificar_rama(rama, base="main"):
    """Devuelve lista de archivos no permitidos modificados en la rama respecto a base."""
    permitidos = PERMITIDOS_POR_RAMA.get(rama)
    if permitidos is None:
        raise ValueError("Rama sin reglas configuradas: %s" % rama)

    salida = _git("diff", "--name-only", "%s...%s" % (base, rama))
    cambiados = [linea.strip() for linea in salida.splitlines() if linea.strip()]

    violaciones = []
    for ruta in cambiados:
        if ruta in ARCHIVOS_PROTEGIDOS_EDDI:
            violaciones.append((ruta, "archivo protegido de Eddi Michael"))
        elif not _es_permitido(ruta, permitidos):
            violaciones.append((ruta, "fuera de la zona asignada para %s" % rama))
    return cambiados, violaciones


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ramas", nargs="*", help="Ramas a verificar (por defecto todas las de integrantes)")
    parser.add_argument("--base", default="main", help="Rama base de comparacion (por defecto main)")
    args = parser.parse_args()

    ramas = args.ramas or list(PERMITIDOS_POR_RAMA.keys())
    hay_error = False

    for rama in ramas:
        try:
            cambiados, violaciones = verificar_rama(rama, base=args.base)
        except subprocess.CalledProcessError as exc:
            print("[ERROR] No se pudo verificar '%s': %s" % (rama, exc.stderr.strip()), file=sys.stderr)
            hay_error = True
            continue
        except ValueError as exc:
            print("[ERROR] %s" % exc, file=sys.stderr)
            hay_error = True
            continue

        if violaciones:
            hay_error = True
            print("[RECHAZADA] %s:" % rama)
            for ruta, motivo in violaciones:
                print("  - %s (%s)" % (ruta, motivo))
        else:
            resumen = "%d archivo(s) en zona valida" % len(cambiados) if cambiados else "sin cambios respecto a %s" % args.base
            print("[OK] %s (%s)" % (rama, resumen))

    return 1 if hay_error else 0


if __name__ == "__main__":
    sys.exit(main())
