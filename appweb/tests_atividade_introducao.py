"""Testes da atividade introdutória.

Usa ``TestCaseAutenticado`` porque as rotas exigem login após o PR #22
(LoginObrigatorioMiddleware). Os testes validam a lógica da atividade,
não o controle de acesso anônimo.
"""

import hashlib
import json
from pathlib import Path

from django.test import Client
from django.urls import resolve, reverse

from .atividade_introducao import carregar_cenarios, processar
from .testes_utils import TestCaseAutenticado


FIXTURE = Path(__file__).parent / 'dados' / 'microlearning.json'
URL_PAGINA = '/atividades/introducao/alerta/'
URL_INTERPRETAR = '/atividades/introducao/alerta/interpretar'
BASE = {'cenario_id': 'g1', 'leitura': '1.80'}


class AtividadeIntroducaoTests(TestCaseAutenticado):
    def postar(self, cliente=None, **alteracoes):
        cliente = cliente or self.client
        corpo = dict(BASE)
        corpo.update(alteracoes)
        return cliente.post(
            URL_INTERPRETAR,
            data=json.dumps(corpo),
            content_type='application/json',
        )

    def test_pagina_inicial_sem_interpretacao_automatica(self):
        resposta = self.client.get(URL_PAGINA)

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'Interpretar um alerta de sensor')
        self.assertContains(resposta, 'Interpretar alerta')
        self.assertContains(resposta, 'aria-labelledby="titulo-resultado" tabindex="-1" hidden')
        self.assertContains(resposta, '/prototipo/introducao-esg.html#titulo-sensor-impacto')
        self.assertNotContains(resposta, 'O que a sigla ESG representa?')
        self.assertNotContains(resposta, 'Concluir desafio')
        self.assertNotContains(resposta, 'Fiz!')
        self.assertNotContains(resposta, 'pontos')
        self.assertNotContains(resposta, 'tempo real')

    def test_cenarios_expostos_com_premissas_completas(self):
        cenarios = carregar_cenarios()

        self.assertEqual([c['id'] for c in cenarios], ['g1', 'g2', 'g3', 'g4', 'g5'])
        for cenario in cenarios:
            with self.subTest(cenario=cenario['id']):
                self.assertTrue(cenario['sensor'])
                self.assertTrue(cenario['local'])
                self.assertTrue(cenario['unidade'])
                self.assertTrue(cenario['leitura'])
                self.assertTrue(cenario['limite'])
                self.assertIn(cenario['condicao'], {'acima', 'abaixo'})
                self.assertNotIn('mensagem', cenario)
                self.assertNotIn('desafio_id', cenario)
                self.assertNotIn('pontos', cenario)

    def test_cenario_valido_g1(self):
        resposta = self.postar()

        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()['resultado']
        self.assertEqual(dados['situacao'], 'ativado')
        self.assertEqual(dados['titulo'], 'Alerta ativado pela regra do cenário')
        self.assertIn('1.80', dados['explicacao'])
        self.assertIn('0.50', dados['explicacao'])
        self.assertIn('acima de', dados['explicacao'])
        self.assertEqual(
            dados['mensagem'],
            'A sala está consumindo energia fora do horário de uso.',
        )
        self.assertEqual(
            dados['sugestao']['titulo'],
            'Desligue tudo ao fim do expediente',
        )

    def test_cenario_inexistente(self):
        resposta = self.postar(cenario_id='inexistente')

        self.assertEqual(resposta.status_code, 400)
        self.assertIn('cenario_id', resposta.json()['campos'])

    def test_cenario_obrigatorio(self):
        resposta = self.postar(cenario_id='')

        self.assertEqual(resposta.status_code, 400)
        self.assertIn('cenario_id', resposta.json()['campos'])

    def test_leitura_invalida(self):
        casos = [
            'abc', 'NaN', 'Infinity', '-Infinity', '1,5', '1e3', '01.5', '',
            '123456789', '0.501', '1.234',
        ]
        for leitura in casos:
            with self.subTest(leitura=leitura):
                resposta = self.postar(leitura=leitura)
                self.assertEqual(resposta.status_code, 400)
                self.assertIn('leitura', resposta.json()['campos'])

    def test_leitura_deve_ser_texto(self):
        resposta = self.postar(leitura=1.8)

        self.assertEqual(resposta.status_code, 400)
        self.assertIn('leitura', resposta.json()['campos'])

    def test_leitura_negativa_usa_unidade_do_cenario(self):
        for cenario in ('g1', 'g2', 'g3', 'g4'):
            with self.subTest(cenario=cenario):
                resposta = self.postar(cenario_id=cenario, leitura='-1')
                self.assertEqual(resposta.status_code, 400)
                mensagem = resposta.json()['campos']['leitura']
                self.assertIn('não negativo', mensagem)

    def test_igualdade_nao_ativa_em_todos_os_cenarios(self):
        for cenario in carregar_cenarios():
            with self.subTest(cenario=cenario['id']):
                resposta = self.postar(
                    cenario_id=cenario['id'],
                    leitura=cenario['limite'],
                )
                self.assertEqual(resposta.status_code, 200)
                self.assertEqual(
                    resposta.json()['resultado']['situacao'],
                    'nao_ativado',
                )

    def test_g2_nao_tem_teto_de_sessenta_minutos(self):
        resposta = self.postar(cenario_id='g2', leitura='120.00')

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json()['resultado']['situacao'], 'ativado')

    def test_g4_aceita_cem_inclusive(self):
        resposta = self.postar(cenario_id='g4', leitura='100.00')

        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()['resultado']
        self.assertEqual(dados['cenario']['leitura'], '100.00')

    def test_g4_rejeita_acima_de_cem(self):
        resposta = self.postar(cenario_id='g4', leitura='100.01')

        self.assertEqual(resposta.status_code, 400)
        mensagem = resposta.json()['campos']['leitura']
        self.assertIn('100', mensagem)

    def test_g4_rejeita_negativo(self):
        resposta = self.postar(cenario_id='g4', leitura='-0.01')

        self.assertEqual(resposta.status_code, 400)
        self.assertIn('leitura', resposta.json()['campos'])

    def test_g5_aceita_temperatura_negativa_e_avalia_regra(self):
        resposta = self.postar(cenario_id='g5', leitura='-5.00')

        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()['resultado']
        self.assertEqual(dados['cenario']['leitura'], '-5.00')
        self.assertEqual(dados['situacao'], 'ativado')
        self.assertIn('-5.00', dados['explicacao'])

    def test_formato_nao_arredonda_precisao_excedente(self):
        for leitura in ('0.5000000001', '0.501', '12345678.001'):
            with self.subTest(leitura=leitura):
                resposta = self.postar(leitura=leitura)
                self.assertEqual(resposta.status_code, 400)
                self.assertIn('leitura', resposta.json()['campos'])

    def test_condicao_acima_no_limite_exato(self):
        casos = [
            ('0.49', False),
            ('0.50', False),
            ('0.51', True),
        ]
        for leitura, ativo in casos:
            with self.subTest(leitura=leitura):
                dados = self.postar(leitura=leitura).json()['resultado']
                self.assertEqual(dados['situacao'] == 'ativado', ativo)

    def test_condicao_abaixo_no_limite_exato(self):
        casos = [
            ('22.01', False),
            ('22.00', False),
            ('21.99', True),
        ]
        for leitura, ativo in casos:
            with self.subTest(leitura=leitura):
                dados = self.postar(cenario_id='g5', leitura=leitura).json()['resultado']
                self.assertEqual(dados['situacao'] == 'ativado', ativo)

    def test_leitura_enviada_e_utilizada(self):
        inativa = self.postar(leitura='0.10').json()['resultado']
        ativa = self.postar(leitura='1.80').json()['resultado']

        self.assertEqual(inativa['situacao'], 'nao_ativado')
        self.assertEqual(ativa['situacao'], 'ativado')
        self.assertIn('0.10', inativa['explicacao'])
        self.assertIn('1.80', ativa['explicacao'])

    def test_regras_do_catalogo_nao_sao_alteraveis_pelo_cliente(self):
        resposta = self.client.post(
            URL_INTERPRETAR,
            data=json.dumps({
                'cenario_id': 'g1',
                'leitura': '1.80',
                'limite': '9999.00',
                'condicao': 'abaixo',
                'unidade': 'inventada',
                'mensagem': 'mensagem inventada',
                'desafio_id': 'd5',
            }),
            content_type='application/json',
        )

        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()['resultado']
        self.assertEqual(dados['situacao'], 'ativado')
        self.assertIn('0.50', dados['explicacao'])
        self.assertIn('acima de', dados['explicacao'])
        self.assertNotIn('inventada', dados['explicacao'])
        self.assertNotEqual(dados['mensagem'], 'mensagem inventada')
        self.assertEqual(dados['sugestao']['id'], 'd1')

    def test_g1_e_g5_preservam_associacao_repetida_com_d1(self):
        primeiro = self.postar(cenario_id='g1').json()['resultado']
        segundo = self.postar(cenario_id='g5', leitura='21.00').json()['resultado']

        self.assertEqual(primeiro['sugestao']['id'], 'd1')
        self.assertEqual(segundo['sugestao']['id'], 'd1')
        self.assertEqual(primeiro['sugestao']['titulo'], segundo['sugestao']['titulo'])

    def test_resposta_sem_pontos_gabarito_ou_progresso(self):
        corpo = self.postar().json()

        self.assertNotIn('pontos', corpo)
        self.assertNotIn('progresso', corpo)
        self.assertNotIn('concluidos', corpo)
        self.assertNotIn('correta', corpo)
        self.assertNotIn('explicacao_quiz', corpo)
        self.assertNotIn('quizzes', str(corpo))

    def test_inativo_nao_afirma_ausencia_de_problema(self):
        dados = self.postar(leitura='0.10').json()['resultado']

        self.assertEqual(dados['titulo'], 'Alerta não ativado pela regra do cenário')
        self.assertIn('não comprova ausência de outros problemas', dados['nota_inativa'])
        self.assertIsNone(dados['mensagem'])
        self.assertIsNone(dados['sugestao'])

    def test_corpo_json_invalido(self):
        resposta = self.client.post(
            URL_INTERPRETAR,
            data='{',
            content_type='application/json',
        )

        self.assertEqual(resposta.status_code, 400)
        self.assertIn('erro', resposta.json())

    def test_metodo_get_nao_e_aceito_no_endpoint(self):
        self.assertEqual(self.client.get(URL_INTERPRETAR).status_code, 405)

    def test_csrf_ativo(self):
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.usuario)
        resposta = self.postar(cliente=cliente)

        self.assertEqual(resposta.status_code, 403)

    def test_csrf_com_token_e_aceito(self):
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.usuario)
        cliente.get(URL_PAGINA)
        token = cliente.cookies['csrftoken'].value
        resposta = cliente.post(
            URL_INTERPRETAR,
            data=json.dumps(dict(BASE)),
            content_type='application/json',
            HTTP_X_CSRFTOKEN=token,
        )

        self.assertEqual(resposta.status_code, 200)

    def test_rotas_existentes_foram_preservadas(self):
        esperadas = {
            '/': 'home',
            '/microlearning/': 'painel_microlearning',
            '/microlearning/dados': 'dados_microlearning',
            '/microlearning/responder': 'responder_microlearning',
            '/recomendacoes': 'recomendacoes',
            '/fornecedores/dados': 'dados_fornecedores',
            '/simuladores/ambiental/': 'simulador_ambiental',
            '/simuladores/ambiental/simular': 'simular_ambiental',
        }
        for caminho, nome in esperadas.items():
            with self.subTest(caminho=caminho):
                self.assertEqual(resolve(caminho).url_name, nome)

        self.assertEqual(reverse('atividade_introducao'), URL_PAGINA)
        self.assertEqual(reverse('interpretar_alerta'), URL_INTERPRETAR)

    def test_fluxo_nao_altera_fixture_nem_cenario_base(self):
        antes = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
        cenarios_antes = carregar_cenarios()

        resposta = self.postar(leitura='0.10')

        depois = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(antes, depois)
        self.assertEqual(cenarios_antes, carregar_cenarios())

    def test_comparacao_usa_decimal_sem_perder_precisao(self):
        inativo, erros = processar({'cenario_id': 'g1', 'leitura': '0.50'})
        ativo, erros_ativos = processar({'cenario_id': 'g1', 'leitura': '0.51'})

        self.assertFalse(erros)
        self.assertFalse(erros_ativos)
        self.assertEqual(inativo['situacao'], 'nao_ativado')
        self.assertEqual(ativo['situacao'], 'ativado')
        self.assertEqual(inativo['cenario']['leitura'], '0.50')
        self.assertEqual(ativo['cenario']['leitura'], '0.51')

    def test_anonimo_get_pagina_redireciona_para_entrar(self):
        resposta = Client().get(URL_PAGINA, HTTP_ACCEPT='text/html')

        self.assertEqual(resposta.status_code, 302)
        self.assertIn('/entrar/', resposta['Location'])

    def test_anonimo_post_interpretar_retorna_401(self):
        resposta = Client().post(
            URL_INTERPRETAR,
            data=json.dumps(dict(BASE)),
            content_type='application/json',
        )

        self.assertEqual(resposta.status_code, 401)
