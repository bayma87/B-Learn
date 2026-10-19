"""Comparativos demonstrativos antes/depois para sugestões selecionadas (F6)."""

import copy
import re
from decimal import Decimal


_DECIMAL_RE = re.compile(r'(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z')
_MENSAGEM = (
    'O depois é uma estimativa demonstrativa, não uma medição pós-ação '
    'nem uma garantia de resultado.'
)


def _validar_fonte(indicadores, fonte):
    if indicadores is None:
        return None

    if not isinstance(indicadores, dict):
        raise ValueError(f'Indicadores de {fonte} devem ser um objeto.')

    if indicadores.get('situacao') in {'sem_dados', 'indisponivel'}:
        return None

    if indicadores.get('origem') != 'simulada':
        raise ValueError(f'Indicadores de {fonte} devem ter origem simulada.')

    total = indicadores.get('total')
    if not isinstance(total, dict):
        raise ValueError(f'Indicadores de {fonte} devem conter total.')
    return total


def calcular_comparativo_acao(
    acao,
    indicadores_sociais,
    indicadores_residuos,
):
    """Retorna comparação demonstrativa somente para A05 ou A06."""
    if not isinstance(acao, dict):
        raise ValueError('A ação selecionada deve ser um objeto.')

    id_acao = acao.get('id_acao')
    if not isinstance(id_acao, str) or not id_acao.strip():
        raise ValueError('A ação selecionada deve conter id_acao.')

    if id_acao not in {'A05', 'A06'}:
        return None

    total_social = _validar_fonte(indicadores_sociais, 'Social')
    total_residuos = _validar_fonte(indicadores_residuos, 'Resíduos')

    if id_acao == 'A05':
        if total_residuos is None:
            return None
        antes = total_residuos.get('nao_reciclado_kg')
        if (
            not isinstance(antes, str) or
            not _DECIMAL_RE.fullmatch(antes) or
            not Decimal(antes).is_finite()
        ):
            raise ValueError(
                'Indicadores de Resíduos têm nao_reciclado_kg inválido.'
            )
        return {
            'indicador': 'residuos.total.nao_reciclado_kg',
            'escopo': 'agregado',
            'unidade': 'kg',
            'antes': antes,
            'depois': '0.00',
            'natureza': 'estimativa_demonstrativa',
            'mensagem': _MENSAGEM,
        }

    if total_social is None:
        return None
    antes = total_social.get('alertas_seguranca')
    if type(antes) is not int or antes < 0:
        raise ValueError(
            'Indicadores de Social têm alertas_seguranca inválidos.'
        )
    return {
        'indicador': 'social.total.alertas_seguranca',
        'escopo': 'agregado',
        'unidade': 'alertas',
        'antes': antes,
        'depois': 0,
        'natureza': 'estimativa_demonstrativa',
        'mensagem': _MENSAGEM,
    }


def adicionar_comparativo(
    sugestao,
    indicadores_sociais,
    indicadores_residuos,
):
    """Copia uma sugestão e anexa o comparativo quando aplicável."""
    resultado = copy.deepcopy(sugestao)
    comparativo = calcular_comparativo_acao(
        resultado,
        indicadores_sociais,
        indicadores_residuos,
    )
    if comparativo is not None:
        resultado['comparativo'] = comparativo
    return resultado
