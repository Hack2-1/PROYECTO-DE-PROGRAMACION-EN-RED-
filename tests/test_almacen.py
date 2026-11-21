import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from almacen import AlmacenBitacora  # noqa: E402


class PruebasAlmacen(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.ruta = os.path.join(self.dir.name, "incidencias.json")
        self.ruta_alertas = os.path.join(self.dir.name, "alertas.json")
        self.almacen = AlmacenBitacora(self.ruta, self.ruta_alertas)

    def tearDown(self):
        self.dir.cleanup()

    def test_crear_asigna_id_hora_y_estado_por_defecto(self):
        inc, snapshot = self.almacen.crear_incidencia("vulnerabilidad", "Puerto 23 abierto")
        self.assertEqual(inc["id"], 1)
        self.assertEqual(inc["estado"], "abierta")
        self.assertIn("hora", inc)
        self.assertEqual(len(snapshot), 1)

    def test_persiste_formato_del_contrato(self):
        self.almacen.crear_incidencia("alerta", "x")
        with open(self.ruta, encoding="utf-8") as f:
            datos = json.load(f)
        self.assertEqual(datos["siguiente_id"], 2)
        self.assertEqual(datos["incidencias"][0]["id"], 1)

    def test_validaciones(self):
        with self.assertRaises(ValueError):
            self.almacen.crear_incidencia("", "desc")
        with self.assertRaises(ValueError):
            self.almacen.crear_incidencia("alerta", "   ")
        with self.assertRaises(ValueError):
            self.almacen.crear_incidencia("alerta", "d", estado="cerrada")
        with self.assertRaises(ValueError):
            self.almacen.crear_incidencia(5, "d")

    def test_id_no_se_reutiliza_tras_delete_ni_tras_reinicio(self):
        self.almacen.crear_incidencia("a", "1")
        self.almacen.crear_incidencia("a", "2")
        self.assertTrue(self.almacen.eliminar_incidencia(2))
        nuevo, _ = self.almacen.crear_incidencia("a", "3")
        self.assertEqual(nuevo["id"], 3)
        self.almacen.eliminar_incidencia(3)
        reiniciado = AlmacenBitacora(self.ruta, self.ruta_alertas)
        nuevo, _ = reiniciado.crear_incidencia("a", "4")
        self.assertEqual(nuevo["id"], 4)

    def test_filtros_y_obtener(self):
        self.almacen.crear_incidencia("alerta", "a")
        self.almacen.crear_incidencia("incidente", "b", estado="resuelta")
        self.assertEqual(len(self.almacen.listar_incidencias(tipo="alerta")), 1)
        self.assertEqual(len(self.almacen.listar_incidencias(estado="resuelta")), 1)
        self.assertEqual(len(self.almacen.listar_incidencias(tipo="alerta", estado="resuelta")), 0)
        self.assertEqual(self.almacen.obtener_incidencia(2)["descripcion"], "b")
        self.assertIsNone(self.almacen.obtener_incidencia(99))

    def test_actualizar_estado_y_reemplazar(self):
        self.almacen.crear_incidencia("alerta", "a")
        self.assertEqual(self.almacen.actualizar_estado(1, "en_proceso")["estado"], "en_proceso")
        with self.assertRaises(ValueError):
            self.almacen.actualizar_estado(1, "inventado")
        self.assertIsNone(self.almacen.actualizar_estado(9, "resuelta"))
        nueva = self.almacen.reemplazar_incidencia(1, "incidente", "nueva")
        self.assertEqual((nueva["tipo"], nueva["estado"]), ("incidente", "abierta"))
        self.assertIsNone(self.almacen.reemplazar_incidencia(9, "a", "b"))

    def test_carga_lista_directa_compatible(self):
        with open(self.ruta, "w", encoding="utf-8") as f:
            json.dump([{"id": 7, "tipo": "a", "descripcion": "d", "estado": "abierta", "hora": "h"}], f)
        almacen = AlmacenBitacora(self.ruta, self.ruta_alertas)
        nuevo, _ = almacen.crear_incidencia("a", "d2")
        self.assertEqual(nuevo["id"], 8)

    def test_archivo_corrupto_se_aparta_sin_caerse(self):
        with open(self.ruta, "w", encoding="utf-8") as f:
            f.write("{esto no es json")
        almacen = AlmacenBitacora(self.ruta, self.ruta_alertas)
        self.assertEqual(almacen.listar_incidencias(), [])
        self.assertTrue(any(n.startswith("incidencias.json.corrupto-") for n in os.listdir(self.dir.name)))

    def test_concurrencia_ids_unicos_y_json_integro(self):
        hilos, por_hilo = 8, 15

        def trabajo(n):
            for i in range(por_hilo):
                self.almacen.crear_incidencia("alerta", "h%d-%d" % (n, i))

        lanzados = [threading.Thread(target=trabajo, args=(n,)) for n in range(hilos)]
        for h in lanzados:
            h.start()
        for h in lanzados:
            h.join()
        ids = [i["id"] for i in self.almacen.listar_incidencias()]
        self.assertEqual(len(ids), hilos * por_hilo)
        self.assertEqual(len(set(ids)), hilos * por_hilo)
        with open(self.ruta, encoding="utf-8") as f:
            disco = json.load(f)
        self.assertEqual(len(disco["incidencias"]), hilos * por_hilo)
        self.assertEqual(disco["siguiente_id"], hilos * por_hilo + 1)

    def test_contadores_y_logs(self):
        self.almacen.registrar_peticion("GET", "/salud", 200, "1.1.1.1")
        self.almacen.registrar_peticion("GET", "/x", 404, "1.1.1.1")
        self.almacen.registrar_peticion("POST", "/incidencias", 201, "1.1.1.1")
        self.almacen.registrar_evento("TLS_RECHAZADO", "2.2.2.2", "HTTP plano")
        c = self.almacen.obtener_contadores()
        self.assertEqual(c["total"], 3)
        self.assertEqual(c["por_metodo"], {"GET": 2, "POST": 1})
        self.assertEqual(c["por_familia"], {"2xx": 2, "4xx": 1})
        self.assertEqual(len(self.almacen.obtener_logs()), 4)

    def test_registro_de_alertas(self):
        self.assertEqual(self.almacen.cargar_alertas(), [])
        a1 = self.almacen.registrar_alerta({"incidencia_id": 1, "estado_envio": "ENVIADO"})
        a2 = self.almacen.registrar_alerta({"incidencia_id": 2, "estado_envio": "ERROR_API"})
        self.assertEqual((a1["id_alerta"], a2["id_alerta"]), (1, 2))
        self.assertEqual(len(self.almacen.cargar_alertas()), 2)

    def test_sqlite_indexado_resumen_por_fecha(self):
        i1, _ = self.almacen.crear_incidencia("vulnerabilidad", "Puerto 23 en caja")
        i2, _ = self.almacen.crear_incidencia("incidente", "Fuerza bruta SSH")
        self.almacen.actualizar_estado(i2["id"], "resuelta")
        self.almacen.registrar_alerta(
            {"incidencia_id": i2["id"], "tipo_incidencia": "incidente", "motivo": "M", "estado_envio": "ENVIADO"}
        )

        # Insertar una incidencia de otro dia directamente en SQLite para aislar el filtro
        with sqlite3.connect(self.almacen.ruta_db) as conn:
            indices = [
                fila[0]
                for fila in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                ).fetchall()
            ]
            conn.execute(
                """
                INSERT INTO incidencias (id, tipo, descripcion, estado, hora, fecha, origen)
                VALUES (99, 'alerta', 'De otro dia', 'abierta', '2026-11-18T10:00:00-06:00', '2026-11-18', NULL)
                """
            )
            conn.commit()

        self.assertIn("idx_incidencias_fecha", indices)
        self.assertIn("idx_alertas_fecha", indices)

        hoy = i1["hora"][:10]
        resumen_hoy = self.almacen.resumen_por_fecha(hoy)
        self.assertEqual(resumen_hoy["total"], 2)
        self.assertEqual(resumen_hoy["por_estado"]["abierta"], 1)
        self.assertEqual(resumen_hoy["por_estado"]["resuelta"], 1)
        self.assertEqual(resumen_hoy["por_tipo"], {"incidente": 1, "vulnerabilidad": 1})
        self.assertEqual(resumen_hoy["total_alertas"], 1)

        resumen_miercoles = self.almacen.resumen_por_fecha("2026-11-18")
        self.assertEqual(resumen_miercoles["total"], 1)
        self.assertEqual(resumen_miercoles["incidencias"][0]["id"], 99)
        self.assertEqual(resumen_miercoles["total_alertas"], 0)


if __name__ == "__main__":
    unittest.main()
