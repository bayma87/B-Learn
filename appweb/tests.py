import os
import re
import tempfile
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
from appweb.recomendacoes import (
    MOTIVO_ECONOMIA_INVALIDA,
    carregar_catalogo_acoes,
    gerar_recomendacoes,
    validar_catalogo_acoes,
)


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
        self.assertContains(
            response,
            'não são personalizadas pelos indicadores',
        )
        self.assertContains(response, 'F1–F4')
        self.assertContains(response, 'retorno financeiro')
        self.assertContains(response, 'estimado da ação')
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
