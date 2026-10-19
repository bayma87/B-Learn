import os
import re
import tempfile
import copy
import json
from pathlib import Path
from decimal import Decimal, ROUND_DOWN, getcontext, localcontext
from unittest.mock import patch

from django.test import TestCase
from django.urls import resolve, reverse

from appweb.models import AssessmentResult, ContactMessage
from appweb.consumo import (
    calcular_indicadores_consumo,
    carregar_dados_consumo,
    validar_dados_consumo,
)
from appweb.equipamentos import (
    calcular_consumo_por_hora,
    carregar_dados_equipamentos,
    validar_dados_equipamentos,
)
from appweb.recomendacoes import (
    MOTIVO_ECONOMIA_INVALIDA,
    carregar_catalogo_acoes,
    gerar_recomendacoes,
    validar_catalogo_acoes,
)
from appweb.residuos import calcular_resumo_residuos
from appweb.social import calcular_indicadores_sociais
from appweb.sugestoes import selecionar_sugestoes_orientadas


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


def _acao(custo='1000.00', economia='200.00', id_acao='T1', **extras):
    registro = {
        'id_acao': id_acao,
        'nome': 'Ação de teste',
        'pilar': 'E (Ambiental)',
        'custo': custo,
        'economia_mensal': economia,
    }
    registro.update(extras)
    return registro


def _catalogo(*registros):
    return {'versao': 1, 'origem': 'simulada', 'registros': list(registros)}


class RecomendacoesCalculoTests(TestCase):
    def test_payback_simples_mil_por_duzentos(self):
        resultado = gerar_recomendacoes(_catalogo(_acao()))

        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0]['payback_meses'], '5.0')
        self.assertEqual(resultado[0]['prioridade'], 'Alta')
        self.assertIsNone(resultado[0]['payback_indisponivel'])

    def test_limites_exatos_de_prioridade(self):
        casos = [
            ('1200.00', '200.00', '6.0', 'Alta'),
            ('2400.00', '200.00', '12.0', 'Média'),
            ('2420.00', '200.00', '12.1', 'Baixa'),
        ]
        for custo, economia, payback, prioridade in casos:
            with self.subTest(custo=custo):
                resultado = gerar_recomendacoes(
                    _catalogo(_acao(custo=custo, economia=economia))
                )
                self.assertEqual(resultado[0]['payback_meses'], payback)
                self.assertEqual(resultado[0]['prioridade'], prioridade)

    def test_payback_nao_arredondado_determina_prioridade(self):
        # 6,01 exibido como 6,0 não pode virar Alta:
        # 1202.00 / 200.00 = 6.01
        resultado = gerar_recomendacoes(
            _catalogo(_acao(custo='1202.00', economia='200.00'))
        )
        self.assertEqual(resultado[0]['payback_meses'], '6.0')
        self.assertEqual(resultado[0]['prioridade'], 'Média')

        # 12,01 exibido como 12,0 não pode virar Média:
        # 2402.00 / 200.00 = 12.01
        resultado = gerar_recomendacoes(
            _catalogo(_acao(custo='2402.00', economia='200.00'))
        )
        self.assertEqual(resultado[0]['payback_meses'], '12.0')
        self.assertEqual(resultado[0]['prioridade'], 'Baixa')

    def test_faixas_de_investimento(self):
        resultado = gerar_recomendacoes(
            _catalogo(_acao(custo='1000.00', economia='200.00'))
        )
        faixa = resultado[0]['investimento_sugerido']

        self.assertEqual(faixa['minimo'], '850.00')
        self.assertEqual(faixa['recomendado'], '1000.00')
        self.assertEqual(faixa['maximo'], '1250.00')

    def test_arredondamento_financeiro_com_meio_centavo(self):
        # 999.99 x 0,85 = 849.9915 -> 849.99 (ROUND_HALF_UP)
        # 999.99 x 1,25 = 1249.9875 -> 1249.99
        resultado = gerar_recomendacoes(
            _catalogo(_acao(custo='999.99', economia='200.00'))
        )
        faixa = resultado[0]['investimento_sugerido']

        self.assertEqual(faixa['minimo'], '849.99')
        self.assertEqual(faixa['maximo'], '1249.99')

    def test_arredondamento_financeiro_round_half_up_exato(self):
        # 0.10 x 0,85 = 0.085 -> 0.09 (meio centavo arredonda para cima)
        # 0.10 x 1,25 = 0.125 -> 0.13
        resultado = gerar_recomendacoes(
            _catalogo(_acao(custo='0.10', economia='200.00'))
        )
        faixa = resultado[0]['investimento_sugerido']

        self.assertEqual(faixa['minimo'], '0.09')
        self.assertEqual(faixa['recomendado'], '0.10')
        self.assertEqual(faixa['maximo'], '0.13')

    def test_ordenacao_por_economia_decrescente(self):
        resultado = gerar_recomendacoes(
            _catalogo(
                _acao(id_acao='T1', custo='1000.00', economia='200.00'),
                _acao(id_acao='T2', custo='5000.00', economia='900.00'),
                _acao(id_acao='T3', custo='800.00', economia='400.00'),
            )
        )
        ordem = [item['id_acao'] for item in resultado]

        self.assertEqual(ordem, ['T2', 'T3', 'T1'])

    def test_ordenacao_comparacao_numerica_de_economias(self):
        resultado = gerar_recomendacoes(
            _catalogo(
                _acao(id_acao='T1', custo='1000.00', economia='80.00'),
                _acao(id_acao='T2', custo='20000.00', economia='1000.00'),
                _acao(id_acao='T3', custo='19000.00', economia='950.00'),
            )
        )
        ordem = [item['id_acao'] for item in resultado]

        # 1000.00 > 950.00 > 80.00, ordem numérica e não lexicográfica
        self.assertEqual(ordem, ['T2', 'T3', 'T1'])

    def test_ordenacao_por_payback_nao_arredondado_em_empate(self):
        # Ambos exibem payback 6.0, mas 1200.00/200.00 = 6.0 e
        # 1202.00/200.00 = 6.01; a de menor payback real vai primeiro,
        # mesmo tendo sido inserida depois no catálogo.
        resultado = gerar_recomendacoes(
            _catalogo(
                _acao(id_acao='T1', custo='1202.00', economia='200.00'),
                _acao(id_acao='T2', custo='1200.00', economia='200.00'),
            )
        )
        ordem = [item['id_acao'] for item in resultado]

        self.assertEqual(ordem, ['T2', 'T1'])
        self.assertEqual(
            [item['payback_meses'] for item in resultado], ['6.0', '6.0']
        )

    def test_ordenacao_por_payback_crescente_em_empate(self):
        # Mesma economia (200.00); custos 1000 e 1200 -> payback 5.0 e 6.0
        resultado = gerar_recomendacoes(
            _catalogo(
                _acao(id_acao='T1', custo='1200.00', economia='200.00'),
                _acao(id_acao='T2', custo='1000.00', economia='200.00'),
            )
        )
        ordem = [item['id_acao'] for item in resultado]

        self.assertEqual(ordem, ['T2', 'T1'])

    def test_economia_zero_nao_divide_nem_gera_prioridade(self):
        resultado = gerar_recomendacoes(
            _catalogo(_acao(custo='1000.00', economia='0.00'))
        )
        item = resultado[0]

        self.assertIsNone(item['payback_meses'])
        self.assertIsNone(item['prioridade'])
        self.assertEqual(item['payback_indisponivel'], MOTIVO_ECONOMIA_INVALIDA)
        # O registro continua presente, sem inventar economia:
        self.assertEqual(item['investimento_sugerido']['recomendado'], '1000.00')

    def test_economia_negativa_nao_divide_nem_gera_prioridade(self):
        resultado = gerar_recomendacoes(
            _catalogo(_acao(custo='1000.00', economia='-50.00'))
        )
        item = resultado[0]

        self.assertIsNone(item['payback_meses'])
        self.assertIsNone(item['prioridade'])
        self.assertEqual(item['payback_indisponivel'], MOTIVO_ECONOMIA_INVALIDA)

    def test_registro_sem_payback_fica_ao_final(self):
        resultado = gerar_recomendacoes(
            _catalogo(
                _acao(id_acao='T1', custo='1000.00', economia='0.00'),
                _acao(id_acao='T2', custo='1000.00', economia='100.00'),
            )
        )
        ordem = [item['id_acao'] for item in resultado]

        self.assertEqual(ordem, ['T2', 'T1'])

    def test_todos_os_itens_marcados_como_simulados(self):
        resultado = gerar_recomendacoes(_catalogo(_acao()))

        self.assertTrue(all(item['dados_simulados'] for item in resultado))


