"""Testes do simulador Ambiental.

Usa ``TestCaseAutenticado`` porque as rotas exigem login após o PR #22
(LoginObrigatorioMiddleware). Os testes validam a lógica do simulador,
não o controle de acesso anônimo.
"""

import hashlib
import json
from pathlib import Path

from django.test import Client
from django.urls import resolve, reverse

from .simuladores import carregar_cenario_ambiental
from .testes_utils import TestCaseAutenticado


FIXTURE = Path(__file__).parent / 'dados' / 'acompanhamento_f6.json'
URL_PAGINA = '/simuladores/ambiental/'
URL_SIMULAR = '/simuladores/ambiental/simular'


class SimuladorAmbientalTests(TestCaseAutenticado):
    def payload_inicial(self):
        return dict(carregar_cenario_ambiental()['valores'])

    def postar(self, cliente=None, **alteracoes):
        cliente = cliente or self.client
        payload = self.payload_inicial()
        payload.update(alteracoes)
        return cliente.post(
            URL_SIMULAR,
            data=json.dumps(payload),
            content_type='application/json',
        )

    def test_pagina_nao_executa_simulacao_automaticamente(self):
        resposta = self.client.get(URL_PAGINA)

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'Acompanhar uma ação de energia')
        self.assertContains(resposta, 'Calcular acompanhamento da ação')
        self.assertContains(resposta, 'id="resultado"')
        self.assertContains(resposta, 'aria-labelledby="titulo-resultado" tabindex="-1" hidden')
        self.assertContains(resposta, '<dl class="simulador__resultado-lista" id="lista-resultado"></dl>')

    def test_entrega_controlada_do_prototipo(self):
        caminhos = {
            '/prototipo/': 'text/html',
            '/prototipo/trilha-01.html': 'text/html',
            '/prototipo/assets/css/tokens.css': 'text/css',
            '/prototipo/assets/js/leitura.js': 'javascript',
            '/prototipo/assets/img/megafone.svg': 'image/svg+xml',
        }
        for caminho, tipo in caminhos.items():
            with self.subTest(caminho=caminho):
                resposta = self.client.get(caminho)
                self.assertEqual(resposta.status_code, 200)
                self.assertIn(tipo, resposta['Content-Type'])

    def test_prototipo_nao_entrega_zip_nem_raiz_do_repositorio(self):
        self.assertEqual(self.client.get('/prototipo/prototipo.zip').status_code, 404)
        self.assertEqual(self.client.get('/prototipo/../README.md').status_code, 404)
        self.assertEqual(self.client.get('/prototipo/%2e%2e/README.md').status_code, 404)

    def test_resultado_equivale_a_fixture(self):
        resposta = self.postar()

        self.assertEqual(resposta.status_code, 200)
        resultado = resposta.json()['resultado']
        self.assertEqual(resultado['situacao'], 'com_dados')
        self.assertEqual(resultado['media_antes'], '93.80')
        self.assertEqual(resultado['media_depois'], '40.44')
        self.assertEqual(resultado['diferenca_absoluta'], '-53.36')
        self.assertEqual(resultado['variacao_percentual'], '-56.88')
        self.assertEqual(resultado['tendencia'], 'queda')
        self.assertEqual(resultado['custo_diferenca']['valor'], '-45.35')
        self.assertEqual(resultado['custo_diferenca']['orientacao'], 'reducao_estimada')
        self.assertEqual(resultado['projecao_mensal']['valor'], '-1360.61')
        self.assertEqual(resultado['projecao_mensal']['dias'], 30)

    def test_entradas_diferentes_chegam_ao_calculo(self):
        cenario = self.payload_inicial()
        novos_depois = ['10.00'] * len(cenario['consumos_depois'])

        resposta = self.postar(consumos_depois=novos_depois)

        self.assertEqual(resposta.status_code, 200)
        resultado = resposta.json()['resultado']
        self.assertEqual(resultado['media_antes'], '93.80')
        self.assertEqual(resultado['media_depois'], '10.00')
        self.assertEqual(resultado['tendencia'], 'queda')

    def test_aumento_de_consumo(self):
        cenario = self.payload_inicial()
        novos_depois = ['200.00'] * len(cenario['consumos_depois'])

        resposta = self.postar(consumos_depois=novos_depois)

        resultado = resposta.json()['resultado']
        self.assertEqual(resultado['tendencia'], 'aumento')
        self.assertEqual(resultado['custo_diferenca']['orientacao'], 'aumento_estimado')
        self.assertNotEqual(resultado['diferenca_absoluta'], '0.00')
        self.assertTrue(resultado['custo_diferenca']['valor'].startswith('-') is False)

    def test_igualdade_de_consumo(self):
        cenario = self.payload_inicial()
        iguais = ['10.00'] * len(cenario['consumos_antes'])

        resposta = self.postar(consumos_antes=iguais, consumos_depois=iguais)

        resultado = resposta.json()['resultado']
        self.assertEqual(resultado['tendencia'], 'estavel')
        self.assertEqual(resultado['diferenca_absoluta'], '0.00')
        self.assertEqual(resultado['variacao_percentual'], '0.00')
        self.assertEqual(resultado['custo_diferenca']['valor'], '0.00')
        self.assertEqual(resultado['custo_diferenca']['orientacao'], 'estavel')

    def test_base_zero(self):
        cenario = self.payload_inicial()
        zeros = ['0.00'] * len(cenario['consumos_antes'])

        resposta = self.postar(consumos_antes=zeros)

        resultado = resposta.json()['resultado']
        self.assertEqual(resultado['situacao'], 'com_dados')
        self.assertIsNone(resultado['variacao_percentual'])
        self.assertIn('Base zero', resultado['motivo'])

    def test_valores_invalidos(self):
        casos = [
            ('abc', 'consumos_antes[0]'),
            ('NaN', 'consumos_antes[0]'),
            ('Infinity', 'consumos_antes[0]'),
            ('-1', 'consumos_antes[0]'),
            ('', 'consumos_antes[0]'),
            ('1,5', 'consumos_antes[0]'),
        ]
        for valor, campo in casos:
            with self.subTest(valor=valor):
                cenario = self.payload_inicial()
                cenario['consumos_antes'][0] = valor
                resposta = self.postar(consumos_antes=cenario['consumos_antes'])
                self.assertEqual(resposta.status_code, 400)
                self.assertIn(campo, resposta.json()['campos'])

    def test_tarifa_invalida(self):
        for tarifa in ('abc', '0', '-1', 'NaN'):
            with self.subTest(tarifa=tarifa):
                resposta = self.postar(tarifa=tarifa)
                self.assertEqual(resposta.status_code, 400)
                self.assertIn('tarifa', resposta.json()['campos'])

    def test_quantidade_incorreta_de_leituras(self):
        cenario = self.payload_inicial()

        resposta_curta = self.postar(consumos_antes=cenario['consumos_antes'][:-1])
        self.assertEqual(resposta_curta.status_code, 400)
        self.assertIn('consumos_antes', resposta_curta.json()['campos'])

        resposta_longa = self.postar(
            consumos_depois=cenario['consumos_depois'] + ['1.00']
        )
        self.assertEqual(resposta_longa.status_code, 400)
        self.assertIn('consumos_depois', resposta_longa.json()['campos'])

    def test_corpo_json_invalido(self):
        resposta = self.client.post(
            URL_SIMULAR,
            data='{',
            content_type='application/json',
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('erro', resposta.json())

    def test_metodo_get_nao_e_aceito_no_calculo(self):
        self.assertEqual(self.client.get(URL_SIMULAR).status_code, 405)

    def test_csrf_ativo(self):
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.usuario)
        resposta = self.postar(cliente=cliente)
        self.assertEqual(resposta.status_code, 403)

    def test_rotas_existentes_foram_preservadas(self):
        esperadas = {
            '/': 'home',
            '/social/indicadores': 'indicadores_sociais',
            '/recomendacoes': 'recomendacoes',
            '/investimentos/simular': 'simular_investimentos',
            '/fornecedores/dados': 'dados_fornecedores',
        }
        for caminho, nome in esperadas.items():
            with self.subTest(caminho=caminho):
                self.assertEqual(resolve(caminho).url_name, nome)

        self.assertEqual(reverse('simulador_ambiental'), URL_PAGINA)
        self.assertEqual(reverse('simular_ambiental'), URL_SIMULAR)

    def test_fluxo_nao_altera_fixture(self):
        antes = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()

        resposta = self.postar()

        depois = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(antes, depois)

    def test_adaptador_nao_altera_cenario_base(self):
        cenario = carregar_cenario_ambiental()
        original = json.dumps(cenario['config'], sort_keys=True)
        payload = self.payload_inicial()
        payload['consumos_antes'][0] = '999.99'

        from .simuladores import aplicar_cenario_ambiental
        aplicar_cenario_ambiental(cenario['config'], payload)

        self.assertEqual(original, json.dumps(cenario['config'], sort_keys=True))

    def test_anonimo_get_pagina_redireciona_para_entrar(self):
        resposta = Client().get(URL_PAGINA, HTTP_ACCEPT='text/html')

        self.assertEqual(resposta.status_code, 302)
        self.assertIn('/entrar/', resposta['Location'])

    def test_anonimo_post_simular_retorna_401(self):
        resposta = Client().post(
            URL_SIMULAR,
            data=json.dumps(self.payload_inicial()),
            content_type='application/json',
        )

        self.assertEqual(resposta.status_code, 401)
