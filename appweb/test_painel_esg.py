from django.test import TestCase
from django.urls import reverse


class PainelEsgHistoria5Tests(TestCase):
    def test_endpoint_consolidado_responde_json(self):
        response = self.client.get(reverse("painel_esg_api"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")

        dados = response.json()
        self.assertEqual(dados["origem"], "simulada")
        self.assertIn("ambiental", dados["indicadores"])
        self.assertIn("social", dados["indicadores"])
        self.assertIn("governanca", dados["indicadores"])
        self.assertIn("resultados_acoes", dados)
        self.assertIn("recomendacoes", dados)

    def test_endpoint_rejeita_metodo_post(self):
        response = self.client.post(reverse("painel_esg_api"))
        self.assertEqual(response.status_code, 405)

    def test_recomendacoes_possuem_criterios_de_prioridade(self):
        response = self.client.get(reverse("painel_esg_api"))
        self.assertEqual(response.status_code, 200)

        recomendacoes = response.json()["recomendacoes"]
        self.assertIn("criterios_priorizacao", recomendacoes)
        self.assertIsInstance(recomendacoes["itens"], list)
        for item in recomendacoes["itens"]:
            self.assertIn("posicao_prioridade", item)
            self.assertIn("viabilidade_financeira", item)
            self.assertIn("impacto_observado", item)