class RecomendacoesValidacaoTests(TestCase):
    def test_catalogo_vazio_gera_erro(self):
        with self.assertRaisesMessage(ValueError, 'não vazia'):
            validar_catalogo_acoes(_catalogo())

    def test_registro_nao_dicionario_gera_erro(self):
        with self.assertRaisesMessage(ValueError, 'formato inválido'):
            validar_catalogo_acoes(_catalogo('nao-sou-um-dict'))

    def test_campo_ausente_gera_erro(self):
        acao = _acao()
        del acao['custo']

        with self.assertRaisesMessage(ValueError, 'custo inválido'):
            validar_catalogo_acoes(_catalogo(acao))

    def test_valor_nao_numerico_gera_erro(self):
        with self.assertRaisesMessage(ValueError, 'economia mensal inválida'):
            validar_catalogo_acoes(_catalogo(_acao(economia='muita')))

    def test_identificador_repetido_gera_erro(self):
        with self.assertRaisesMessage(ValueError, 'repetido'):
            validar_catalogo_acoes(
                _catalogo(_acao(id_acao='T1'), _acao(id_acao='T1'))
            )

    def test_custo_zero_gera_erro(self):
        with self.assertRaisesMessage(ValueError, 'maior que zero'):
            validar_catalogo_acoes(_catalogo(_acao(custo='0.00')))

    def test_origem_diferente_de_simulada_gera_erro(self):
        dados = _catalogo(_acao())
        dados['origem'] = 'sensor'

        with self.assertRaisesMessage(ValueError, 'origem simulada'):
            validar_catalogo_acoes(dados)


class RecomendacoesCarregadorTests(TestCase):
    def _criar_temporario(self, conteudo):
        arquivo = tempfile.NamedTemporaryFile(
            mode='w', encoding='utf-8', suffix='.json', delete=False
        )
        arquivo.write(conteudo)
        arquivo.close()
        self.addCleanup(os.unlink, arquivo.name)
        return arquivo.name

    def test_arquivo_vazio_gera_erro(self):
        caminho = self._criar_temporario('')

        with self.assertRaisesMessage(ValueError, 'vazio'):
            carregar_catalogo_acoes(caminho)

    def test_json_invalido_gera_erro(self):
        caminho = self._criar_temporario('{nao é json')

        with self.assertRaisesMessage(ValueError, 'JSON válido'):
            carregar_catalogo_acoes(caminho)

    def test_caminho_inexistente_gera_erro(self):
        caminho = os.path.join(
            tempfile.gettempdir(), 'arquivo_que_nao_existe_esg.json'
        )

        with self.assertRaisesMessage(ValueError, 'Não foi possível ler'):
            carregar_catalogo_acoes(caminho)


class RecomendacoesCatalogoRealTests(TestCase):
    def test_catalogo_do_projeto_carrega_e_gera_recomendacoes(self):
        dados = carregar_catalogo_acoes()
        resultado = gerar_recomendacoes(dados)

        self.assertEqual(len(resultado), 6)
        self.assertTrue(all(item['dados_simulados'] for item in resultado))
        # Ordenação conferida convertendo a economia para Decimal,
        # e não comparando strings monetárias:
        economias = [
            Decimal(item['economia_estimada_mensal']) for item in resultado
        ]
        self.assertEqual(economias, sorted(economias, reverse=True))

    def test_gerar_recomendacoes_sem_argumentos_usa_catalogo_padrao(self):
        resultado = gerar_recomendacoes()

        self.assertEqual(len(resultado), 6)
        self.assertEqual(
            [item['id_acao'] for item in resultado],
            ['A04', 'A02', 'A01', 'A03', 'A06', 'A05'],
        )

    def test_acao_led_do_catalogo_tem_payback_esperado(self):
        resultado = gerar_recomendacoes(carregar_catalogo_acoes())
        led = next(
            item for item in resultado if item['id_acao'] == 'A01'
        )

        # 2500.00 / 450.00 = 5.55... -> 5.6, prioridade Alta
        self.assertEqual(led['payback_meses'], '5.6')
        self.assertEqual(led['prioridade'], 'Alta')


class RecomendacoesApiTests(TestCase):
    def test_get_recomendacoes_retorna_contrato_json(self):
        response = self.client.get(reverse('recomendacoes'), secure=True)

        self.assertEqual(response.status_code, 200)

        dados = response.json()
        recomendacoes = dados['recomendacoes']

        self.assertEqual(dados['origem'], 'simulada')
        self.assertFalse(dados['personalizada_por_indicadores'])
        self.assertEqual(dados['total'], len(recomendacoes))
        self.assertEqual(
            [item['id_acao'] for item in recomendacoes],
            ['A04', 'A02', 'A01', 'A03', 'A06', 'A05'],
        )
        self.assertEqual(
            [item['id_acao'] for item in dados['sugestoes_orientadas']],
            ['A06', 'A05'],
        )
        self.assertEqual(
            dados['avaliacao_fontes'],
            {
                'social': {'situacao': 'avaliada', 'escopo': 'agregado'},
                'residuos': {'situacao': 'avaliada', 'escopo': 'agregado'},
            },
        )
        for sugestao in dados['sugestoes_orientadas']:
            self.assertIn('justificativa', sugestao)
            self.assertEqual(
                sugestao['natureza_financeira'],
                'estimativa_do_catalogo',
            )
            self.assertEqual(sugestao['evidencias'][0]['escopo'], 'agregado')
            self.assertNotIn('local', sugestao['evidencias'][0])
            self.assertNotIn('periodo_inicio', sugestao['evidencias'][0])
            self.assertNotIn('periodo_fim', sugestao['evidencias'][0])

        for item in recomendacoes:
            self.assertTrue(item['dados_simulados'])
            self.assertIsInstance(
                item['economia_estimada_mensal'], str
            )
            self.assertIsInstance(item['investimento_sugerido'], dict)
            for valor in item['investimento_sugerido'].values():
                self.assertIsInstance(valor, str)

    def test_payback_no_json_preserva_string_ou_null(self):
        recomendacoes = gerar_recomendacoes(
            _catalogo(
                _acao(id_acao='T1', economia='200.00'),
                _acao(id_acao='T2', economia='0.00'),
            )
        )

        with patch(
            'appweb.views.gerar_recomendacoes',
            return_value=recomendacoes,
        ):
            response = self.client.get(
                reverse('recomendacoes'),
                secure=True,
            )

        self.assertEqual(response.status_code, 200)
        itens = response.json()['recomendacoes']

        item_com_payback = next(
            item for item in itens if item['id_acao'] == 'T1'
        )
        item_sem_payback = next(
            item for item in itens if item['id_acao'] == 'T2'
        )

        self.assertIsInstance(item_com_payback['payback_meses'], str)
        self.assertIsNone(item_sem_payback['payback_meses'])

    @patch('appweb.views.selecionar_sugestoes_orientadas')
    def test_api_preserva_catalogo_quando_nao_ha_sugestoes(
        self,
        mock_selecionar,
    ):
        mock_selecionar.return_value = {
            'origem': 'simulada',
            'avaliacao_fontes': {
                'social': {'situacao': 'avaliada', 'escopo': 'agregado'},
                'residuos': {'situacao': 'avaliada', 'escopo': 'agregado'},
            },
            'sugestoes_orientadas': [],
        }

        response = self.client.get(reverse('recomendacoes'), secure=True)

        self.assertEqual(response.status_code, 200)
        dados = response.json()
        self.assertEqual(
            [item['id_acao'] for item in dados['recomendacoes']],
            ['A04', 'A02', 'A01', 'A03', 'A06', 'A05'],
        )
        self.assertEqual(dados['sugestoes_orientadas'], [])
        self.assertEqual(dados['total'], 6)
        self.assertEqual(
            dados['avaliacao_fontes']['social']['situacao'],
            'avaliada',
        )

    def test_recomendacoes_nao_aceita_metodo_post(self):
        response = self.client.post(
            reverse('recomendacoes'),
            secure=True,
        )

        self.assertEqual(response.status_code, 405)

    @patch('appweb.views.gerar_recomendacoes')
    def test_falha_de_carregamento_retorna_erro_generico(self, mock_gerar):
        mock_gerar.side_effect = ValueError(
            'Não foi possível ler o arquivo secreto do catálogo.'
        )

        response = self.client.get(
            reverse('recomendacoes'),
            secure=True,
        )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json(),
            {'erro': 'Não foi possível carregar as recomendações.'},
        )
        self.assertNotIn('secreto', response.content.decode())

    @patch('appweb.views.gerar_recomendacoes')
    def test_catalogo_invalido_retorna_erro_generico(self, mock_gerar):
        mock_gerar.side_effect = ValueError(
            'Identificador repetido: detalhe interno do catálogo.'
        )

        response = self.client.get(
            reverse('recomendacoes'),
            secure=True,
        )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json(),
            {'erro': 'Não foi possível carregar as recomendações.'},
        )
        self.assertNotIn('detalhe interno', response.content.decode())


