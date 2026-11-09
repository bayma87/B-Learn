
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
