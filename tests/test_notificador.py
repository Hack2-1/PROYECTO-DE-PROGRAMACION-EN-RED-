import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

from almacen import AlmacenBitacora  # noqa: E402
from notificador_telegram import NotificadorTelegram  # noqa: E402


def incidencia(id_, tipo="alerta", estado="abierta"):
    return {"id": id_, "tipo": tipo, "descripcion": "d", "estado": estado, "hora": "h"}


class PruebasNotificador(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.almacen = AlmacenBitacora(
            os.path.join(self.dir.name, "i.json"), os.path.join(self.dir.name, "a.json")
        )
        self.notificador = NotificadorTelegram("TOKEN-SECRETO", "123", self.almacen)

    def tearDown(self):
        self.dir.cleanup()

    @mock.patch("notificador_telegram.requests.post")
    def test_bajo_umbral_no_envia_ni_registra(self, post):
        lista = [incidencia(1), incidencia(2)]
        r = self.notificador.evaluar_umbral_telegram(lista[-1], lista)
        self.assertFalse(r["alerta"])
        post.assert_not_called()
        self.assertEqual(self.almacen.cargar_alertas(), [])

    @mock.patch("notificador_telegram.requests.post")
    def test_incidente_critico_dispara_directo(self, post):
        post.return_value.status_code = 200
        nueva = incidencia(1, tipo="incidente")
        r = self.notificador.evaluar_umbral_telegram(nueva, [nueva])
        self.assertTrue(r["alerta"])
        self.assertEqual(r["estado_envio"], "ENVIADO")
        self.assertEqual(r["motivo"], "UMBRAL_CRITICO_DIRECTO (1/1)")
        self.assertEqual(r["codigo_http"], 200)
        self.assertEqual(post.call_args.kwargs["timeout"], 5)
        self.assertEqual(len(self.almacen.cargar_alertas()), 1)

    @mock.patch("notificador_telegram.requests.post")
    def test_acumulacion_de_tres_abiertas(self, post):
        post.return_value.status_code = 200
        lista = [incidencia(1), incidencia(2), incidencia(3)]
        r = self.notificador.evaluar_umbral_telegram(lista[-1], lista)
        self.assertTrue(r["motivo"].startswith("UMBRAL_ACUMULACION (3 abiertas"))

    @mock.patch("notificador_telegram.requests.post")
    def test_resueltas_no_cuentan_para_acumulacion(self, post):
        lista = [incidencia(1), incidencia(2, estado="resuelta"), incidencia(3)]
        r = self.notificador.evaluar_umbral_telegram(lista[-1], lista)
        self.assertFalse(r["alerta"])

    @mock.patch("notificador_telegram.requests.post")
    def test_sin_internet_registra_fallido_sin_filtrar_token(self, post):
        post.side_effect = requests.ConnectionError("https://api.telegram.org/botTOKEN-SECRETO/sendMessage")
        nueva = incidencia(1, tipo="incidente")
        r = self.notificador.evaluar_umbral_telegram(nueva, [nueva])
        self.assertEqual(r["estado_envio"], "FALLIDO_SIN_INTERNET")
        self.assertEqual(r["codigo_http"], 503)
        guardado = self.almacen.cargar_alertas()
        self.assertEqual(len(guardado), 1)
        self.assertNotIn("TOKEN-SECRETO", str(guardado))

    @mock.patch("notificador_telegram.requests.post")
    def test_error_api(self, post):
        post.return_value.status_code = 401
        nueva = incidencia(1, tipo="incidente")
        r = self.notificador.evaluar_umbral_telegram(nueva, [nueva])
        self.assertEqual((r["estado_envio"], r["codigo_http"]), ("ERROR_API", 401))

    @mock.patch("notificador_telegram.requests.post")
    def test_sin_credenciales_no_hace_peticion(self, post):
        sin = NotificadorTelegram("", "", self.almacen)
        nueva = incidencia(1, tipo="incidente")
        r = sin.evaluar_umbral_telegram(nueva, [nueva])
        self.assertEqual(r["estado_envio"], "SIN_CREDENCIALES")
        post.assert_not_called()

    def test_nunca_lanza_excepciones(self):
        r = self.notificador.evaluar_umbral_telegram(None, [])
        self.assertFalse(r["alerta"])


if __name__ == "__main__":
    unittest.main()