class SugestoesOrientadasTests(TestCase):
    def _acoes(self):
        return gerar_recomendacoes(carregar_catalogo_acoes())

    def test_seleciona_a05_com_residuo_nao_reciclado_positivo(self):
        resultado = selecionar_sugestoes_orientadas(
            self._acoes(),
            _indicadores_sociais_teste(),
            _indicadores_residuos_teste('0.01'),
        )

        self.assertEqual(
            [item['id_acao'] for item in resultado['sugestoes_orientadas']],
            ['A05'],
        )
        sugestao = resultado['sugestoes_orientadas'][0]
        self.assertEqual(
            sugestao['regra_aplicada'],
            'A05_quantidade_nao_reciclada_positiva',
        )
        self.assertIn('não afirma que toda essa quantidade', sugestao['justificativa'])
        self.assertEqual(
            sugestao['evidencias'][0]['escopo'],
            'agregado',
        )
        self.assertEqual(
            sugestao['evidencias'][0]['valores_observados']['nao_reciclado_kg'],
            '0.01',
        )

    def test_residuo_nao_reciclado_zero_nao_seleciona_a05(self):
        resultado = selecionar_sugestoes_orientadas(
            self._acoes(),
            _indicadores_sociais_teste(),
            _indicadores_residuos_teste('0.00'),
        )

        self.assertEqual(resultado['sugestoes_orientadas'], [])
        self.assertEqual(
            resultado['avaliacao_fontes']['residuos']['situacao'],
            'avaliada',
        )

    def test_seleciona_a06_somente_com_status_vermelho(self):
        for status, alertas, esperado in (
            ('verde', 0, []),
            ('amarelo', 3, []),
            ('vermelho', 4, ['A06']),
        ):
            with self.subTest(status=status):
                resultado = selecionar_sugestoes_orientadas(
                    self._acoes(),
                    _indicadores_sociais_teste(status, alertas),
                    _indicadores_residuos_teste(),
                )

                self.assertEqual(
                    [
                        item['id_acao']
                        for item in resultado['sugestoes_orientadas']
                    ],
                    esperado,
                )
                self.assertEqual(
                    resultado['avaliacao_fontes']['social']['situacao'],
                    'avaliada',
                )

    def test_justificativas_nao_atribuem_causa_ou_reciclabilidade(self):
        resultado = selecionar_sugestoes_orientadas(
            self._acoes(),
            _indicadores_sociais_teste('vermelho', 4),
            _indicadores_residuos_teste('2.00'),
        )
        por_id = {
            item['id_acao']: item
            for item in resultado['sugestoes_orientadas']
        }

        self.assertIn('não afirma que toda essa quantidade seja reciclável', por_id['A05']['justificativa'])
        self.assertIn('não atribui a causa dos alertas', por_id['A06']['justificativa'])

    def test_fontes_sem_dados_e_indisponivel_sao_distintas(self):
        resultado = selecionar_sugestoes_orientadas(
            self._acoes(),
            None,
            {'situacao': 'indisponivel', 'motivo': 'fonte indisponível'},
        )

        self.assertEqual(
            resultado['avaliacao_fontes']['social'],
            {'situacao': 'sem_dados'},
        )
        self.assertEqual(
            resultado['avaliacao_fontes']['residuos'],
            {
                'situacao': 'indisponivel',
                'motivo': 'fonte indisponível',
            },
        )
        self.assertEqual(resultado['sugestoes_orientadas'], [])

    def test_a01_a04_nao_sao_selecionadas_automaticamente(self):
        resultado = selecionar_sugestoes_orientadas(
            self._acoes(),
            _indicadores_sociais_teste('vermelho', 4),
            _indicadores_residuos_teste('2.00'),
        )

        ids = {
            item['id_acao'] for item in resultado['sugestoes_orientadas']
        }
        self.assertEqual(ids, {'A05', 'A06'})
        self.assertTrue(ids.isdisjoint({'A01', 'A02', 'A03', 'A04'}))

    def test_preserva_financeiro_ordem_e_entradas(self):
        acoes = self._acoes()
        acoes_reordenadas = [
            next(acao for acao in acoes if acao['id_acao'] == id_acao)
            for id_acao in ('A06', 'A01', 'A05')
        ]
        acoes_antes = copy.deepcopy(acoes_reordenadas)
        social = _indicadores_sociais_teste('vermelho', 4)
        residuos = _indicadores_residuos_teste('2.00')
        social_antes = copy.deepcopy(social)
        residuos_antes = copy.deepcopy(residuos)

        resultado = selecionar_sugestoes_orientadas(
            acoes_reordenadas,
            social,
            residuos,
        )

        self.assertEqual(
            [item['id_acao'] for item in resultado['sugestoes_orientadas']],
            ['A06', 'A05'],
        )
        sugestoes = {
            item['id_acao']: item
            for item in resultado['sugestoes_orientadas']
        }
        self.assertEqual(
            sugestoes['A06']['investimento_sugerido'],
            next(acao for acao in acoes_reordenadas if acao['id_acao'] == 'A06')['investimento_sugerido'],
        )
        self.assertEqual(
            sugestoes['A06']['payback_meses'],
            next(acao for acao in acoes_reordenadas if acao['id_acao'] == 'A06')['payback_meses'],
        )
        acao_original = next(
            acao for acao in acoes_reordenadas if acao['id_acao'] == 'A06'
        )
        for campo, valor in acao_original.items():
            self.assertEqual(sugestoes['A06'][campo], valor)
        self.assertEqual(sugestoes['A06']['natureza_financeira'], 'estimativa_do_catalogo')
        self.assertEqual(acoes_reordenadas, acoes_antes)
        self.assertEqual(social, social_antes)
        self.assertEqual(residuos, residuos_antes)

    def test_contrato_real_tem_fontes_agregadas_sem_local_ou_periodo(self):
        base = Path(__file__).parent / 'dados'
        dados_social = json.loads(
            (base / 'social.json').read_text(encoding='utf-8')
        )
        dados_residuos = json.loads(
            (base / 'residuos.json').read_text(encoding='utf-8')
        )
        indicadores_social = calcular_indicadores_sociais(dados_social)
        indicadores_residuos = calcular_resumo_residuos(dados_residuos)

        resultado = selecionar_sugestoes_orientadas(
            self._acoes(), indicadores_social, indicadores_residuos
        )

        self.assertEqual(
            resultado['avaliacao_fontes']['social']['escopo'],
            'agregado',
        )
        self.assertEqual(
            resultado['avaliacao_fontes']['residuos']['escopo'],
            'agregado',
        )
        for sugestao in resultado['sugestoes_orientadas']:
            evidencia = sugestao['evidencias'][0]
            self.assertEqual(evidencia['escopo'], 'agregado')
            self.assertNotIn('local', evidencia)
            self.assertNotIn('periodo_inicio', evidencia)
            self.assertNotIn('periodo_fim', evidencia)

    def test_contrato_invalido_nao_vira_sem_dados(self):
        casos = [
            (
                None,
                _indicadores_sociais_teste(),
                _indicadores_residuos_teste(),
                'lista',
            ),
            (
                self._acoes(),
                {'origem': 'simulada'},
                _indicadores_residuos_teste(),
                'Social',
            ),
            (
                self._acoes(),
                _indicadores_sociais_teste(),
                {'origem': 'simulada'},
                'Resíduos',
            ),
            (
                self._acoes(),
                _indicadores_sociais_teste(),
                _indicadores_residuos_teste('muita'),
                'decimal',
            ),
            (
                self._acoes(),
                _indicadores_sociais_teste('azul', 0),
                _indicadores_residuos_teste(),
                'status',
            ),
            (
                self._acoes(),
                {'situacao': 'indisponivel'},
                _indicadores_residuos_teste(),
                'indisponibilidade',
            ),
        ]

        for acoes, social, residuos, mensagem in casos:
            with self.subTest(mensagem=mensagem):
                with self.assertRaises(ValueError):
                    selecionar_sugestoes_orientadas(
                        acoes,
                        social,
                        residuos,
                    )

    def test_status_social_com_lista_objeto_ou_null_retorna_value_error(self):
        for status in ([], {}, None):
            with self.subTest(status=status):
                social = _indicadores_sociais_teste()
                social['total']['status'] = status

                with self.assertRaisesMessage(
                    ValueError, 'status inválido'
                ):
                    selecionar_sugestoes_orientadas(
                        self._acoes(),
                        social,
                        _indicadores_residuos_teste(),
                    )

    def test_uma_evidencia_por_fonte_agregada_sem_multiplicar_financeiro(self):
        resultado = selecionar_sugestoes_orientadas(
            self._acoes(),
            _indicadores_sociais_teste('vermelho', 4),
            _indicadores_residuos_teste('2.00'),
        )

        for sugestao in resultado['sugestoes_orientadas']:
            self.assertEqual(len(sugestao['evidencias']), 1)
            self.assertIsInstance(
                sugestao['economia_estimada_mensal'], str
            )
            self.assertIsInstance(sugestao['investimento_sugerido'], dict)

    def test_acao_financeira_malformada_e_rejeitada(self):
        acoes = self._acoes()
        acoes[0]['id_acao'] = ''

        with self.assertRaisesMessage(ValueError, 'id_acao obrigatório'):
            selecionar_sugestoes_orientadas(
                acoes,
                _indicadores_sociais_teste(),
                _indicadores_residuos_teste(),
            )

    def test_id_acao_com_espacos_nas_extremidades_e_rejeitado_sem_normalizar(self):
        acoes = self._acoes()
        acoes_antes = copy.deepcopy(acoes)
        entrada_invalida = copy.deepcopy(acoes)
        entrada_invalida[0]['id_acao'] = ' A05 '

        with self.assertRaisesMessage(
            ValueError, 'id_acao não pode ter espaços'
        ):
            selecionar_sugestoes_orientadas(
                entrada_invalida,
                _indicadores_sociais_teste(),
                _indicadores_residuos_teste(),
            )

        self.assertEqual(acoes, acoes_antes)
        self.assertEqual(entrada_invalida[0]['id_acao'], ' A05 ')


