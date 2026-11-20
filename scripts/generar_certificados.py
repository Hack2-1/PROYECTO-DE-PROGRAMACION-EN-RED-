"""Genera certificado.pem y llave.pem autofirmados (con SAN) usando OpenSSL.

Uso: python3 scripts/generar_certificados.py [--ip 192.168.1.50 ...] [--dias 365] [--force]
"""

import argparse
import os
import socket
import subprocess
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ip_lan():
    """IP de la interfaz de salida (no envia paquetes: UDP connect)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def generar(directorio, ips_extra=(), dias=365, force=False):
    cert = os.path.join(directorio, "certificado.pem")
    llave = os.path.join(directorio, "llave.pem")
    if (os.path.exists(cert) or os.path.exists(llave)) and not force:
        raise FileExistsError("Ya existen certificado.pem/llave.pem (usa --force para regenerar)")
    ips = ["127.0.0.1"]
    for ip in (ip_lan(), *ips_extra):
        if ip and ip not in ips:
            ips.append(ip)
    san = ",".join(["DNS:localhost"] + ["IP:%s" % ip for ip in ips])
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", llave, "-out", cert, "-days", str(dias),
            "-subj", "/CN=bitacora-equipo-01/O=Equipo 01",
            "-addext", "subjectAltName=" + san,
        ],
        check=True,
        capture_output=True,
    )
    os.chmod(llave, 0o600)
    return cert, llave, san


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ip", action="append", default=[], help="IP adicional para el SAN")
    parser.add_argument("--dias", type=int, default=365)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        cert, llave, san = generar(RAIZ, args.ip, args.dias, args.force)
    except FileExistsError as exc:
        print(exc, file=sys.stderr)
        return 1
    except FileNotFoundError:
        print("OpenSSL no esta instalado.", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print("OpenSSL fallo: %s" % exc.stderr.decode(errors="replace"), file=sys.stderr)
        return 1
    print("Generados:\n  %s\n  %s\nSAN: %s" % (cert, llave, san))
    return 0


if __name__ == "__main__":
    sys.exit(main())
