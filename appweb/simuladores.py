"""Adaptadores finos para os simuladores educativos.

Este módulo não contém fórmulas de cálculo. Ele apenas:

- lê o cenário simulado já existente em ``comparativos.py``;
- transforma poucas entradas do formulário na estrutura aceita pelo
  backend;
- devolve os resultados produzidos pelas funções existentes;
- mapeia falhas de validação para os campos correspondentes.

Nenhuma entrada do usuário altera fixtures, banco de dados ou sessão.
"""

import copy
import re
from decimal import Decimal, InvalidOperation

from .comparativos import (
    calcular_acompanhamento,
    carregar_acompanhamentos,
    validar_acompanhamentos,
)
from .recomendacoes import carregar_catalogo_acoes


_VALOR_RE = re.compile(r'(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z')
_LEITURA_RE = re.compile(r'leitura (\d+)')

MENSAGEM_NUMERO = (
    'Informe um número não negativo, usando ponto como separador decimal '
    '(exemplo: 50.50).'
)
MENSAGEM_CARDINALIDADE = 'Informe exatamente {quantidade} valores.'
MENSAGEM_OBRIGATORIO = 'Este campo é obrigatório.'


def _carregar_config():
    """Devolve a configuração validada do cenário F6."""
    configs = validar_acompanhamentos(carregar_acompanhamentos())
    if len(configs) != 1:
        raise ValueError('O cenário do simulador deve conter uma ação.')
    return configs[0]


def _nome_acao(id_acao):
    """Lê apenas o nome da ação no catálogo simulado existente."""
    try:
        catalogo = carregar_catalogo_acoes()
    except ValueError:
        return f'Ação {id_acao}'

    for registro in catalogo.get('registros', []):
        if isinstance(registro, dict) and registro.get('id_acao') == id_acao:
            nome = registro.get('nome')
            if isinstance(nome, str) and nome.strip():
                return nome.strip()
    return f'Ação {id_acao}'


def _periodo(config):
    """Obtém as janelas a partir do cálculo existente, sem expor resultados."""
    processado = calcular_acompanhamento(config)
    return processado['periodo_antes'], processado['periodo_depois']


def carregar_cenario_ambiental():
    """Monta o estado inicial do simulador a partir da fixture existente."""
    config = _carregar_config()
    janela = config['janela_dias']
    leituras = config['leituras']

    antes = [item['valor'] for item in leituras[:janela]]
    depois = [item['valor'] for item in leituras[janela:janela * 2]]
    periodo_antes, periodo_depois = _periodo(config)

    def linhas(inicio, quantidade):
        return [
            {
                'indice': indice,
                'data': leituras[inicio + indice]['data'],
                'valor': leituras[inicio + indice]['valor'],
            }
            for indice in range(quantidade)
        ]

    return {
        'config': config,
        'valores': {
            'consumos_antes': antes,
            'consumos_depois': depois,
            'tarifa': config['tarifa'],
        },
        'linhas_antes': linhas(0, janela),
        'linhas_depois': linhas(janela, janela),
        'janela': janela,
        'periodo_antes': periodo_antes,
        'periodo_depois': periodo_depois,
        'unidade': config['unidade'],
        'unidade_medias': f'{config["unidade"]}/dia',
        'moeda': config['moeda'],
        'projecao_dias': config['projecao_dias'],
        'acao': _nome_acao(config['id_acao']),
        'local': config['local'],
        'aviso_causal': (
            'Cenário fictício de demonstração. A data de implantação, as '
            'leituras posteriores e a tarifa são premissas do exemplo. A '
            'comparação não comprova efeito causado pela ação.'
        ),
    }


def _valor_valido(valor):
    """Validação de formato da interface; a validação final é do backend."""
    if not isinstance(valor, str):
        return False
    texto = valor.strip()
    if not _VALOR_RE.fullmatch(texto):
        return False
    try:
        numero = Decimal(texto)
    except InvalidOperation:
        return False
    return numero.is_finite() and numero >= 0


def _campo_para_erro(mensagem, janela):
    """Mapeia mensagem do validador existente para o campo do formulário."""
    if 'tarifa' in mensagem:
        return 'tarifa', MENSAGEM_NUMERO

    encontrado = _LEITURA_RE.search(mensagem)
    if encontrado:
        numero = int(encontrado.group(1))
        if numero <= janela:
            return f'consumos_antes[{numero - 1}]', MENSAGEM_NUMERO
        return f'consumos_depois[{numero - janela - 1}]', MENSAGEM_NUMERO

    return 'payload', mensagem


def aplicar_cenario_ambiental(config_base, payload):
    """Aplica entradas do formulário sobre uma cópia da configuração.

    Devolve ``(config, resultado, erros)``. Em caso de erro, ``config`` e
    ``resultado`` são ``None`` e ``erros`` mapeia campo -> mensagem.
    """
    if not isinstance(payload, dict):
        return None, None, {'payload': 'O corpo deve ser um objeto JSON.'}

    janela = config_base['janela_dias']
    antes = payload.get('consumos_antes')
    depois = payload.get('consumos_depois')
    tarifa = payload.get('tarifa')
    erros = {}

    for nome, valores in (
        ('consumos_antes', antes),
        ('consumos_depois', depois),
    ):
        if not isinstance(valores, list) or len(valores) != janela:
            erros[nome] = MENSAGEM_CARDINALIDADE.format(quantidade=janela)
            continue
        for indice, valor in enumerate(valores):
            if _valor_valido(valor):
                continue
            chave = f'{nome}[{indice}]'
            if valor is None or (isinstance(valor, str) and not valor.strip()):
                erros[chave] = MENSAGEM_OBRIGATORIO
            else:
                erros[chave] = MENSAGEM_NUMERO

    if tarifa is None or (isinstance(tarifa, str) and not tarifa.strip()):
        erros['tarifa'] = MENSAGEM_OBRIGATORIO
    elif not _valor_valido(tarifa):
        erros['tarifa'] = MENSAGEM_NUMERO

    if erros:
        return None, None, erros

    config = copy.deepcopy(config_base)
    for indice, valor in enumerate(antes):
        config['leituras'][indice]['valor'] = valor.strip()
    for indice, valor in enumerate(depois):
        config['leituras'][janela + indice]['valor'] = valor.strip()
    config['tarifa'] = tarifa.strip()

    try:
        validados = validar_acompanhamentos({
            'origem': 'simulada',
            'acompanhamentos': [config],
        })
        resultado = calcular_acompanhamento(validados[0])
    except ValueError as exc:
        campo, mensagem = _campo_para_erro(str(exc), janela)
        return None, None, {campo: mensagem}

    return config, resultado, {}
