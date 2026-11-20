import os
import socket
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import requests  # noqa: E402

from almacen import AlmacenBitacora  # noqa: E402
from generar_certificados import generar  # noqa: E402
from notificador_telegram import NotificadorTelegram  # noqa: E402
from servidor_bitacora import ServidorBitacoraHTTPS, crear_contexto_tls  # noqa: E402


class PruebasServidorTLS(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.cert, cls.llave, _ = generar(cls.dir.name)
        cls.almacen = AlmacenBitacora(
            os.path.join(cls.dir.name, "i.json"), os.path.join(cls.dir.name, "a.json")
        )
        notificador = NotificadorTelegram("", "", cls.almacen)
        cls.servidor = ServidorBitacoraHTTPS(
            ("127.0.0.1", 0), cls.almacen, notificador, crear_contexto_tls(cls.cert, cls.llave)
        )
        cls.puerto = cls.servidor.server_address[1]
        cls.hilo = threading.Thread(target=cls.servidor.serve_forever, daemon=True)
        cls.hilo.start()
        cls.base = "https://127.0.0.1:%d" % cls.puerto

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()
        cls.servidor.server_close()
        cls.dir.cleanup()

    def test_salud_por_https_con_certificado_verificado(self):
        r = requests.get(self.base + "/salud", verify=self.cert, timeout=10)
        self.assertEqual(r.status_code, 200)
        cuerpo = r.json()
        self.assertTrue(cuerpo["tls"])
        self.assertTrue(cuerpo["version_tls"].startswith("TLS"))

    def test_http_plano_es_rechazado_y_registrado(self):
        antes = len([l for l in self.almacen.obtener_logs() if l["tipo"] == "TLS_RECHAZADO"])
        with socket.create_connection(("127.0.0.1", self.puerto), timeout=5) as s:
            s.sendall(b"GET /salud HTTP/1.1\r\nHost: x\r\n\r\n")
            try:
                s.recv(1024)
            except OSError:
                pass
        for _ in range(30):
            ahora = len([l for l in self.almacen.obtener_logs() if l["tipo"] == "TLS_RECHAZADO"])
            if ahora > antes:
                break
            time.sleep(0.1)
        self.assertGreater(ahora, antes)

    def test_ruta_inexistente_404_y_stubs_501(self):
        self.assertEqual(requests.get(self.base + "/nada", verify=self.cert, timeout=10).status_code, 404)
        self.assertEqual(requests.get(self.base + "/incidencias", verify=self.cert, timeout=10).status_code, 501)
        self.assertEqual(requests.post(self.base + "/incidencias", json={}, verify=self.cert, timeout=10).status_code, 501)

    def test_auditoria_automatica_cuenta_peticiones(self):
        antes = self.almacen.obtener_contadores()["por_metodo"].get("GET", 0)
        requests.get(self.base + "/salud", verify=self.cert, timeout=10)
        self.assertEqual(self.almacen.obtener_contadores()["por_metodo"]["GET"], antes + 1)

    def test_clientes_concurrentes(self):
        codigos = []

        def cliente():
            codigos.append(requests.get(self.base + "/salud", verify=self.cert, timeout=10).status_code)

        hilos = [threading.Thread(target=cliente) for _ in range(6)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        self.assertEqual(codigos, [200] * 6)

    def test_desconexion_abrupta_no_tumba_el_servidor(self):
        s = socket.create_connection(("127.0.0.1", self.puerto), timeout=5)
        s.close()
        r = requests.get(self.base + "/salud", verify=self.cert, timeout=10)
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()
