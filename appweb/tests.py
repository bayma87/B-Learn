from django.test import TestCase
from django.urls import reverse

from appweb.models import AssessmentResult, ContactMessage


class AssessmentResultTests(TestCase):
    def test_calcula_pontuacao_e_pilar_critico(self):
        result = AssessmentResult(
            environmental_score=6,
            social_score=8,
            governance_score=5,
            overall_score=19,
        )

        result.calculate_scores()

        self.assertEqual(result.environmental_score, 6)
        self.assertEqual(result.social_score, 8)
        self.assertEqual(result.governance_score, 5)
        self.assertEqual(result.overall_score, 19)
        self.assertEqual(result.weakest_pillar, 'Governança')

    def test_quem_somos_post_salva_mensagem(self):
        response = self.client.post(
            reverse('quem_somos'),
            {
                'name': 'Ana Souza',
                'email': 'ana@email.com',
                'message': 'Teste de envio do formulário',
            },
            secure=True,
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Pergunta enviada com sucesso!')
        self.assertEqual(ContactMessage.objects.count(), 1)


class MicrolearningTests(TestCase):
    def responder(self, item_id, resposta=None):
        return self.client.post(
            reverse('responder_microlearning'),
            {'id': item_id, 'resposta': resposta},
            content_type='application/json',
            secure=True,
        )

    def test_dados_nao_expoem_gabarito_e_marcam_gatilhos_ativos(self):
        response = self.client.get(reverse('dados_microlearning'), secure=True)

        self.assertEqual(response.status_code, 200)
        dados = response.json()
        self.assertNotIn('correta', dados['quizzes'][0])
        self.assertNotIn('explicacao', dados['quizzes'][0])
        ativos = {g['id']: g['ativo'] for g in dados['gatilhos']}
        self.assertTrue(ativos['g1'])
        self.assertFalse(ativos['g5'])
        self.assertEqual(dados['progresso']['pontos'], 0)

    def test_quiz_correto_pontua_uma_unica_vez(self):
        primeira = self.responder('q1', 1).json()
        segunda = self.responder('q1', 1).json()

        self.assertTrue(primeira['resultado']['correta'])
        self.assertEqual(primeira['resultado']['pontos_ganhos'], 10)
        self.assertEqual(segunda['resultado']['pontos_ganhos'], 0)
        self.assertTrue(segunda['resultado']['ja_concluido'])
        self.assertEqual(segunda['progresso']['pontos'], 10)

    def test_quiz_errado_nao_pontua_e_permite_nova_tentativa(self):
        errada = self.responder('q1', 0).json()
        certa = self.responder('q1', 1).json()

        self.assertFalse(errada['resultado']['correta'])
        self.assertEqual(errada['progresso']['pontos'], 0)
        self.assertEqual(certa['progresso']['pontos'], 10)

    def test_desafio_soma_pontos_e_impacto(self):
        corpo = self.responder('d3').json()

        self.assertEqual(corpo['progresso']['pontos'], 20)
        impacto = {i['tipo']: i['valor'] for i in corpo['progresso']['impacto']}
        self.assertEqual(impacto['agua_l'], '50.00')
        self.assertEqual(impacto['energia_kwh'], '0.00')

    def test_desafio_sem_impacto_pontua(self):
        corpo = self.responder('d5').json()

        self.assertEqual(corpo['progresso']['pontos'], 20)

    def test_progresso_fica_na_sessao(self):
        self.responder('d1')
        dados = self.client.get(reverse('dados_microlearning'), secure=True).json()

        self.assertEqual(dados['progresso']['concluidos'], ['d1'])
        self.assertEqual(dados['progresso']['nivel'], 'Iniciante')

    def test_entradas_invalidas_retornam_400(self):
        self.assertEqual(self.responder('inexistente').status_code, 400)
        self.assertEqual(self.responder('q1', 9).status_code, 400)
        self.assertEqual(self.responder('q1', True).status_code, 400)
        self.assertEqual(self.responder('q1', '1').status_code, 400)

        for corpo in ('[1]', 'isto nao e json'):
            response = self.client.post(
                reverse('responder_microlearning'),
                corpo,
                content_type='application/json',
                secure=True,
            )
            self.assertEqual(response.status_code, 400)

    def test_resposta_so_aceita_post(self):
        response = self.client.get(reverse('responder_microlearning'), secure=True)

        self.assertEqual(response.status_code, 405)

    def test_paginas_renderizam(self):
        for nome in ('painel_microlearning', 'painel_fornecedores'):
            response = self.client.get(reverse(nome), secure=True)

            self.assertEqual(response.status_code, 200)


class FornecedoresTests(TestCase):
    def consultar(self, **parametros):
        return self.client.get(
            reverse('dados_fornecedores'), parametros, secure=True
        )

    def test_por_padrao_somente_auditados_ordenados_por_nota(self):
        dados = self.consultar().json()
        ids = [f['id'] for f in dados['fornecedores']]
        notas = [f['nota_esg'] for f in dados['fornecedores']]

        self.assertNotIn('f2', ids)
        self.assertEqual(notas, sorted(notas, reverse=True))
        self.assertEqual(ids[0], 'f1')

    def test_incluir_nao_auditados_gera_alerta_de_greenwashing(self):
        dados = self.consultar(somente_auditados='false').json()
        f2 = next(f for f in dados['fornecedores'] if f['id'] == 'f2')

        self.assertFalse(f2['auditado'])
        self.assertTrue(f2['alertas'])

    def test_alegacao_sustentavel_com_nota_baixa_gera_alerta(self):
        dados = self.consultar().json()
        f6 = next(f for f in dados['fornecedores'] if f['id'] == 'f6')

        self.assertEqual(f6['nivel'], 'baixa')
        self.assertTrue(f6['alertas'])

    def test_nota_minima_filtra_fornecedores(self):
        dados = self.consultar(nota_minima='70').json()
        ids = [f['id'] for f in dados['fornecedores']]

        self.assertTrue(all(f['nota_esg'] >= 70 for f in dados['fornecedores']))
        self.assertNotIn('f4', ids)

    def test_comparativo_de_ciclo_de_vida(self):
        dados = self.consultar(categoria='Monitores').json()
        comparativo = dados['comparativos'][0]

        # eco: 900/96 + 4*0.9 = 12.975; tradicional: 650/60 + 9*0.9 = 18.9333
        self.assertEqual(comparativo['ecologico']['custo_mensal'], '12.98')
        self.assertEqual(comparativo['tradicional']['custo_mensal'], '18.93')
        self.assertEqual(comparativo['economia_horizonte'], '357.50')
        self.assertEqual(comparativo['energia_evitada_kwh'], '300.00')
        self.assertTrue(comparativo['ecologico_compensa'])

    def test_comparativo_honesto_quando_tradicional_e_mais_barato(self):
        dados = self.consultar(categoria='Cadeiras').json()
        comparativo = dados['comparativos'][0]

        self.assertFalse(comparativo['ecologico_compensa'])
        self.assertTrue(comparativo['economia_horizonte'].startswith('-'))

    def test_preco_maximo_remove_produtos_acima_do_orcamento(self):
        dados = self.consultar(categoria='Monitores', preco_maximo='700').json()
        produtos = [p['id'] for f in dados['fornecedores'] for p in f['produtos']]

        self.assertEqual(produtos, ['p4'])
        self.assertEqual(dados['comparativos'], [])

    def test_filtros_invalidos_retornam_400(self):
        for parametros in (
            {'nota_minima': '101'},
            {'nota_minima': '-1'},
            {'nota_minima': 'abc'},
            {'preco_maximo': '-5'},
            {'preco_maximo': 'abc'},
            {'somente_auditados': 'talvez'},
            {'categoria': 'x' * 51},
        ):
            with self.subTest(parametros=parametros):
                self.assertEqual(self.consultar(**parametros).status_code, 400)
