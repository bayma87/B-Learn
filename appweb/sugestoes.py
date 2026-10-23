"""Seleção demonstrativa de sugestões orientadas por indicadores.

Este módulo recebe somente saídas já calculadas pelos serviços de F3, F4 e
F5. Não carrega arquivos, não faz requisições e não recalcula indicadores ou
valores financeiros. As fontes atuais de Social e Resíduos são agregadas;
por isso, suas evidências não recebem local ou período inventados.
"""

import copy
import re
from decimal import Decimal


SITUACAO_AVALIADA = 'avaliada'
SITUACAO_SEM_DADOS = 'sem_dados'
SITUACAO_INDISPONIVEL = 'indisponivel'
_SITUACOES_ESPECIAIS = {SITUACAO_SEM_DADOS, SITUACAO_INDISPONIVEL}
_DECIMAL_RE = re.compile(r'(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z')


def _validar_acoes(recomendacoes):
    if not isinstance(recomendacoes, list):
        raise ValueError('As recomendações financeiras devem ser uma lista.')

    validadas = []
    identificadores = set()
    for posicao, acao in enumerate(recomendacoes, start=1):
        if not isinstance(acao, dict):
            raise ValueError(f'Ação financeira {posicao}: formato inválido.')

        identificador = acao.get('id_acao')
        if not isinstance(identificador, str) or not identificador.strip():
            raise ValueError(
                f'Ação financeira {posicao}: id_acao obrigatório.'
            )

        if identificador != identificador.strip():
            raise ValueError(
                f'Ação financeira {posicao}: id_acao não pode ter espaços '
                'nas extremidades.'
            )

        identificador = identificador.strip()
        if identificador in identificadores:
            raise ValueError(
                f'Ação financeira {posicao}: id_acao repetido.'
            )

        if not isinstance(acao.get('acao'), str) or not acao['acao'].strip():
            raise ValueError(
                f'Ação financeira {posicao}: campo acao inválido.'
            )

        identificadores.add(identificador)
        validadas.append(acao)

    return validadas


def _situacao_especial(indicadores, fonte):
    if indicadores is None:
        return {
            'situacao': SITUACAO_SEM_DADOS,
        }

    if not isinstance(indicadores, dict):
        raise ValueError(f'Indicadores de {fonte} devem ser um objeto.')

    situacao = indicadores.get('situacao')
    if situacao == SITUACAO_SEM_DADOS:
        if set(indicadores) != {'situacao'}:
            raise ValueError(
                f'Indicadores de {fonte} têm contrato de ausência inválido.'
            )
        return {'situacao': SITUACAO_SEM_DADOS}

    if situacao == SITUACAO_INDISPONIVEL:
        motivo = indicadores.get('motivo')
        if (
            set(indicadores) != {'situacao', 'motivo'} or
            not isinstance(motivo, str) or
            not motivo.strip()
        ):
            raise ValueError(
                f'Indicadores de {fonte} têm contrato de indisponibilidade '
                'inválido.'
            )
        return {
            'situacao': SITUACAO_INDISPONIVEL,
            'motivo': motivo,
        }

    return None


def _validar_origem(indicadores, fonte):
    if indicadores.get('origem') != 'simulada':
        raise ValueError(f'Indicadores de {fonte} devem ter origem simulada.')


def _validar_social(indicadores):
    especial = _situacao_especial(indicadores, 'Social')
    if especial is not None:
        return especial, None

    _validar_origem(indicadores, 'Social')
    total = indicadores.get('total')
    if not isinstance(total, dict):
        raise ValueError('Indicadores de Social devem conter total.')

    alertas = total.get('alertas_seguranca')
    status = total.get('status')
    if type(alertas) is not int or alertas < 0:
        raise ValueError(
            'Indicadores de Social têm alertas_seguranca inválidos.'
        )
    if (
        not isinstance(status, str) or
        status not in {'verde', 'amarelo', 'vermelho'}
    ):
        raise ValueError('Indicadores de Social têm status inválido.')

    avaliacao = {
        'situacao': SITUACAO_AVALIADA,
        'escopo': 'agregado',
    }
    evidencia = {
        'indicador': 'social.total.status',
        'escopo': 'agregado',
        'valores_observados': {
            'status': status,
            'alertas_seguranca': alertas,
        },
    }
    return avaliacao, {
        'status': status,
        'evidencia': evidencia,
    }