class RecomendacoesPaginaTests(TestCase):
    def test_pagina_de_recomendacoes_renderiza_com_menu_e_api(self):
        response = self.client.get(
            reverse('painel_recomendacoes'),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Recomendações ESG')
        self.assertContains(response, 'catálogo demonstrativo')
        self.assertContains(response, 'dados simulados')
        self.assertContains(response, 'sugestões orientadas')
        self.assertContains(response, 'indicadores simulados disponíveis')
        self.assertContains(response, 'retorno financeiro')
        self.assertContains(response, 'estimado da ação')
        self.assertContains(
            response,
            'Sugestões orientadas pelos indicadores simulados',
        )
        self.assertContains(response, 'lista-sugestoes')
        self.assertContains(response, 'justificativa')
        self.assertContains(response, 'avaliacao_fontes')
        self.assertContains(
            response,
            f'href="{reverse("painel_recomendacoes")}"',
        )
        self.assertContains(response, 'aria-current="page"')
        self.assertContains(response, f'"{reverse("recomendacoes")}"')


def _registro_consumo(
    id_leitura='C1',
    recurso='energia',
    valor='10.00',
    unidade='kWh',
    data='2026-01-01',
    local='Fabrica',
):
    return {
        'id_leitura': id_leitura,
        'recurso': recurso,
        'valor': valor,
        'unidade': unidade,
        'data': data,
        'local': local,
    }


def _dados_consumo(*registros):
    return {
        'versao': 1,
        'origem': 'simulada',
        'registros': list(registros),
    }


def _registro_equipamento(
    id_registro='E1',
    equipamento_id='EQ1',
    equipamento='Motor de teste',
    local='Fabrica de teste',
    consumo_kwh='10.00',
    horas_uso='2.00',
    periodo_inicio='2026-01-01',
    periodo_fim='2026-01-31',
    recurso='energia',
):
    return {
        'id_registro': id_registro,
        'equipamento_id': equipamento_id,
        'equipamento': equipamento,
        'local': local,
        'recurso': recurso,
        'consumo_kwh': consumo_kwh,
        'horas_uso': horas_uso,
        'periodo_inicio': periodo_inicio,
        'periodo_fim': periodo_fim,
    }


def _dados_equipamentos(*registros):
    return {
        'versao': 1,
        'origem': 'simulada',
        'registros': list(registros),
    }


def _indicadores_sociais_teste(status='verde', alertas=0):
    return {
        'origem': 'simulada',
        'unidade_horas': 'h',
        'total': {
            'alertas_seguranca': alertas,
            'horas_uso': '0.00',
            'status': status,
        },
        'por_dia': [],
        'por_mes': [],
    }


def _indicadores_residuos_teste(nao_reciclado='0.00'):
    return {
        'origem': 'simulada',
        'unidade': 'kg',
        'total': {
            'total_kg': '10.00',
            'reciclado_kg': '10.00',
            'nao_reciclado_kg': nao_reciclado,
            'taxa_reciclagem': '100.0',
            'tem_quantidade': True,
        },
        'por_dia': [],
        'por_mes': [],
    }


class ConsumoDadosTests(TestCase):
    def test_catalogo_real_carrega_energia_e_agua(self):
        dados = carregar_dados_consumo()
        registros = validar_dados_consumo(dados)

        self.assertEqual(len(registros), 9)
        self.assertEqual(
            {registro['recurso'] for registro in registros},
            {'energia', 'agua'},
        )

    def test_carregador_nao_tem_fallback_para_arquivo_invalido(self):
        arquivo = tempfile.NamedTemporaryFile(
            mode='w', encoding='utf-8', suffix='.json', delete=False
        )
        arquivo.write('{nao e json')
        arquivo.close()
        self.addCleanup(os.unlink, arquivo.name)

        with self.assertRaisesMessage(ValueError, 'carregar os dados'):
            carregar_dados_consumo(arquivo.name)

    def test_carregador_rejeita_arquivo_inexistente(self):
        caminho = os.path.join(
            tempfile.gettempdir(), 'consumo_f1_inexistente.json'
        )

        with self.assertRaisesMessage(ValueError, 'carregar os dados'):
            carregar_dados_consumo(caminho)

    def test_estrutura_vazia_e_aceita_sem_fabricar_dados(self):
        resultado = calcular_indicadores_consumo(_dados_consumo())

        self.assertEqual(resultado, {'origem': 'simulada', 'grupos': []})

    def test_validacao_rejeita_estrutura_e_dados_invalidos(self):
        casos = [
            ({**_dados_consumo(), 'versao': 2}, 'versão'),
            ({'versao': 1, 'origem': 'simulada'}, 'Registros'),
            (_dados_consumo(_registro_consumo(valor='-1.00')), 'não negativo'),
            (_dados_consumo(_registro_consumo(valor='NaN')), 'não negativo'),
            (
                _dados_consumo(_registro_consumo(recurso=[])),
                'recurso desconhecido',
            ),
            (
                _dados_consumo(_registro_consumo(recurso={})),
                'recurso desconhecido',
            ),
            (
                _dados_consumo(_registro_consumo(recurso=None)),
                'recurso desconhecido',
            ),
            (
                _dados_consumo(_registro_consumo(unidade='m3')),
                'incompatível',
            ),
            (
                _dados_consumo(_registro_consumo(recurso='outro')),
                'desconhecido',
            ),
            (
                _dados_consumo(_registro_consumo(data='2026-02-30')),
                'data inválida',
            ),
            (
                _dados_consumo(_registro_consumo(local='   ')),
                'local obrigatório',
            ),
        ]

        for dados, mensagem in casos:
            with self.subTest(mensagem=mensagem):
                with self.assertRaisesMessage(ValueError, mensagem):
                    validar_dados_consumo(dados)

    def test_rejeita_ids_e_combinacoes_repetidos(self):
        primeiro = _registro_consumo()
        segundo = _registro_consumo(
            id_leitura='C2',
            data='2026-01-02',
        )

        with self.assertRaisesMessage(ValueError, 'Identificador repetido'):
            validar_dados_consumo(
                _dados_consumo(primeiro, {**segundo, 'id_leitura': 'C1'})
            )

        with self.assertRaisesMessage(ValueError, 'combinação'):
            validar_dados_consumo(
                _dados_consumo(primeiro, {**primeiro, 'id_leitura': 'C2'})
            )

    def test_separa_recursos_e_locais_sem_misturar_grupos(self):
        resultado = calcular_indicadores_consumo(
            _dados_consumo(
                _registro_consumo(valor='10.00'),
                _registro_consumo(
                    id_leitura='C2',
                    valor='20.00',
                    data='2026-01-02',
                ),
                _registro_consumo(
                    id_leitura='C3',
                    recurso='agua',
                    unidade='m3',
                    valor='3.00',
                ),
                _registro_consumo(
                    id_leitura='C4',
                    local='Escritorio',
                    valor='30.00',
                ),
            )
        )

        grupos = {
            (grupo['recurso'], grupo['local']): grupo
            for grupo in resultado['grupos']
        }
        self.assertEqual(grupos[('energia', 'Fabrica')]['total'], '30.00')
        self.assertEqual(grupos[('energia', 'Escritorio')]['total'], '30.00')
        self.assertEqual(grupos[('agua', 'Fabrica')]['total'], '3.00')


class EquipamentosDadosTests(TestCase):
    def test_catalogo_real_carrega_e_valida_fixtures_simuladas(self):
        dados = carregar_dados_equipamentos()
        registros = validar_dados_equipamentos(dados)

        self.assertEqual(dados['origem'], 'simulada')
        self.assertEqual(len(registros), 4)
        self.assertEqual(
            {registro['equipamento_id'] for registro in registros},
            {'EQ-F2-001', 'EQ-F2-002', 'EQ-F2-003', 'EQ-F2-004'},
        )

    def test_carregador_rejeita_arquivo_ausente_e_json_invalido(self):
        caminho = os.path.join(
            tempfile.gettempdir(), 'equipamentos_f2_inexistente.json'
        )
        with self.assertRaisesMessage(ValueError, 'carregar os dados'):
            carregar_dados_equipamentos(caminho)

        arquivo = tempfile.NamedTemporaryFile(
            mode='w', encoding='utf-8', suffix='.json', delete=False
        )
        arquivo.write('{nao e json')
        arquivo.close()
        self.addCleanup(os.unlink, arquivo.name)

        with self.assertRaisesMessage(ValueError, 'carregar os dados'):
            carregar_dados_equipamentos(arquivo.name)

    def test_lista_vazia_nao_cria_registros(self):
        self.assertEqual(
            calcular_consumo_por_hora(_dados_equipamentos()),
            {'origem': 'simulada', 'grupos': []},
        )

    def test_exemplo_original_adaptado_retorna_375_kwh_por_hora(self):
        grupo = calcular_consumo_por_hora(_dados_equipamentos(
            _registro_equipamento(
                consumo_kwh='450.00',
                horas_uso='120.00',
            )
        ))['grupos'][0]

        self.assertEqual(grupo['consumo_kwh'], '450.00')
        self.assertEqual(grupo['horas_uso'], '120.00')
        self.assertEqual(grupo['consumo_por_hora'], '3.75')
        self.assertEqual(grupo['unidade_consumo_por_hora'], 'kWh/h')
        self.assertEqual(grupo['avaliacao'], 'disponivel')
        self.assertIsNone(grupo['motivo'])

    def test_multiplos_equipamentos_periodos_e_saida_individual_ordenada(self):
        dados = _dados_equipamentos(
            _registro_equipamento(
                id_registro='E2', equipamento_id='EQ2',
                periodo_inicio='2026-02-01', periodo_fim='2026-02-28',
            ),
            _registro_equipamento(
                id_registro='E1', equipamento_id='EQ1',
                periodo_inicio='2026-02-01', periodo_fim='2026-02-28',
            ),
            _registro_equipamento(
                id_registro='E3', equipamento_id='EQ1',
                periodo_inicio='2026-03-01', periodo_fim='2026-03-31',
            ),
        )

        grupos = calcular_consumo_por_hora(dados)['grupos']

        self.assertEqual(
            [(grupo['equipamento_id'], grupo['periodo_inicio']) for grupo in grupos],
            [('EQ1', '2026-02-01'), ('EQ1', '2026-03-01'), ('EQ2', '2026-02-01')],
        )
        self.assertEqual(len(grupos), 3)
        self.assertNotIn('total', calcular_consumo_por_hora(dados))

    def test_zero_horas_distingue_consumo_zero_de_consumo_positivo(self):
        grupos = calcular_consumo_por_hora(_dados_equipamentos(
            _registro_equipamento(
                id_registro='E1', consumo_kwh='0.00', horas_uso='0.00'
            ),
            _registro_equipamento(
                id_registro='E2', equipamento_id='EQ2',
                consumo_kwh='25.00', horas_uso='0.00'
            ),
        ))['grupos']

        self.assertIsNone(grupos[0]['consumo_por_hora'])
        self.assertEqual(grupos[0]['avaliacao'], 'indisponivel')
        self.assertIn('horas de uso positivas', grupos[0]['motivo'])
        self.assertIsNone(grupos[1]['consumo_por_hora'])
        self.assertEqual(grupos[1]['avaliacao'], 'indisponivel')
        self.assertIn('consumo registrado sem horas', grupos[1]['motivo'])
        self.assertNotIn('desperdício', grupos[1]['motivo'])

    def test_horas_positivas_e_consumo_zero_tem_razao_zero_disponivel(self):
        grupo = calcular_consumo_por_hora(_dados_equipamentos(
            _registro_equipamento(consumo_kwh='0.00', horas_uso='4.00')
        ))['grupos'][0]

        self.assertEqual(grupo['consumo_por_hora'], '0.00')
        self.assertEqual(grupo['avaliacao'], 'disponivel')

    def test_decimal_e_arredondamento_nao_dependem_do_contexto_externo(self):
        with localcontext() as contexto:
            contexto.prec = 6
            contexto.rounding = ROUND_DOWN
            grupo = calcular_consumo_por_hora(_dados_equipamentos(
                _registro_equipamento(
                    consumo_kwh='1.00', horas_uso='6.00'
                )
            ))['grupos'][0]

            self.assertEqual(grupo['consumo_por_hora'], '0.17')
            self.assertEqual(contexto.prec, 6)
            self.assertIs(contexto.rounding, ROUND_DOWN)

    def test_validacao_rejeita_duplicacoes_sobreposicoes_e_identidade(self):
        casos = [
            (
                _dados_equipamentos(
                    _registro_equipamento(),
                    _registro_equipamento(id_registro='E1'),
                ),
                'Identificador repetido',
            ),
            (
                _dados_equipamentos(
                    _registro_equipamento(),
                    _registro_equipamento(
                        id_registro='E2', periodo_inicio='2026-01-31',
                        periodo_fim='2026-02-28'
                    ),
                ),
                'Períodos sobrepostos',
            ),
            (
                _dados_equipamentos(
                    _registro_equipamento(),
                    _registro_equipamento(
                        id_registro='E2', equipamento='Outro nome',
                        periodo_inicio='2026-02-01',
                        periodo_fim='2026-02-28'
                    ),
                ),
                'identidade do equipamento inconsistente',
            ),
        ]

        for dados, mensagem in casos:
            with self.subTest(mensagem=mensagem):
                with self.assertRaisesMessage(ValueError, mensagem):
                    validar_dados_equipamentos(dados)

    def test_ids_de_registro_iguais_em_periodos_diferentes_sao_rejeitados(self):
        dados = _dados_equipamentos(
            _registro_equipamento(
                id_registro='E1',
                periodo_inicio='2026-01-01',
                periodo_fim='2026-01-31',
            ),
            _registro_equipamento(
                id_registro='E1',
                periodo_inicio='2026-02-01',
                periodo_fim='2026-02-28',
            ),
        )

        with self.assertRaisesMessage(ValueError, 'Identificador repetido'):
            validar_dados_equipamentos(dados)

    def test_periodo_repetido_com_ids_diferentes_e_rejeitado(self):
        dados = _dados_equipamentos(
            _registro_equipamento(id_registro='E1'),
            _registro_equipamento(id_registro='E2'),
        )

        with self.assertRaisesMessage(
            ValueError, 'período do equipamento repetido'
        ):
            validar_dados_equipamentos(dados)

    def test_local_diferente_rejeita_identidade_mesmo_com_periodos_distintos(self):
        dados = _dados_equipamentos(
            _registro_equipamento(
                id_registro='E1',
                periodo_inicio='2026-01-01',
                periodo_fim='2026-01-31',
            ),
            _registro_equipamento(
                id_registro='E2',
                local='Outro local',
                periodo_inicio='2026-02-01',
                periodo_fim='2026-02-28',
            ),
        )

        with self.assertRaisesMessage(
            ValueError, 'identidade do equipamento inconsistente'
        ):
            validar_dados_equipamentos(dados)

    def test_periodos_consecutivos_sem_dia_compartilhado_sao_aceitos(self):
        dados = _dados_equipamentos(
            _registro_equipamento(
                id_registro='E1',
                periodo_inicio='2026-01-01',
                periodo_fim='2026-01-31',
            ),
            _registro_equipamento(
                id_registro='E2',
                periodo_inicio='2026-02-01',
                periodo_fim='2026-02-28',
            ),
        )

        grupos = calcular_consumo_por_hora(dados)['grupos']

        self.assertEqual(len(grupos), 2)
        self.assertEqual(
            [(grupo['id_registro'], grupo['periodo_inicio']) for grupo in grupos],
            [('E1', '2026-01-01'), ('E2', '2026-02-01')],
        )

    def test_tipos_de_saida_disponivel_e_indisponivel_sao_explicitos(self):
        grupos = calcular_consumo_por_hora(_dados_equipamentos(
            _registro_equipamento(
                id_registro='E1', consumo_kwh='10.00', horas_uso='4.00'
            ),
            _registro_equipamento(
                id_registro='E2', equipamento_id='EQ2',
                consumo_kwh='0.00', horas_uso='0.00'
            ),
        ))['grupos']
        disponivel, indisponivel = grupos

        self.assertIsInstance(disponivel['consumo_kwh'], str)
        self.assertIsInstance(disponivel['horas_uso'], str)
        self.assertIsInstance(disponivel['consumo_por_hora'], str)
        self.assertEqual(disponivel['avaliacao'], 'disponivel')
        self.assertIsNone(disponivel['motivo'])

        self.assertIsInstance(indisponivel['consumo_kwh'], str)
        self.assertIsInstance(indisponivel['horas_uso'], str)
        self.assertIsNone(indisponivel['consumo_por_hora'])
        self.assertEqual(indisponivel['avaliacao'], 'indisponivel')
        self.assertIsInstance(indisponivel['motivo'], str)
        self.assertTrue(indisponivel['motivo'])

    def test_validacao_rejeita_contrato_tipos_datas_e_valores_invalidos(self):
        casos = [
            ({**_dados_equipamentos(), 'versao': 2}, 'versão'),
            ({**_dados_equipamentos(), 'origem': 'real'}, 'origem'),
            ({'versao': 1, 'origem': 'simulada'}, 'Registros'),
            (_dados_equipamentos(_registro_equipamento(recurso='agua')), 'recurso'),
            (_dados_equipamentos(_registro_equipamento(consumo_kwh='-1.00')), 'não negativo'),
            (_dados_equipamentos(_registro_equipamento(horas_uso='NaN')), 'não negativo'),
            (_dados_equipamentos(_registro_equipamento(consumo_kwh=1.0)), 'não negativo'),
            (_dados_equipamentos(_registro_equipamento(local='   ')), 'local obrigatório'),
            (_dados_equipamentos(_registro_equipamento(periodo_inicio='2026-02-30')), 'periodo_inicio inválido'),
            (_dados_equipamentos(_registro_equipamento(periodo_fim='2025-12-31')), 'período final anterior'),
        ]

        for dados, mensagem in casos:
            with self.subTest(mensagem=mensagem):
                with self.assertRaisesMessage(ValueError, mensagem):
                    validar_dados_equipamentos(dados)


class ConsumoCalculoTests(TestCase):
    def test_valores_originais_de_energia_nao_geram_alertas(self):
        resultado = calcular_indicadores_consumo(carregar_dados_consumo())
        energia = next(
            grupo for grupo in resultado['grupos']
            if grupo['recurso'] == 'energia'
        )

        self.assertEqual(energia['total'], '656.60')
        self.assertEqual(energia['media_por_dia_observado'], '93.80')
        self.assertEqual(energia['dias_observados'], 7)
        self.assertEqual(energia['quantidade_alertas'], 0)
        self.assertEqual(energia['alertas_consumo_elevado'], [])
        self.assertEqual(energia['avaliacao_alerta'], 'disponivel')

    def test_cenario_sintetico_identifica_alerta_sem_provar_desperdicio(self):
        registros = [
            _registro_consumo(
                id_leitura=f'C{i}',
                valor='1.00',
                data=f'2026-01-{i:02d}',
            )
            for i in range(1, 10)
        ]
        registros.append(
            _registro_consumo(
                id_leitura='C10',
                valor='10.00',
                data='2026-01-10',
            )
        )

        grupo = calcular_indicadores_consumo(
            _dados_consumo(*registros)
        )['grupos'][0]

        self.assertEqual(grupo['avaliacao_alerta'], 'disponivel')
        self.assertEqual(grupo['quantidade_alertas'], 1)
        self.assertEqual(grupo['alertas_consumo_elevado'][0]['valor'], '10.00')

    def test_alerta_compara_limite_antes_do_arredondamento(self):
        registros = [
            _registro_consumo(
                id_leitura=f'C{i}',
                valor='1.00',
                data=f'2026-01-{i:02d}',
            )
            for i in range(1, 10)
        ]
        registros.append(
            _registro_consumo(
                id_leitura='C10',
                valor='1.01',
                data='2026-01-10',
            )
        )

        grupo = calcular_indicadores_consumo(
            _dados_consumo(*registros)
        )['grupos'][0]

        self.assertEqual(grupo['limite_consumo_elevado'], '1.01')
        self.assertEqual(grupo['quantidade_alertas'], 1)

    def test_uma_leitura_deixa_avaliacao_indisponivel(self):
        grupo = calcular_indicadores_consumo(
            _dados_consumo(_registro_consumo(valor='0.00'))
        )['grupos'][0]

        self.assertEqual(grupo['total'], '0.00')
        self.assertEqual(grupo['media_por_dia_observado'], '0.00')
        self.assertIsNone(grupo['desvio_padrao_amostral'])
        self.assertIsNone(grupo['limite_consumo_elevado'])
        self.assertIsNone(grupo['quantidade_alertas'])
        self.assertIsNone(grupo['alertas_consumo_elevado'])
        self.assertEqual(grupo['avaliacao_alerta'], 'indisponivel')
        self.assertIn('duas leituras', grupo['motivo_avaliacao'])

    def test_valores_iguais_tem_desvio_zero_e_nenhum_alerta(self):
        grupo = calcular_indicadores_consumo(
            _dados_consumo(
                _registro_consumo(valor='5.00'),
                _registro_consumo(
                    id_leitura='C2',
                    valor='5.00',
                    data='2026-01-02',
                ),
            )
        )['grupos'][0]

        self.assertEqual(grupo['desvio_padrao_amostral'], '0.00')
        self.assertEqual(grupo['limite_consumo_elevado'], '5.00')
        self.assertEqual(grupo['quantidade_alertas'], 0)

    def test_zeros_validos_nao_causam_divisao_por_zero(self):
        grupo = calcular_indicadores_consumo(
            _dados_consumo(
                _registro_consumo(valor='0.00'),
                _registro_consumo(
                    id_leitura='C2',
                    valor='0.00',
                    data='2026-01-02',
                ),
            )
        )['grupos'][0]

        self.assertEqual(grupo['total'], '0.00')
        self.assertEqual(grupo['media_por_dia_observado'], '0.00')
        self.assertEqual(grupo['limite_consumo_elevado'], '0.00')
        self.assertEqual(grupo['quantidade_alertas'], 0)

    def test_ordena_datas_e_nao_preenche_dias_ausentes(self):
        grupo = calcular_indicadores_consumo(
            _dados_consumo(
                _registro_consumo(
                    id_leitura='C2',
                    valor='30.00',
                    data='2026-01-03',
                ),
                _registro_consumo(
                    id_leitura='C1',
                    valor='10.00',
                    data='2026-01-01',
                ),
            )
        )['grupos'][0]

        self.assertEqual(grupo['inicio'], '2026-01-01')
        self.assertEqual(grupo['fim'], '2026-01-03')
        self.assertEqual(grupo['dias_observados'], 2)
        self.assertEqual(grupo['total'], '40.00')

    def test_campos_numericos_sao_strings_e_indisponiveis_sao_null(self):
        grupos = calcular_indicadores_consumo(
            _dados_consumo(
                _registro_consumo(valor='10.00'),
                _registro_consumo(
                    id_leitura='C2',
                    valor='20.00',
                    data='2026-01-02',
                ),
                _registro_consumo(
                    id_leitura='C3',
                    valor='5.00',
                    data='2026-01-03',
                    local='Escritorio',
                ),
            )
        )['grupos']
        grupo_com_avaliacao = next(
            grupo for grupo in grupos if grupo['local'] == 'Fabrica'
        )
        grupo_indisponivel = next(
            grupo for grupo in grupos if grupo['local'] == 'Escritorio'
        )

        for campo in (
            'total',
            'media_por_dia_observado',
            'desvio_padrao_amostral',
            'limite_consumo_elevado',
        ):
            self.assertIsInstance(grupo_com_avaliacao[campo], str)

        self.assertIsNone(grupo_indisponivel['desvio_padrao_amostral'])
        self.assertIsNone(grupo_indisponivel['limite_consumo_elevado'])
        self.assertIsNone(grupo_indisponivel['alertas_consumo_elevado'])
        self.assertIsNone(grupo_indisponivel['quantidade_alertas'])
        self.assertIsInstance(grupo_indisponivel['total'], str)
        self.assertIsInstance(
            grupo_indisponivel['media_por_dia_observado'],
            str,
        )

    def test_calculo_isola_contexto_decimal_externo(self):
        dados = _dados_consumo(
            _registro_consumo(valor='1.00'),
            _registro_consumo(
                id_leitura='C2',
                valor='1.01',
                data='2026-01-02',
            ),
        )
        esperado = calcular_indicadores_consumo(dados)

        with localcontext() as contexto_externo:
            contexto_externo.prec = 4
            contexto_externo.rounding = ROUND_DOWN
            precisao_antes = getcontext().prec
            arredondamento_antes = getcontext().rounding

            resultado = calcular_indicadores_consumo(dados)

            self.assertEqual(resultado, esperado)
            self.assertEqual(getcontext().prec, precisao_antes)
            self.assertEqual(
                getcontext().rounding,
                arredondamento_antes,
            )


class ConsumoApiTests(TestCase):
    def test_get_retorna_json_com_grupos_de_agua_e_energia(self):
        esperado = calcular_indicadores_consumo(
            carregar_dados_consumo()
        )

        response = self.client.get(
            reverse('indicadores_consumo'),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), esperado)
        self.assertEqual(response.json()['origem'], 'simulada')
        self.assertEqual(
            {grupo['recurso'] for grupo in response.json()['grupos']},
            {'agua', 'energia'},
        )

        for grupo in response.json()['grupos']:
            for campo in (
                'total',
                'media_por_dia_observado',
                'desvio_padrao_amostral',
                'limite_consumo_elevado',
            ):
                self.assertIsInstance(grupo[campo], str)

    @patch('appweb.views.carregar_dados_consumo')
    def test_dados_vazios_retorna_grupos_vazios(self, mock_carregar):
        mock_carregar.return_value = _dados_consumo()

        response = self.client.get(
            reverse('indicadores_consumo'),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'origem': 'simulada',
            'grupos': [],
        })

    @patch('appweb.views.carregar_dados_consumo')
    def test_uma_leitura_preserva_avaliacao_indisponivel(self, mock_carregar):
        mock_carregar.return_value = _dados_consumo(
            _registro_consumo(valor='0.00')
        )

        response = self.client.get(
            reverse('indicadores_consumo'),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        grupo = response.json()['grupos'][0]
        self.assertEqual(grupo['avaliacao_alerta'], 'indisponivel')
        self.assertIsNone(grupo['desvio_padrao_amostral'])
        self.assertIsNone(grupo['limite_consumo_elevado'])
        self.assertIsNone(grupo['alertas_consumo_elevado'])
        self.assertIsNone(grupo['quantidade_alertas'])

    def test_post_retorna_405(self):
        response = self.client.post(
            reverse('indicadores_consumo'),
            secure=True,
        )

        self.assertEqual(response.status_code, 405)

    @patch('appweb.views.carregar_dados_consumo')
    def test_falha_de_carregamento_retorna_erro_generico(
        self,
        mock_carregar,
    ):
        mock_carregar.side_effect = ValueError(
            'detalhe interno do arquivo de consumo'
        )

        response = self.client.get(
            reverse('indicadores_consumo'),
            secure=True,
        )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json(),
            {'erro': 'Não foi possível carregar os indicadores de consumo.'},
        )
        self.assertNotIn('detalhe interno', response.content.decode())

    @patch('appweb.views.carregar_dados_consumo')
    def test_dados_invalidos_retorna_erro_generico(self, mock_carregar):
        mock_carregar.return_value = _dados_consumo(
            _registro_consumo(recurso='desconhecido')
        )

        response = self.client.get(
            reverse('indicadores_consumo'),
            secure=True,
        )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json(),
            {'erro': 'Não foi possível carregar os indicadores de consumo.'},
        )
        self.assertNotIn('desconhecido', response.content.decode())


