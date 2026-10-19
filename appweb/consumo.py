"""Indicadores demonstrativos de consumo de água e energia (F1).

A estrutura inicial de energia foi adaptada da contribuição de Arthur Alencar,
na branch ``origin/feature/dados-iot``, commit ``9b3bd73``. Esta adaptação
preserva somente a parte F1 e a regra de referência ``média + 2 desvios``.

Os dados deste módulo representam consumo diário total, não leituras
acumuladas de medidor. Um alerta significa consumo elevado possivelmente
associado a desperdício; não comprova desperdício.
"""

import json
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, localcontext
from pathlib import Path


PRECISAO_CALCULO = 28
ARREDONDAMENTO = ROUND_HALF_UP
CASAS_APRESENTACAO = Decimal('0.01')

RECURSOS_UNIDADES = {
    'energia': 'kWh',
    'agua': 'm3',
}

_VALOR_RE = re.compile(r'(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z')


def carregar_dados_consumo(caminho=None):
    """Carrega o catálogo simulado de consumo sem usar fallback artificial."""
    if caminho is None:
        caminho = Path(__file__).parent / 'dados' / 'consumo.json'

    try:
        conteudo = Path(caminho).read_text(encoding='utf-8')
        return json.loads(conteudo)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            'Não foi possível carregar os dados de consumo.'
        ) from exc


def _validar_valor(valor, posicao):
    if not isinstance(valor, str) or not _VALOR_RE.fullmatch(valor):
        raise ValueError(
            f'Registro {posicao}: valor deve ser decimal não negativo.'
        )

    convertido = Decimal(valor)
    if not convertido.is_finite() or convertido < 0:
        raise ValueError(
            f'Registro {posicao}: valor deve ser decimal não negativo.'
        )

    return convertido


def validar_dados_consumo(dados):
    """Valida o contrato F1 e devolve registros normalizados com Decimal."""
    if not isinstance(dados, dict):
        raise ValueError('A entrada deve ser um objeto JSON.')

    if type(dados.get('versao')) is not int or dados['versao'] != 1:
        raise ValueError('A versão deve ser o número inteiro 1.')

    if dados.get('origem') != 'simulada':
        raise ValueError('Esta versão aceita apenas origem simulada.')

    registros = dados.get('registros')
    if not isinstance(registros, list):
        raise ValueError('Registros deve ser uma lista.')

    validados = []
    ids = set()
    combinacoes = set()

    for posicao, registro in enumerate(registros, start=1):
        if not isinstance(registro, dict):
            raise ValueError(f'Registro {posicao}: formato inválido.')

        identificador = registro.get('id_leitura')
        recurso = registro.get('recurso')
        valor = registro.get('valor')
        unidade = registro.get('unidade')
        data_texto = registro.get('data')
        local = registro.get('local')

        if not isinstance(identificador, str) or not identificador.strip():
            raise ValueError(f'Registro {posicao}: id_leitura obrigatório.')
        identificador = identificador.strip()

        if identificador in ids:
            raise ValueError(f'Identificador repetido: {identificador}.')

        if not isinstance(recurso, str) or recurso not in RECURSOS_UNIDADES:
            raise ValueError(f'Registro {posicao}: recurso desconhecido.')

        if unidade != RECURSOS_UNIDADES[recurso]:
            raise ValueError(
                f'Registro {posicao}: unidade incompatível com o recurso.'
            )

        if not isinstance(local, str) or not local.strip():
            raise ValueError(f'Registro {posicao}: local obrigatório.')
        local = local.strip()

        if not isinstance(data_texto, str):
            raise ValueError(f'Registro {posicao}: data obrigatória.')

        try:
            data_consumo = date.fromisoformat(data_texto)
        except ValueError:
            raise ValueError(f'Registro {posicao}: data inválida.') from None

        if data_consumo.isoformat() != data_texto:
            raise ValueError(
                f'Registro {posicao}: use data ISO AAAA-MM-DD.'
            )

        valor_decimal = _validar_valor(valor, posicao)
        combinacao = (recurso, local, data_consumo)
        if combinacao in combinacoes:
            raise ValueError(
                f'Registro {posicao}: combinação recurso, local e data '
                'repetida.'
            )

        ids.add(identificador)
        combinacoes.add(combinacao)
        validados.append({
            'id_leitura': identificador,
            'recurso': recurso,
            'valor': valor_decimal,
            'unidade': unidade,
            'data': data_consumo,
            'local': local,
        })

    return validados


def _formatar_decimal(valor):
    with localcontext() as contexto:
        contexto.prec = PRECISAO_CALCULO
        contexto.rounding = ARREDONDAMENTO
        quantizado = valor.quantize(
            CASAS_APRESENTACAO,
            rounding=ARREDONDAMENTO,
        )
        return f'{quantizado:f}'


def _desvio_padrao_amostral(valores):
    with localcontext() as contexto:
        contexto.prec = PRECISAO_CALCULO
        contexto.rounding = ARREDONDAMENTO
        media = sum(valores, Decimal('0')) / len(valores)
        variancia = sum(
            ((valor - media) ** 2 for valor in valores),
            Decimal('0'),
        ) / (len(valores) - 1)
        return variancia.sqrt()


def _resumir_grupo(recurso, local, registros):
    with localcontext() as contexto:
        contexto.prec = PRECISAO_CALCULO
        contexto.rounding = ARREDONDAMENTO

        registros = sorted(registros, key=lambda registro: registro['data'])
        valores = [registro['valor'] for registro in registros]
        total = sum(valores, Decimal('0'))
        media = total / len(valores)
        inicio = registros[0]['data'].isoformat()
        fim = registros[-1]['data'].isoformat()

        resultado = {
            'recurso': recurso,
            'unidade': RECURSOS_UNIDADES[recurso],
            'local': local,
            'inicio': inicio,
            'fim': fim,
            'dias_observados': len(registros),
            'total': _formatar_decimal(total),
            'media_por_dia_observado': _formatar_decimal(media),
            'desvio_padrao_amostral': None,
            'limite_consumo_elevado': None,
            'avaliacao_alerta': 'indisponivel',
            'motivo_avaliacao': None,
            'alertas_consumo_elevado': None,
            'quantidade_alertas': None,
        }

        if len(valores) < 2:
            resultado['motivo_avaliacao'] = (
                'São necessárias pelo menos duas leituras para avaliar '
                'consumo elevado.'
            )
            return resultado

        desvio = _desvio_padrao_amostral(valores)
        limite = media + (Decimal('2') * desvio)
        alertas = [
            {
                'data': registro['data'].isoformat(),
                'valor': _formatar_decimal(registro['valor']),
            }
            for registro in registros
            if registro['valor'] > limite
        ]

        resultado.update({
            'desvio_padrao_amostral': _formatar_decimal(desvio),
            'limite_consumo_elevado': _formatar_decimal(limite),
            'avaliacao_alerta': 'disponivel',
            'alertas_consumo_elevado': alertas,
            'quantidade_alertas': len(alertas),
        })
        return resultado


def calcular_indicadores_consumo(dados):
    """Calcula indicadores agrupados por recurso e local."""
    registros = validar_dados_consumo(dados)
    grupos = defaultdict(list)

    for registro in registros:
        grupos[(registro['recurso'], registro['local'])].append(registro)

    resultados = [
        _resumir_grupo(recurso, local, grupos[(recurso, local)])
        for recurso, local in sorted(grupos)
    ]

    return {
        'origem': dados['origem'],
        'grupos': resultados,
    }
