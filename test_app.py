import unittest
from app import app

class TestApp(unittest.TestCase):

    def setUp(self):
        # Configura o cliente de testes do Flask
        self.client = app.test_client()
        self.client.testing = True

    def test_consumo_endpoint(self):
        # Testa a rota /consumo
        response = self.client.get('/consumo')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn('media_diaria', data)
        self.assertIn('alertas_desperdicio', data)

    def test_equipamentos_endpoint(self):
        # Testa a rota /equipamentos
        response = self.client.get('/equipamentos')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data['equipamento'], 'Motor Industrial')
        self.assertIn('kwh_por_hora', data)

    def test_resultados_endpoint(self):
        # Testa a rota /resultados
        response = self.client.get('/resultados')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data['acao'], 'Troca para LEDs')
        self.assertTrue(data['variacao_percentual'] < 0) # Deve ser redução

if __name__ == '__main__':
    unittest.main()