class EquipamentosApiTests(TestCase):
    def test_url_efetiva_e_get_retorna_json_do_servico(self):
        self.assertEqual(
            reverse('consumo_por_hora_equipamentos'),
            '/equipamentos/consumo-por-hora',
        )

        esperado = calcular_consumo_por_hora(
            carregar_dados_equipamentos()
        )
        response = self.client.get(
            reverse('consumo_por_hora_equipamentos'),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertEqual(response.json(), esperado)

    def test_get_preserva_identidade_periodos_unidades_e_exemplo_original(self):
        response = self.client.get(
            reverse('consumo_por_hora_equipamentos'),
            secure=True,
        )
        dados = response.json()

        self.assertEqual(dados['origem'], 'simulada')
        self.assertEqual(len(dados['grupos']), 4)
        primeiro = next(
            grupo for grupo in dados['grupos']
            if grupo['equipamento_id'] == 'EQ-F2-001'
        )
        self.assertEqual(primeiro['equipamento'], 'Motor Industrial')
        self.assertEqual(primeiro['local'], 'Fabrica F2')
        self.assertEqual(primeiro['recurso'], 'energia')
        self.assertEqual(primeiro['unidade_consumo'], 'kWh')
        self.assertEqual(primeiro['unidade_horas'], 'h')
        self.assertEqual(primeiro['unidade_consumo_por_hora'], 'kWh/h')
        self.assertEqual(primeiro['periodo_inicio'], '2026-10-01')
        self.assertEqual(primeiro['periodo_fim'], '2026-10-31')
        self.assertEqual(primeiro['consumo_kwh'], '450.00')
        self.assertEqual(primeiro['horas_uso'], '120.00')
        self.assertEqual(primeiro['consumo_por_hora'], '3.75')

    def test_get_preserva_strings_motivos_e_razoes_indisponiveis(self):
        grupos = self.client.get(
            reverse('consumo_por_hora_equipamentos'),
            secure=True,
        ).json()['grupos']
        por_id = {grupo['equipamento_id']: grupo for grupo in grupos}

        for grupo in grupos:
            self.assertIsInstance(grupo['consumo_kwh'], str)
            self.assertIsInstance(grupo['horas_uso'], str)

        self.assertIsNone(por_id['EQ-F2-003']['consumo_por_hora'])
        self.assertIsNone(por_id['EQ-F2-004']['consumo_por_hora'])
        self.assertEqual(por_id['EQ-F2-003']['avaliacao'], 'indisponivel')
        self.assertEqual(por_id['EQ-F2-004']['avaliacao'], 'indisponivel')
        self.assertIsInstance(por_id['EQ-F2-003']['motivo'], str)
        self.assertIsInstance(por_id['EQ-F2-004']['motivo'], str)
        self.assertIn('horas de uso positivas', por_id['EQ-F2-003']['motivo'])
        self.assertIn('consumo registrado sem horas', por_id['EQ-F2-004']['motivo'])

    def test_get_preserva_consumo_zero_com_horas_positivas(self):
        grupo = next(
            grupo for grupo in self.client.get(
                reverse('consumo_por_hora_equipamentos'),
                secure=True,
            ).json()['grupos']
            if grupo['equipamento_id'] == 'EQ-F2-002'
        )

        self.assertEqual(grupo['consumo_kwh'], '0.00')
        self.assertEqual(grupo['horas_uso'], '80.00')
        self.assertEqual(grupo['consumo_por_hora'], '0.00')
        self.assertEqual(grupo['avaliacao'], 'disponivel')
        self.assertIsNone(grupo['motivo'])

    @patch('appweb.views.carregar_dados_equipamentos')
    def test_dados_vazios_retorna_grupos_vazios(self, mock_carregar):
        mock_carregar.return_value = _dados_equipamentos()

        response = self.client.get(
            reverse('consumo_por_hora_equipamentos'),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {'origem': 'simulada', 'grupos': []},
        )

    def test_post_retorna_405(self):
        response = self.client.post(
            reverse('consumo_por_hora_equipamentos'),
            secure=True,
        )

        self.assertEqual(response.status_code, 405)

    @patch('appweb.views.carregar_dados_equipamentos')
    def test_falha_de_carregamento_retorna_erro_generico(self, mock_carregar):
        mock_carregar.side_effect = ValueError(
            'detalhe interno do arquivo de equipamentos'
        )

        response = self.client.get(
            reverse('consumo_por_hora_equipamentos'),
            secure=True,
        )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json(),
            {'erro': 'Não foi possível carregar os indicadores de equipamentos.'},
        )
        self.assertNotIn('detalhe interno', response.content.decode())

    @patch('appweb.views.carregar_dados_equipamentos')
    def test_dados_invalidos_retorna_erro_generico(self, mock_carregar):
        mock_carregar.return_value = _dados_equipamentos(
            _registro_equipamento(recurso='agua')
        )

        response = self.client.get(
            reverse('consumo_por_hora_equipamentos'),
            secure=True,
        )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json(),
            {'erro': 'Não foi possível carregar os indicadores de equipamentos.'},
        )
        self.assertNotIn('recurso deve ser energia', response.content.decode())


