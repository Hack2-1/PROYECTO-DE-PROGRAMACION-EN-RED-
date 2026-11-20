import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

from almacen import AlmacenBitacora  # noqa: E402
from bot_comandos import BotComandos, ErrorTelegram  # noqa: E402


def actualizacion(update_id, chat_id, texto):
    return {"update_id": update_id, "message": {"chat": {"id": chat_id}, "text": texto}}


class PruebasBotComandos(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.almacen = AlmacenBitacora(
            os.path.join(self.dir.name, "i.json"), os.path.join(self.dir.name, "a.json")
        )
        self.bot = BotComandos("TOKEN", ["111"], self.almacen, {"puerto": 8443})

    def tearDown(self):
        self.dir.cleanup()

    def test_estado_muestra_servidor_activo_y_conteos(self):
        self.almacen.crear_incidencia("alerta", "a")
        self.almacen.crear_incidencia("alerta", "b", estado="resuelta")
        self.almacen.registrar_peticion("GET", "/salud", 200, "x")
        self.almacen.registrar_evento("TLS_RECHAZADO", "x", "d")
        r = self.bot.procesar_comando("/estado")
        self.assertIn("ACTIVO", r)
        self.assertIn("8443", r)
        self.assertIn("1 abiertas, 0 en proceso, 1 resueltas", r)
        self.assertIn("2xx: 1", r)
        self.assertIn("Rechazos TLS recientes: 1", r)

    def test_incidencias_lista_ultimas_abiertas(self):
        for n in range(7):
            self.almacen.crear_incidencia("vulnerabilidad", "puerto %d" % n)
        r = self.bot.procesar_comando("/incidencias")
        self.assertIn("7 abiertas", r)
        self.assertIn("#7", r)
        self.assertNotIn("#2 ", r)  # solo las ultimas 5

    def test_incidencias_y_alertas_vacias(self):
        self.assertIn("No hay incidencias abiertas", self.bot.procesar_comando("/incidencias"))
        self.assertIn("Aun no se han enviado alertas", self.bot.procesar_comando("/alertas"))
        self.assertIn("Aun no hay peticiones", self.bot.procesar_comando("/contadores"))

    def test_contadores_y_alertas(self):
        self.almacen.registrar_peticion("POST", "/incidencias", 201, "x")
        self.almacen.registrar_peticion("GET", "/zzz", 404, "x")
        r = self.bot.procesar_comando("/contadores")
        self.assertIn("POST: 1", r)
        self.assertIn("4xx: 1", r)
        self.almacen.registrar_alerta({"incidencia_id": 3, "motivo": "M", "estado_envio": "ENVIADO"})
        self.assertIn("ENVIADO", self.bot.procesar_comando("/alertas"))

    def test_comando_con_arroba_ayuda_y_desconocido(self):
        self.assertIn("/estado", self.bot.procesar_comando("/ayuda"))
        self.assertIn("/estado", self.bot.procesar_comando("/Start@mi_bot"))
        self.assertIn("no reconocido", self.bot.procesar_comando("/borrar"))

    @mock.patch("bot_comandos.requests.post")
    @mock.patch("bot_comandos.requests.get")
    def test_autorizado_recibe_respuesta_y_avanza_offset(self, get, post):
        get.return_value.status_code = 200
        get.return_value.json.return_value = {"result": [actualizacion(10, 111, "/estado")]}
        self.bot.ciclo_una_vez()
        self.assertEqual(self.bot._offset, 11)
        enviado = post.call_args.kwargs["json"]
        self.assertEqual(enviado["chat_id"], "111")
        self.assertIn("ACTIVO", enviado["text"])

    @mock.patch("bot_comandos.requests.post")
    @mock.patch("bot_comandos.requests.get")
    def test_no_autorizado_se_ignora_y_se_audita(self, get, post):
        get.return_value.status_code = 200
        get.return_value.json.return_value = {"result": [actualizacion(5, 999, "/estado")]}
        self.bot.ciclo_una_vez()
        post.assert_not_called()
        eventos = [l for l in self.almacen.obtener_logs() if l["tipo"] == "BOT_NO_AUTORIZADO"]
        self.assertEqual(len(eventos), 1)
        self.assertEqual(eventos[0]["cliente"], "999")

    @mock.patch("bot_comandos.requests.post")
    @mock.patch("bot_comandos.requests.get")
    def test_texto_sin_comando_sugiere_ayuda(self, get, post):
        get.return_value.status_code = 200
        get.return_value.json.return_value = {"result": [actualizacion(1, 111, "hola")]}
        self.bot.ciclo_una_vez()
        self.assertIn("/ayuda", post.call_args.kwargs["json"]["text"])

    @mock.patch("bot_comandos.requests.get")
    def test_error_de_telegram_levanta_error_controlado(self, get):
        get.return_value.status_code = 409
        with self.assertRaises(ErrorTelegram):
            self.bot.ciclo_una_vez()

    @mock.patch("bot_comandos.requests.get")
    def test_descartar_pendientes_ignora_mensajes_viejos(self, get):
        get.return_value.status_code = 200
        get.return_value.json.return_value = {"result": [actualizacion(40, 111, "/estado")]}
        self.bot._descartar_pendientes()
        self.assertEqual(self.bot._offset, 41)

    @mock.patch("bot_comandos.requests.post", side_effect=requests.ConnectionError())
    def test_fallo_al_responder_no_lanza(self, _post):
        self.bot._procesar_actualizacion(actualizacion(1, 111, "/estado"))


if __name__ == "__main__":
    unittest.main()
