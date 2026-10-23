"""Consumo demonstrativo por equipamento e hora de uso (F2).

A fórmula conceitual e o exemplo numérico desta adaptação vêm da contribuição
de Arthur Alencar, na branch ``feature/dados-iot``, commit ``9b3bd73``:
450 kWh / 120 horas = 3,75 kWh/h. Os identificadores, nomes de catálogo,
locais e períodos usados aqui são fixtures novas e simuladas do projeto.

Este módulo não relaciona automaticamente os registros com Social ou F1.
"""

import json
import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, localcontext
from pathlib import Path


PRECISAO_CALCULO = 28
ARREDONDAMENTO = ROUND_HALF_UP
CASAS_APRESENTACAO = Decimal('0.01')
_VALOR_RE = re.compile(r'(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z')


def carregar_dados_equipamentos(caminho=None):
    """Carrega fixtures simuladas sem fallback artificial."""
    if caminho is None:
        caminho = Path(__file__).parent / 'dados' / 'equipamentos.json'

    try:
        conteudo = Path(caminho).read_text(encoding='utf-8')
        return json.loads(conteudo)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            'Não foi possível carregar os dados de equipamentos.'
        ) from exc


def _validar_decimal(valor, campo, posicao):
    if not isinstance(valor, str) or not _VALOR_RE.fullmatch(valor):
        raise ValueError(
            f'Registro {posicao}: {campo} deve ser decimal não negativo.'
        )

    convertido = Decimal(valor)
    if not convertido.is_finite() or convertido < 0:
        raise ValueError(
            f'Registro {posicao}: {campo} deve ser decimal não negativo.'
        )

    return convertido


def _validar_data(valor, campo, posicao):
    if not isinstance(valor, str):
        raise ValueError(f'Registro {posicao}: {campo} obrigatório.')

    try:
        data = date.fromisoformat(valor)
    except ValueError:
        raise ValueError(f'Registro {posicao}: {campo} inválido.') from None

    if data.isoformat() != valor:
        raise ValueError(
            f'Registro {posicao}: {campo} deve usar AAAA-MM-DD.'
        )

    return data


def _texto_obrigatorio(valor, campo, posicao):
    if not isinstance(valor, str) or not valor.strip():
        raise ValueError(f'Registro {posicao}: {campo} obrigatório.')
    return valor.strip()


def validar_dados_equipamentos(dados):
    """Valida o contrato F2 e devolve registros com valores normalizados."""
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
    chaves_periodos = set()
    identidades = {}

    for posicao, registro in enumerate(registros, start=1):
        if not isinstance(registro, dict):
            raise ValueError(f'Registro {posicao}: formato inválido.')

        id_registro = _texto_obrigatorio(
            registro.get('id_registro'), 'id_registro', posicao
        )
        equipamento_id = _texto_obrigatorio(
            registro.get('equipamento_id'), 'equipamento_id', posicao
        )
        equipamento = _texto_obrigatorio(
            registro.get('equipamento'), 'equipamento', posicao
        )
        local = _texto_obrigatorio(registro.get('local'), 'local', posicao)

        if id_registro in ids:
            raise ValueError(f'Identificador repetido: {id_registro}.')
        ids.add(id_registro)

        if registro.get('recurso') != 'energia':
            raise ValueError(
                f'Registro {posicao}: recurso deve ser energia.'
            )

        consumo = _validar_decimal(
            registro.get('consumo_kwh'), 'consumo_kwh', posicao
        )
        horas = _validar_decimal(
            registro.get('horas_uso'), 'horas_uso', posicao
        )
        periodo_inicio = _validar_data(
            registro.get('periodo_inicio'), 'periodo_inicio', posicao
        )
        periodo_fim = _validar_data(
            registro.get('periodo_fim'), 'periodo_fim', posicao
        )

        if periodo_fim < periodo_inicio:
            raise ValueError(
                f'Registro {posicao}: período final anterior ao inicial.'
            )

        identidade = (equipamento, local)
        if equipamento_id in identidades and identidades[equipamento_id] != identidade:
            raise ValueError(
                f'Registro {posicao}: identidade do equipamento inconsistente.'
            )

        chave_periodo = (
            equipamento_id,
            local,
            periodo_inicio,
            periodo_fim,
        )
        if chave_periodo in chaves_periodos:
            raise ValueError(
                f'Registro {posicao}: período do equipamento repetido.'
            )

        identidades[equipamento_id] = identidade
        chaves_periodos.add(chave_periodo)
        validados.append({
            'id_registro': id_registro,
            'equipamento_id': equipamento_id,
            'equipamento': equipamento,
            'local': local,
            'recurso': 'energia',
            'consumo_kwh': consumo,
            'horas_uso': horas,
            'periodo_inicio': periodo_inicio,
            'periodo_fim': periodo_fim,
        })

    por_equipamento = {}
    for registro in validados:
        por_equipamento.setdefault(
            registro['equipamento_id'], []
        ).append(registro)

    for equipamento_id, itens in por_equipamento.items():
        ordenados = sorted(
            itens,
            key=lambda item: (
                item['periodo_inicio'],
                item['periodo_fim'],
            ),
        )
        ultimo_fim = None
        for registro in ordenados:
            if (
                ultimo_fim is not None and
                registro['periodo_inicio'] <= ultimo_fim
            ):
                raise ValueError(
                    f'Períodos sobrepostos para o equipamento '
                    f'{equipamento_id}.'
                )
            ultimo_fim = registro['periodo_fim']

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


def _calcular_grupo(registro):
    with localcontext() as contexto:
        contexto.prec = PRECISAO_CALCULO
        contexto.rounding = ARREDONDAMENTO

        consumo = registro['consumo_kwh']
        horas = registro['horas_uso']
        consumo_por_hora = None
        avaliacao = 'indisponivel'
        motivo = None

        if horas > 0:
            consumo_por_hora = _formatar_decimal(consumo / horas)
            avaliacao = 'disponivel'
        elif consumo == 0:
            motivo = (
                'Não há horas de uso positivas para calcular o consumo '
                'por hora.'
            )
        else:
            motivo = (
                'Há consumo registrado sem horas de uso; confira os '
                'registros antes de calcular o indicador.'
            )

        return {
            'id_registro': registro['id_registro'],
            'equipamento_id': registro['equipamento_id'],
            'equipamento': registro['equipamento'],
            'local': registro['local'],
            'recurso': registro['recurso'],
            'unidade_consumo': 'kWh',
            'unidade_horas': 'h',
            'unidade_consumo_por_hora': 'kWh/h',
            'consumo_kwh': _formatar_decimal(consumo),
            'horas_uso': _formatar_decimal(horas),
            'periodo_inicio': registro['periodo_inicio'].isoformat(),
            'periodo_fim': registro['periodo_fim'].isoformat(),
            'consumo_por_hora': consumo_por_hora,
            'avaliacao': avaliacao,
            'motivo': motivo,
        }


def calcular_consumo_por_hora(dados):
    """Calcula uma saída individual por registro, sem agregação."""
    registros = validar_dados_equipamentos(dados)
    ordenados = sorted(
        registros,
        key=lambda registro: (
            registro['equipamento_id'],
            registro['periodo_inicio'],
            registro['periodo_fim'],
        ),
    )

    return {
        'origem': dados['origem'],
        'grupos': [_calcular_grupo(registro) for registro in ordenados],
    }