class EquipamentosPaginaTests(TestCase):
    def test_pagina_renderiza_template_rota_e_avisos(self):
        response = self.client.get(
            reverse('painel_equipamentos'),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            'appweb/painel_equipamentos.html',
        )
        self.assertEqual(
            resolve('/painel-equipamentos/').url_name,
            'painel_equipamentos',
        )
        self.assertContains(response, 'Consumo por equipamento e hora de uso')
        conteudo_normalizado = ' '.join(
            response.content.decode('utf-8').split()
        )
        self.assertIn(
            'dados e períodos são cenários simulados',
            conteudo_normalizado,
        )
        self.assertIn(
            'não representam medições reais já realizadas',
            conteudo_normalizado,
        )
        self.assertIn(
            'Não há vínculo automático com Social ou F1.',
            conteudo_normalizado,
        )
        self.assertIn(
            'não classificação de eficiência',
            conteudo_normalizado,
        )
        self.assertIn(
            'Não há ranking nem comparação automática entre funções diferentes.',
            conteudo_normalizado,
        )
        self.assertContains(
            response,
            f'"{reverse("consumo_por_hora_equipamentos")}"',
        )

    def test_menu_destaca_especificamente_equipamentos_e_preserva_rotas(self):
        response = self.client.get(
            reverse('painel_equipamentos'),
            secure=True,
        )
        conteudo = response.content.decode('utf-8')
        equipamentos_url = re.escape(reverse('painel_equipamentos'))

        self.assertRegex(
            conteudo,
            rf'<a href="{equipamentos_url}"\s+aria-current="page">\s*'
            r'Equipamentos\s*</a>',
        )
        self.assertContains(response, f'href="{reverse("home")}"')
        self.assertContains(response, f'href="{reverse("painel_consumo")}"')
        self.assertContains(response, f'href="{reverse("painel_social")}"')


class ConsumoPaginaTests(TestCase):
    def test_pagina_renderiza_template_rota_e_menu_atual(self):
        response = self.client.get(
            reverse('painel_consumo'),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            'appweb/painel_consumo.html',
        )
        self.assertEqual(
            resolve('/painel-consumo/').url_name,
            'painel_consumo',
        )

        self.assertContains(response, 'Consumo de água e energia')
        self.assertContains(response, 'dados simulados')
        self.assertContains(response, 'diário total')
        self.assertContains(response, 'não uma leitura acumulada de medidor')
        self.assertContains(response, 'média + 2 desvios-padrão amostrais')
        self.assertContains(response, 'consumo elevado')
        self.assertContains(response, 'não desperdício comprovado')
        self.assertContains(
            response,
            f'"{reverse("indicadores_consumo")}"',
        )

        pagina_url = re.escape(reverse('painel_consumo'))
        self.assertRegex(
            response.content.decode('utf-8'),
            rf'<a href="{pagina_url}"\s+aria-current="page">\s*'
            r'Consumo\s*</a>',
        )
