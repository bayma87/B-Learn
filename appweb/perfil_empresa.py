
import re
from decimal import Decimal


VALOR_RE = re.compile(r'^(0|[1-9][0-9]*)(\.[0-9]{1,2})?$')

PORTES_VALIDOS = {'micro', 'pequena', 'media'}


def validar_perfil_empresa(dados):
    if not isinstance(dados, dict):
        raise ValueError('O perfil deve ser um objeto.')

    porte = dados.get('porte')

    if porte not in PORTES_VALIDOS:
        raise ValueError('Porte da empresa inválido.')

    campos = [
        'faturamento_mensal',
        'area_m2',
        'orcamento_total',
        'orcamento_mensal',
    ]

    valores = {}

    for campo in campos:
        valor = dados.get(campo)

        if not isinstance(valor, str) or not VALOR_RE.fullmatch(valor):
            raise ValueError(f'{campo}: valor inválido.')

        valores[campo] = Decimal(valor)

    if valores['faturamento_mensal'] <= 0:
        raise ValueError('O faturamento deve ser maior que zero.')

    if valores['area_m2'] <= 0:
        raise ValueError('A área deve ser maior que zero.')

    if valores['orcamento_total'] <= 0:
        raise ValueError('O orçamento total deve ser maior que zero.')

    if valores['orcamento_mensal'] <= 0:
        raise ValueError('O orçamento mensal deve ser maior que zero.')

    return {
        'porte': porte,
        **valores,
    }
from decimal import ROUND_CEILING


def filtrar_acoes_por_perfil(recomendacoes, perfil):
    orcamento_total = perfil['orcamento_total']
    orcamento_mensal = perfil['orcamento_mensal']

    recomendacoes_viaveis = []

    for recomendacao in recomendacoes:
        custo = Decimal(
            recomendacao['investimento_sugerido']['recomendado']
        )

        if custo > orcamento_total:
            continue

        meses = int(
            (custo / orcamento_mensal).to_integral_value(
                rounding=ROUND_CEILING
            )
        )

        item = recomendacao.copy()
        item['meses_para_juntar'] = meses

        recomendacoes_viaveis.append(item)

    recomendacoes_viaveis.sort(
        key=lambda item: item['meses_para_juntar']
    )

    return recomendacoes_viaveis