def _validar_residuos(indicadores):
    especial = _situacao_especial(indicadores, 'Resíduos')
    if especial is not None:
        return especial, None

    origem = indicadores.get('origem')
    if origem not in {'simulada', 'informada_pelo_usuario'}:
        raise ValueError('Indicadores de Resíduos devem ter origem simulada ou informada_pelo_usuario.')

    total = indicadores.get('total')
    if not isinstance(total, dict):
        raise ValueError('Indicadores de Resíduos devem conter total.')

    nao_reciclado = total.get('nao_reciclado_kg')
    if (
        not isinstance(nao_reciclado, str) or
        not _DECIMAL_RE.fullmatch(nao_reciclado) or
        not Decimal(nao_reciclado).is_finite()
    ):
        raise ValueError(
            'Indicadores de Resíduos têm nao_reciclado_kg inválido.'
        )

    avaliacao = {
        'situacao': SITUACAO_AVALIADA,
        'escopo': 'agregado',
    }
    evidencia = {
        'indicador': 'residuos.total.nao_reciclado_kg',
        'escopo': 'agregado',
        'valores_observados': {
            'nao_reciclado_kg': nao_reciclado,
        },
    }
    return avaliacao, {
        'nao_reciclado': Decimal(nao_reciclado),
        'evidencia': evidencia,
    }


def _sugestao(acao, regra, justificativa, evidencia):
    resultado = copy.deepcopy(acao)
    resultado.update({
        'justificativa': justificativa,
        'regra_aplicada': regra,
        'evidencias': [evidencia],
        'natureza_financeira': 'estimativa_do_catalogo',
    })
    return resultado


def selecionar_sugestoes_orientadas(
    recomendacoes,
    indicadores_sociais,
    indicadores_residuos,
):
    """Seleciona no máximo uma sugestão por ação, sem alterar entradas."""
    acoes = _validar_acoes(recomendacoes)
    avaliacao_social, evidencia_social = _validar_social(indicadores_sociais)
    avaliacao_residuos, evidencia_residuos = _validar_residuos(
        indicadores_residuos
    )

    por_id = {acao['id_acao']: acao for acao in acoes}
    sugestoes_por_id = {}

    if (
        evidencia_residuos is not None and
        evidencia_residuos['nao_reciclado'] > 0 and
        'A05' in por_id
    ):
        sugestoes_por_id['A05'] = _sugestao(
            por_id['A05'],
            'A05_quantidade_nao_reciclada_positiva',
            'Avaliar segregação e coleta seletiva diante da quantidade '
            'não reciclada observada. Isso não afirma que toda essa '
            'quantidade seja reciclável.',
            evidencia_residuos['evidencia'],
        )

    if (
        evidencia_social is not None and
        evidencia_social['status'] == 'vermelho' and
        'A06' in por_id
    ):
        sugestoes_por_id['A06'] = _sugestao(
            por_id['A06'],
            'A06_status_seguranca_vermelho',
            'Avaliar treinamento e medidas de segurança diante do status '
            'observado. Isso não atribui a causa dos alertas à falta de '
            'treinamento ou EPI.',
            evidencia_social['evidencia'],
        )

    sugestoes = [
        sugestoes_por_id[acao['id_acao']]
        for acao in acoes
        if acao['id_acao'] in sugestoes_por_id
    ]

    return {
        'origem': 'simulada',
        'avaliacao_fontes': {
            'social': avaliacao_social,
            'residuos': avaliacao_residuos,
        },
        'sugestoes_orientadas': sugestoes,
    }
