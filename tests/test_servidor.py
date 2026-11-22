import io
import os
import socket
import sys
import tempfile
import threading
import time
import unittest

from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import requests  # noqa: E402

from almacen import AlmacenBitacora  # noqa: E402
from agente_puertos import ejecutar_escaneo, verificar_recursos_locales  # noqa: E402
from cliente_admin import ClienteAPI  # noqa: E402
from cliente_pruebas_alertas import (  # noqa: E402
    escenario_acumulacion_tres_abiertas,
    escenario_puerto_no_autorizado,
    escenario_umbral_cpu,
    obtener_evidencia_alertas,
)
from generar_certificados import generar  # noqa: E402
from manejador_http import ManejadorBitacora  # noqa: E402
from notificador_telegram import NotificadorTelegram  # noqa: E402
from servidor_bitacora import (  # noqa: E402
    MonitorRecursosServidor,
    ServidorBitacoraHTTPS,
    construir_parser,
    crear_contexto_tls,
    main as servidor_main,
)
from web_tienda import ServidorWebTienda  # noqa: E402


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
        self.assertIn("recursos", cuerpo)
        for campo in ("cpu_porcentaje", "ram_porcentaje", "disco_porcentaje"):
            self.assertIn(campo, cuerpo["recursos"])

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

    def test_ruta_inexistente_404(self):
        self.assertEqual(requests.get(self.base + "/nada", verify=self.cert, timeout=10).status_code, 404)
        self.assertEqual(requests.post(self.base + "/nada", json={}, verify=self.cert, timeout=10).status_code, 404)

    def test_flujo_crud_y_auditoria_completo(self):
        # F4: POST invalido -> 400; valido -> 201 (incidente dispara umbral -> SIN_CREDENCIALES)
        self.assertEqual(
            requests.post(self.base + "/incidencias", json={}, verify=self.cert, timeout=10).status_code,
            400,
        )
        r1 = requests.post(
            self.base + "/incidencias",
            json={"tipo": "vulnerabilidad", "descripcion": "Puerto 23 abierto"},
            verify=self.cert,
            timeout=10,
        )
        self.assertEqual(r1.status_code, 201)
        id1 = r1.json()["id"]

        r2 = requests.post(
            self.base + "/incidencias",
            json={"tipo": "incidente", "descripcion": "Acceso no autorizado"},
            verify=self.cert,
            timeout=10,
        )
        self.assertEqual(r2.status_code, 201)
        id2 = r2.json()["id"]

        # F5: GET con filtros y detalle por ID
        r_list = requests.get(
            self.base + "/incidencias?tipo=vulnerabilidad&estado=abierta",
            verify=self.cert,
            timeout=10,
        )
        self.assertEqual(r_list.status_code, 200)
        self.assertTrue(any(i["id"] == id1 for i in r_list.json()))
        self.assertEqual(
            requests.get(f"{self.base}/incidencias/{id2}", verify=self.cert, timeout=10).status_code,
            200,
        )
        self.assertEqual(
            requests.get(self.base + "/incidencias/abc", verify=self.cert, timeout=10).status_code,
            400,
        )
        self.assertEqual(
            requests.get(self.base + "/incidencias/99999", verify=self.cert, timeout=10).status_code,
            404,
        )

        # F7: PATCH estado y PUT reemplazo completo
        self.assertEqual(
            requests.patch(
                f"{self.base}/incidencias/{id1}",
                json={"estado": "invalido"},
                verify=self.cert,
                timeout=10,
            ).status_code,
            400,
        )
        r_patch = requests.patch(
            f"{self.base}/incidencias/{id1}",
            json={"estado": "en_proceso"},
            verify=self.cert,
            timeout=10,
        )
        self.assertEqual(r_patch.status_code, 200)
        self.assertEqual(r_patch.json()["estado"], "en_proceso")

        r_put = requests.put(
            f"{self.base}/incidencias/{id1}",
            json={"tipo": "alerta", "descripcion": "Actualizada"},
            verify=self.cert,
            timeout=10,
        )
        self.assertEqual(r_put.status_code, 200)
        self.assertEqual(r_put.json()["estado"], "abierta")

        # F8: Auditoria y DELETE
        self.assertEqual(requests.get(self.base + "/logs", verify=self.cert, timeout=10).status_code, 200)
        self.assertEqual(requests.get(self.base + "/contadores", verify=self.cert, timeout=10).status_code, 200)
        r_alertas = requests.get(self.base + "/alertas", verify=self.cert, timeout=10)
        self.assertEqual(r_alertas.status_code, 200)
        self.assertTrue(any(a.get("incidencia_id") == id2 for a in r_alertas.json()))

        self.assertEqual(
            requests.delete(f"{self.base}/incidencias/{id1}", verify=self.cert, timeout=10).status_code,
            204,
        )
        self.assertEqual(
            requests.get(f"{self.base}/incidencias/{id1}", verify=self.cert, timeout=10).status_code,
            404,
        )
        self.assertEqual(
            requests.delete(f"{self.base}/incidencias/{id2}", verify=self.cert, timeout=10).status_code,
            204,
        )

    def test_integracion_agente_puertos_y_cliente_admin(self):
        # F6: socket TCP abierto simulado -> agente_puertos reporta por HTTPS con X-API-Key
        with tempfile.TemporaryDirectory() as tmp:
            almacen_e2e = AlmacenBitacora(
                os.path.join(tmp, "i_e2e.json"),
                os.path.join(tmp, "a_e2e.json"),
            )
            srv = ServidorBitacoraHTTPS(
                ("127.0.0.1", 0),
                almacen_e2e,
                NotificadorTelegram("", "", almacen_e2e),
                crear_contexto_tls(self.cert, self.llave),
                api_keys={"llave-equipo-01"},
            )
            hilo = threading.Thread(target=srv.serve_forever, daemon=True)
            hilo.start()
            escucha = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            escucha.bind(("127.0.0.1", 0))
            escucha.listen(1)
            puerto_abierto = escucha.getsockname()[1]
            try:
                url = "https://127.0.0.1:%d" % srv.server_address[1]
                detectados = ejecutar_escaneo(
                    host="127.0.0.1",
                    puertos=[puerto_abierto],
                    lista_blanca=[],
                    url_servidor=url,
                    ruta_certificado=self.cert,
                    api_key="llave-equipo-01",
                )
                self.assertEqual(detectados, [puerto_abierto])

                # F9: ClienteAPI autenticado consulta y cierra la incidencia detectada por F6
                cliente = ClienteAPI(url, self.cert, api_key="llave-equipo-01")
                cod, lista = cliente.solicitar("GET", "/incidencias")
                self.assertEqual(cod, 200)
                self.assertEqual(len(lista), 1)
                self.assertIn(str(puerto_abierto), lista[0]["descripcion"])

                cod_patch, actualizada = cliente.solicitar(
                    "PATCH", f"/incidencias/{lista[0]['id']}", {"estado": "resuelta"}
                )
                self.assertEqual(cod_patch, 200)
                self.assertEqual(actualizada["estado"], "resuelta")
            finally:
                escucha.close()
                srv.shutdown()
                srv.server_close()

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

    def test_verificar_api_key_401_y_200(self):
        class ManejadorProtegido(ManejadorBitacora):
            def do_POST(self):
                if not self._verificar_api_key():
                    return
                self._enviar_json(200, {"autorizado": True})

        with tempfile.TemporaryDirectory() as tmp:
            almacen_auth = AlmacenBitacora(
                os.path.join(tmp, "i_auth.json"),
                os.path.join(tmp, "a_auth.json"),
            )
            srv = ServidorBitacoraHTTPS(
                ("127.0.0.1", 0),
                almacen_auth,
                NotificadorTelegram("", "", almacen_auth),
                crear_contexto_tls(self.cert, self.llave),
                manejador=ManejadorProtegido,
                api_keys={"clave-secreta-01"},
            )
            hilo = threading.Thread(target=srv.serve_forever, daemon=True)
            hilo.start()
            try:
                url = "https://127.0.0.1:%d/incidencias" % srv.server_address[1]
                r_sin = requests.post(url, json={}, verify=self.cert, timeout=10)
                self.assertEqual(r_sin.status_code, 401)
                r_mal = requests.post(
                    url, json={}, headers={"X-API-Key": "incorrecta"}, verify=self.cert, timeout=10
                )
                self.assertEqual(r_mal.status_code, 401)
                r_ok = requests.post(
                    url, json={}, headers={"X-API-Key": "clave-secreta-01"}, verify=self.cert, timeout=10
                )
                self.assertEqual(r_ok.status_code, 200)
                self.assertTrue(r_ok.json()["autorizado"])
                rechazos = [l for l in almacen_auth.obtener_logs() if l["tipo"] == "API_KEY_RECHAZADA"]
                self.assertEqual(len(rechazos), 2)
            finally:
                srv.shutdown()
                srv.server_close()

    def test_monitor_recursos_cpu_ram_crea_incidencia_y_alerta(self):
        with tempfile.TemporaryDirectory() as tmp:
            almacen_mon = AlmacenBitacora(
                os.path.join(tmp, "i_mon.json"),
                os.path.join(tmp, "a_mon.json"),
            )
            notificador_mon = NotificadorTelegram("", "", almacen_mon)
            monitor = MonitorRecursosServidor(
                almacen_mon, notificador_mon, umbral_cpu=85, umbral_ram=85, umbral_disco=90
            )

            creadas = monitor.evaluar_una_vez(
                {"cpu_porcentaje": 96.0, "ram_porcentaje": 91.5, "disco_porcentaje": 50.0}
            )
            self.assertEqual(len(creadas), 2)
            self.assertIn("96.0%", creadas[0]["descripcion"])
            self.assertIn("91.5%", creadas[1]["descripcion"])
            self.assertEqual(len(almacen_mon.cargar_alertas()), 2)

            # Segundo ciclo con las mismas incidencias abiertas: no duplica
            repetidas = monitor.evaluar_una_vez(
                {"cpu_porcentaje": 96.0, "ram_porcentaje": 91.5, "disco_porcentaje": 50.0}
            )
            self.assertEqual(repetidas, [])
            self.assertEqual(len(almacen_mon.listar_incidencias()), 2)

            # Al resolver CPU, una nueva alza vuelve a generar incidencia
            almacen_mon.actualizar_estado(creadas[0]["id"], "resuelta")
            almacen_mon.registrar_evento("TLS_RECHAZADO", "10.0.0.5", "HTTP plano")
            nuevas = monitor.evaluar_una_vez(
                {"cpu_porcentaje": 97.0, "ram_porcentaje": 40.0, "disco_porcentaje": 50.0}
            )
            self.assertEqual(len(nuevas), 2)
            self.assertTrue(any("97.0%" in i["descripcion"] for i in nuevas))
            self.assertTrue(any("Alteracion de seguridad" in i["descripcion"] for i in nuevas))

            # Verificar persistencia en SQLite por fecha actual
            hoy = creadas[0]["hora"][:10]
            resumen = almacen_mon.resumen_por_fecha(hoy)
            self.assertEqual(resumen["total"], 4)
            self.assertEqual(resumen["total_alertas"], 4)

    def test_agente_simula_cpu_96_por_https(self):
        activos = verificar_recursos_locales(
            url_servidor=self.base,
            ruta_certificado=self.cert,
            umbral_cpu=85.0,
            umbral_ram=85.0,
            simular_cpu=96.0,
            simular_ram=30.0,
        )
        self.assertEqual(activos, {"cpu"})
        incidencias = self.almacen.listar_incidencias(tipo="incidente")
        self.assertTrue(any("96.0%" in i["descripcion"] for i in incidencias))
        for inc in incidencias:
            if "96.0%" in inc["descripcion"]:
                self.almacen.eliminar_incidencia(inc["id"])

    def test_cliente_pruebas_alertas_levanta_evidencia(self):
        with tempfile.TemporaryDirectory() as tmp:
            almacen_pr = AlmacenBitacora(
                os.path.join(tmp, "i_pr.json"),
                os.path.join(tmp, "a_pr.json"),
            )
            srv = ServidorBitacoraHTTPS(
                ("127.0.0.1", 0),
                almacen_pr,
                NotificadorTelegram("", "", almacen_pr),
                crear_contexto_tls(self.cert, self.llave),
            )
            hilo = threading.Thread(target=srv.serve_forever, daemon=True)
            hilo.start()
            try:
                url = "https://127.0.0.1:%d" % srv.server_address[1]
                cod_cpu, inc_cpu = escenario_umbral_cpu(url, self.cert, porcentaje=96.0)
                self.assertEqual(cod_cpu, 201)
                self.assertIn("96.0%", inc_cpu["descripcion"])

                resultados = escenario_acumulacion_tres_abiertas(url, self.cert)
                self.assertEqual([r[0] for r in resultados], [201, 201, 201])

                detectados = escenario_puerto_no_autorizado(url, self.cert)
                self.assertEqual(len(detectados), 1)

                evidencia = obtener_evidencia_alertas(url, self.cert)
                self.assertEqual(len(evidencia["incidencias"]), 5)
                self.assertTrue(
                    any(
                        f"Puerto no autorizado abierto: {detectados[0]}" in i["descripcion"]
                        for i in evidencia["incidencias"]
                    )
                )
                self.assertGreaterEqual(len(evidencia["alertas"]), 2)
                self.assertEqual(
                    evidencia["alertas"][0]["motivo"],
                    "UMBRAL_CRITICO_DIRECTO (1/1)",
                )
                self.assertTrue(
                    any(
                        str(a.get("motivo", "")).startswith("UMBRAL_ACUMULACION")
                        for a in evidencia["alertas"]
                    )
                )
            finally:
                srv.shutdown()
                srv.server_close()

    def test_puerto_configurable_y_aviso_si_esta_en_uso(self):
        args = construir_parser().parse_args(["--host", "127.0.0.1", "--puerto", "8444"])
        self.assertEqual((args.host, args.puerto), ("127.0.0.1", 8444))

        salida_err = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch("servidor_bitacora.config.RUTA_CERTIFICADO", self.cert), \
             mock.patch("servidor_bitacora.config.RUTA_LLAVE", self.llave), \
             mock.patch("servidor_bitacora.config.RUTA_INCIDENCIAS", os.path.join(tmp, "i.json")), \
             mock.patch("servidor_bitacora.config.RUTA_ALERTAS", os.path.join(tmp, "a.json")), \
             mock.patch("sys.stderr", salida_err):
            codigo = servidor_main(["--host", "127.0.0.1", "--puerto", str(self.puerto)])
        self.assertEqual(codigo, 1)
        self.assertIn("ya esta en uso", salida_err.getvalue())
        self.assertIn("--puerto", salida_err.getvalue())

    def test_web_tienda_sirve_portal_y_evidencias_fernanda(self):
        with tempfile.TemporaryDirectory() as tmp:
            almacen_web = AlmacenBitacora(
                os.path.join(tmp, "i_web.json"),
                os.path.join(tmp, "a_web.json"),
            )
            srv_https = ServidorBitacoraHTTPS(
                ("127.0.0.1", 0),
                almacen_web,
                NotificadorTelegram("", "", almacen_web),
                crear_contexto_tls(self.cert, self.llave),
            )
            hilo_https = threading.Thread(target=srv_https.serve_forever, daemon=True)
            hilo_https.start()

            url_https = "https://127.0.0.1:%d" % srv_https.server_address[1]
            srv_web = ServidorWebTienda(("127.0.0.1", 0), url_https, self.cert)
            hilo_web = threading.Thread(target=srv_web.serve_forever, daemon=True)
            hilo_web.start()
            base_web = "http://127.0.0.1:%d" % srv_web.server_address[1]
            try:
                html = requests.get(base_web + "/", timeout=10)
                self.assertEqual(html.status_code, 200)
                self.assertIn("Apartado de Evidencias", html.text)
                self.assertIn("FERNANDA", html.text)
                self.assertEqual(requests.get(base_web + "/estilos.css", timeout=10).status_code, 200)
                self.assertEqual(requests.get(base_web + "/app.js", timeout=10).status_code, 200)

                r_post = requests.post(
                    base_web + "/api/incidencias",
                    json={"tipo": "alerta", "descripcion": "Prueba desde portal"},
                    timeout=10,
                )
                self.assertEqual(r_post.status_code, 201)
                inc_id = r_post.json()["id"]

                r_patch = requests.patch(
                    f"{base_web}/api/incidencias/{inc_id}",
                    json={"estado": "resuelta"},
                    timeout=10,
                )
                self.assertEqual(r_patch.status_code, 200)
                self.assertEqual(r_patch.json()["estado"], "resuelta")

                r_put = requests.put(
                    f"{base_web}/api/incidencias/{inc_id}",
                    json={"tipo": "vulnerabilidad", "descripcion": "Reemplazada PUT"},
                    timeout=10,
                )
                self.assertEqual(r_put.status_code, 200)
                self.assertEqual(r_put.json()["estado"], "abierta")

                r_estado = requests.get(base_web + "/api/estado", timeout=10)
                self.assertEqual(r_estado.status_code, 200)
                self.assertTrue(r_estado.json()["conectado"])
                self.assertEqual(len(r_estado.json()["incidencias"]), 1)

                r_conc = requests.post(base_web + "/api/evidencia/concurrencia", timeout=10)
                self.assertEqual(r_conc.status_code, 200)
                self.assertTrue(r_conc.json()["exito"])
                self.assertEqual(r_conc.json()["codigos"], [200, 200, 200])

                r_tol = requests.post(base_web + "/api/evidencia/tolerancia", timeout=10)
                self.assertEqual(r_tol.status_code, 200)
                self.assertTrue(r_tol.json()["exito"])
                self.assertEqual(r_tol.json()["salud_posterior"], 200)

                r_del = requests.delete(f"{base_web}/api/incidencias/{inc_id}", timeout=10)
                self.assertEqual(r_del.status_code, 204)
            finally:
                srv_web.shutdown()
                srv_web.server_close()
                srv_https.shutdown()
                srv_https.server_close()


if __name__ == "__main__":
    unittest.main()
