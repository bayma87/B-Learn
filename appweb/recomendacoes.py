"""Recomendações de investimento ESG (F5) a partir de dados simulados.

Premissas demonstrativas (não constituem orientação financeira):

- Payback simples = custo / economia mensal.
- Prioridade por payback, calculada sobre o payback NÃO arredondado:
    - até 6 meses = 'Alta';
    - acima de 6 até 12 meses = 'Média';
    - acima de 12 meses = 'Baixa'.
- Faixas de investimento: mínimo = custo x 0,85; recomendado = custo;
  máximo = custo x 1,25.
- Arredondamento: ROUND_HALF_UP, com 1 casa decimal para o payback
  apresentado e 2 casas para os valores financeiros.

A prioridade expressa apenas retorno financeiro estimado; não é uma
avaliação completa do impacto ESG da ação.
"""

import json
import os
import re
from decimal import Decimal, ROUND_HALF_UP

LIMITE_ALTA_MESES = Decimal('6')
LIMITE_MEDIA_MESES = Decimal('12')

FATOR_MINIMO = Decimal('0.85')
FATOR_MAXIMO = Decimal('1.25')

ARREDONDAMENTO = ROUND_HALF_UP
CASAS_PAYBACK = Decimal('0.1')
CASAS_FINANCEIRO = Decimal('0.01')

MOTIVO_ECONOMIA_INVALIDA = (
    'payback indisponível: a economia mensal deve ser maior que zero.'
)

_QUANTIDADE_RE = re.compile(r'-?[0-9]{1,8}\.[0-9]{2}')


def carregar_catalogo_acoes(caminho=None):
    """Carrega o catálogo de ações a partir do JSON de dados simulados."""
    if caminho is None:
        caminho = os.path.join(
            os.path.dirname(__file__), 'dados', 'acoes_esg.json'
        )

    try:
        with open(caminho, encoding='utf-8') as arquivo:
            conteudo = arquivo.read()
    except OSError:
        raise ValueError(
            'Não foi possível ler o arquivo do catálogo de ações.'
        ) from None

    if not conteudo.strip():
        raise ValueError('O arquivo do catálogo está vazio.')

    try:
        return json.loads(conteudo)
    except ValueError:
        raise ValueError(
            'O arquivo do catálogo não contém JSON válido.'
        ) from None


def validar_catalogo_acoes(dados):
    """Valida o catálogo e devolve os registros com valores decimais."""
    if not isinstance(dados, dict):
        raise ValueError('A entrada deve ser um objeto JSON.')

    if type(dados.get('versao')) is not int or dados['versao'] != 1:
        raise ValueError('A versão deve ser o número inteiro 1.')

    if dados.get('origem') != 'simulada':
        raise ValueError('Esta versão aceita apenas origem simulada.')

    registros = dados.get('registros')

    if not isinstance(registros, list) or not registros:
        raise ValueError('Informe uma lista não vazia de registros.')

    validados = []
    identificadores = set()

    for posicao, registro in enumerate(registros, start=1):
        if not isinstance(registro, dict):
            raise ValueError(f'Registro {posicao}: formato inválido.')

        identificador = registro.get('id_acao')
        nome = registro.get('nome')
        pilar = registro.get('pilar')
        custo_texto = registro.get('custo')
        economia_texto = registro.get('economia_mensal')

        if not isinstance(identificador, str) or not identificador.strip():
            raise ValueError(f'Registro {posicao}: id_acao obrigatório.')

        identificador = identificador.strip()

        if identificador in identificadores:
            raise ValueError(f'Identificador repetido: {identificador}.')

        if not isinstance(nome, str) or not 1 <= len(nome.strip()) <= 200:
            raise ValueError(f'Registro {posicao}: nome inválido.')

        if not isinstance(pilar, str) or not 1 <= len(pilar.strip()) <= 50:
            raise ValueError(f'Registro {posicao}: pilar inválido.')

        if not isinstance(custo_texto, str) or not _QUANTIDADE_RE.fullmatch(
            custo_texto
        ):
            raise ValueError(
                f'Registro {posicao}: custo inválido. Use um valor como 2500.00.'
            )

        if not isinstance(economia_texto, str) or not _QUANTIDADE_RE.fullmatch(
            economia_texto
        ):
            raise ValueError(
                f'Registro {posicao}: economia mensal inválida. '
                'Use um valor como 450.00.'
            )

        custo = Decimal(custo_texto)
        economia = Decimal(economia_texto)

        if custo <= 0:
            raise ValueError(
                f'Registro {posicao}: o custo deve ser maior que zero.'
            )

        identificadores.add(identificador)

        validados.append({
            'id_acao': identificador,
            'nome': nome.strip(),
            'pilar': pilar.strip(),
            'custo': custo,
            'economia_mensal': economia,
        })

    return validados


def _arredondar(valor, casas):
    return valor.quantize(casas, rounding=ARREDONDAMENTO)


def _classificar_prioridade(payback_meses):
    """Classifica pelo payback NÃO arredondado."""
    if payback_meses <= LIMITE_ALTA_MESES:
        return 'Alta'

    if payback_meses <= LIMITE_MEDIA_MESES:
        return 'Média'

    return 'Baixa'


def _montar_recomendacao(registro):
    custo = registro['custo']
    economia = registro['economia_mensal']

    recomendacao = {
        'id_acao': registro['id_acao'],
        'acao': registro['nome'],
        'pilar': registro['pilar'],
        'investimento_sugerido': {
            'minimo': f'{_arredondar(custo * FATOR_MINIMO, CASAS_FINANCEIRO):f}',
            'recomendado': f'{_arredondar(custo, CASAS_FINANCEIRO):f}',
            'maximo': f'{_arredondar(custo * FATOR_MAXIMO, CASAS_FINANCEIRO):f}',
        },
        'economia_estimada_mensal': (
            f'{_arredondar(economia, CASAS_FINANCEIRO):f}'
        ),
        'payback_meses': None,
        'prioridade': None,
        'payback_indisponivel': None,
        'dados_simulados': True,
    }

    if economia <= 0:
        recomendacao['payback_indisponivel'] = MOTIVO_ECONOMIA_INVALIDA
        return recomendacao, None

    payback_meses = custo / economia

    recomendacao['payback_meses'] = f'{_arredondar(payback_meses, CASAS_PAYBACK):f}'
    recomendacao['prioridade'] = _classificar_prioridade(payback_meses)

    return recomendacao, payback_meses


def gerar_recomendacoes(dados=None):
    """Gera as recomendações ordenadas do catálogo validado.

    A ordenação usa os valores NÃO arredondados: economia mensal
    decrescente e, em empate, payback crescente. Registros sem payback
    disponível são apresentados ao final, sem prioridade.
    """
    if dados is None:
        dados = carregar_catalogo_acoes()

    registros = validar_catalogo_acoes(dados)

    itens = []
    for registro in registros:
        recomendacao, payback_meses = _montar_recomendacao(registro)
        itens.append((recomendacao, payback_meses, registro['economia_mensal']))

    itens.sort(
        key=lambda item: (
            item[2] * -1,
            item[1] if item[1] is not None else Decimal('Infinity'),
        )
    )

    return [item[0] for item in itens]
