"""Acompanhamento temporal simulado antes/depois de ações ESG (F6).

Este módulo substitui o comparativo com o ``depois`` fixado em zero por uma
comparação temporal simulada entre janelas de igual duração, definidas a
partir de uma data de implantação explícita. Cobre somente ações
configuradas em um cenário dedicado (``dados/acompanhamento_f6.json``);
ações sem configuração recebem ausência de acompanhamento com motivo, sem
valores fabricados.

As fórmulas de variação percentual e de diferença de custo com tarifa
foram parcialmente adaptadas da contribuição de Arthur Alencar
(``origin/feature/dados-iot``, commit ``9b3bd73``, PR nº 15). O
reaproveitamento é parcial: somente as fórmulas e a ligação entre ação e
comparativo foram aproveitadas; a aplicação Flask do PR não foi
incorporada.

A comparação é temporal e simulada; não demonstra causalidade. Os
cálculos usam ``Decimal`` sem arredondamento intermediário; o
arredondamento (ROUND_HALF_UP, 2 casas) acontece apenas na
serialização. O dia da implantação é excluído de ambas as janelas.
"""

import copy
import json
import re
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP, localcontext
from pathlib import Path


PRECISAO_CALCULO = 28
ARREDONDAMENTO = ROUND_HALF_UP
CASAS_APRESENTACAO = Decimal('0.01')

SITUACAO_COM_DADOS = 'com_dados'
SITUACAO_SEM_DADOS = 'sem_dados'

TENDENCIA_QUEDA = 'queda'
TENDENCIA_AUMENTO = 'aumento'
TENDENCIA_ESTAVEL = 'estavel'

ORIENTACAO_REDUCAO = 'reducao_estimada'
ORIENTACAO_AUMENTO = 'aumento_estimado'
ORIENTACAO_ESTAVEL = 'estavel'

AVISO_CAUSAL = (
    'Cenário simulado de demonstração. A data de implantação, as leituras '
    'posteriores e a tarifa são premissas do exemplo. A comparação não '
    'comprova efeito causado pela ação.'
)

MOTIVO_BASE_ZERO = (
    'Base zero: a média do período anterior é 0,00 e a variação '
    'percentual não é calculável.'
)

MOTIVO_SEM_CONFIGURACAO = (
    'Ação sem configuração de acompanhamento: sem data de implantação '
    'registrada.'
)

_VALOR_RE = re.compile(r'(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z')
_DATA_RE = re.compile(r'\d{4}-\d{2}-\d{2}\Z')


def carregar_acompanhamentos(caminho=None):
    """Carrega o cenário simulado de acompanhamento sem fallback artificial."""
    if caminho is None:
        caminho = Path(__file__).parent / 'dados' / 'acompanhamento_f6.json'

    try:
        conteudo = Path(caminho).read_text(encoding='utf-8')
        return json.loads(conteudo)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            'Não foi possível carregar os dados de acompanhamento.'
        ) from exc


def _parse_data(texto, rotulo):
    if not isinstance(texto, str) or not _DATA_RE.fullmatch(texto):
        raise ValueError(f'{rotulo}: data inválida (use AAAA-MM-DD).')

    try:
        return date.fromisoformat(texto)
    except ValueError as exc:
        raise ValueError(f'{rotulo}: data inexistente no calendário.') from exc


def _parse_decimal(texto, rotulo):
    if not isinstance(texto, str) or not _VALOR_RE.fullmatch(texto):
        raise ValueError(f'{rotulo}: valor decimal inválido.')
    return Decimal(texto)


def _texto_obrigatorio(valor, rotulo):
    if not isinstance(valor, str) or not valor.strip():
        raise ValueError(f'{rotulo}: texto obrigatório.')
    return valor


def _inteiro_positivo(valor, rotulo):
    if type(valor) is not int or valor <= 0:
        raise ValueError(f'{rotulo}: deve ser um inteiro positivo.')
    return valor


def _validar_leitura(leitura, posicao, id_acompanhamento):
    rotulo = (
        f'Acompanhamento {id_acompanhamento}, leitura {posicao}'
    )
    if not isinstance(leitura, dict):
        raise ValueError(f'{rotulo}: deve ser um objeto.')

    data_leitura = _parse_data(leitura.get('data'), f'{rotulo}, data')
    valor = _parse_decimal(leitura.get('valor'), f'{rotulo}, valor')
    return data_leitura, valor


def validar_acompanhamentos(dados):
    """Valida o cenário e retorna uma cópia; nunca altera a entrada."""
    if not isinstance(dados, dict):
        raise ValueError('Os dados de acompanhamento devem ser um objeto.')

    if dados.get('origem') != 'simulada':
        raise ValueError(
            'Os dados de acompanhamento devem ter origem simulada.'
        )

    acompanhamentos = dados.get('acompanhamentos')
    if not isinstance(acompanhamentos, list):
        raise ValueError(
            'Os dados de acompanhamento devem conter a lista acompanhamentos.'
        )

    identificadores = set()
    validados = []
    for posicao, config in enumerate(acompanhamentos, start=1):
        if not isinstance(config, dict):
            raise ValueError(
                f'Acompanhamento {posicao}: deve ser um objeto.'
            )

        id_acompanhamento = _texto_obrigatorio(
            config.get('id_acompanhamento'),
            f'Acompanhamento {posicao}, id_acompanhamento',
        )
        if id_acompanhamento in identificadores:
            raise ValueError(
                f'Acompanhamento {posicao}: id_acompanhamento repetido.'
            )
        identificadores.add(id_acompanhamento)

        _texto_obrigatorio(
            config.get('id_acao'),
            f'Acompanhamento {id_acompanhamento}, id_acao',
        )
        _texto_obrigatorio(
            config.get('recurso'),
            f'Acompanhamento {id_acompanhamento}, recurso',
        )
        _texto_obrigatorio(
            config.get('unidade'),
            f'Acompanhamento {id_acompanhamento}, unidade',
        )
        _texto_obrigatorio(
            config.get('moeda'),
            f'Acompanhamento {id_acompanhamento}, moeda',
        )
        _texto_obrigatorio(
            config.get('local'),
            f'Acompanhamento {id_acompanhamento}, local',
        )
        _parse_data(
            config.get('data_implantacao'),
            f'Acompanhamento {id_acompanhamento}, data_implantacao',
        )
        _inteiro_positivo(
            config.get('janela_dias'),
            f'Acompanhamento {id_acompanhamento}, janela_dias',
        )
        _inteiro_positivo(
            config.get('projecao_dias'),
            f'Acompanhamento {id_acompanhamento}, projecao_dias',
        )
        tarifa = _parse_decimal(
            config.get('tarifa'),
            f'Acompanhamento {id_acompanhamento}, tarifa',
        )
        if tarifa <= 0:
            raise ValueError(
                f'Acompanhamento {id_acompanhamento}, tarifa: deve ser '
                'maior que zero.'
            )

        leituras = config.get('leituras')
        if not isinstance(leituras, list):
            raise ValueError(
                f'Acompanhamento {id_acompanhamento}, leituras: deve ser '
                'uma lista.'
            )

        datas_vistas = set()
        for posicao_leitura, leitura in enumerate(leituras, start=1):
            data_leitura, _ = _validar_leitura(
                leitura,
                posicao_leitura,
                id_acompanhamento,
            )
            if data_leitura in datas_vistas:
                raise ValueError(
                    f'Acompanhamento {id_acompanhamento}, leitura '
                    f'{posicao_leitura}: data duplicada '
                    f'({data_leitura.isoformat()}).'
                )
            datas_vistas.add(data_leitura)

        validados.append(copy.deepcopy(config))

    return validados


def _janelas(data_implantacao, janela_dias):
    antes = [
        data_implantacao - timedelta(days=dias)
        for dias in range(janela_dias, 0, -1)
    ]
    depois = [
        data_implantacao + timedelta(days=dias)
        for dias in range(1, janela_dias + 1)
    ]
    return antes, depois


def _formatar(valor):
    with localcontext() as contexto:
        contexto.prec = PRECISAO_CALCULO
        arredondado = valor.quantize(
            CASAS_APRESENTACAO,
            rounding=ARREDONDAMENTO,
        )
    return str(arredondado)


def _periodo(dias):
    return {
        'inicio': dias[0].isoformat(),
        'fim': dias[-1].isoformat(),
        'dias': len(dias),
    }


def _sem_dados(config, motivo):
    return {
        'id_acompanhamento': config['id_acompanhamento'],
        'id_acao': config['id_acao'],
        'origem': 'simulada',
        'situacao': SITUACAO_SEM_DADOS,
        'recurso': config['recurso'],
        'unidade': config['unidade'],
        'local': config['local'],
        'data_implantacao': config['data_implantacao'],
        'motivo': motivo,
    }


def _motivo_cobertura(nome, periodo, total, encontrados):
    if not encontrados:
        return (
            f'Sem leituras no período {nome} '
            f'({periodo["inicio"]} a {periodo["fim"]}).'
        )
    faltantes = total - len(encontrados)
    return (
        f'Cobertura diária incompleta no período {nome} '
        f'({periodo["inicio"]} a {periodo["fim"]}): '
        f'{faltantes} dia(s) sem leitura.'
    )


def calcular_acompanhamento(config):
    """Calcula a comparação temporal de uma configuração validada.

    Não inventa leituras: cobertura ausente ou incompleta resulta em
    ``sem_dados`` com motivo. Dados estruturalmente inválidos levantam
    ``ValueError`` e não são confundidos com ausência de dados.
    """
    if not isinstance(config, dict):
        raise ValueError('A configuração de acompanhamento deve ser um objeto.')

    id_acompanhamento = config['id_acompanhamento']
    data_implantacao = _parse_data(
        config['data_implantacao'],
        f'Acompanhamento {id_acompanhamento}, data_implantacao',
    )
    janela_dias = _inteiro_positivo(
        config['janela_dias'],
        f'Acompanhamento {id_acompanhamento}, janela_dias',
    )
    tarifa = _parse_decimal(
        config['tarifa'],
        f'Acompanhamento {id_acompanhamento}, tarifa',
    )
    projecao_dias = _inteiro_positivo(
        config['projecao_dias'],
        f'Acompanhamento {id_acompanhamento}, projecao_dias',
    )

    datas_antes, datas_depois = _janelas(data_implantacao, janela_dias)
    conjunto_antes = set(datas_antes)
    conjunto_depois = set(datas_depois)

    valores_antes = {}
    valores_depois = {}
    for posicao_leitura, leitura in enumerate(config['leituras'], start=1):
        data_leitura, valor = _validar_leitura(
            leitura,
            posicao_leitura,
            id_acompanhamento,
        )
        if data_leitura == data_implantacao:
            continue
        if data_leitura in conjunto_antes:
            valores_antes[data_leitura] = valor
        elif data_leitura in conjunto_depois:
            valores_depois[data_leitura] = valor
        else:
            raise ValueError(
                f'Acompanhamento {id_acompanhamento}, leitura '
                f'{posicao_leitura}: data fora das janelas de '
                'acompanhamento.'
            )

    periodo_antes = _periodo(datas_antes)
    periodo_depois = _periodo(datas_depois)

    if len(valores_antes) != janela_dias:
        return _sem_dados(
            config,
            _motivo_cobertura(
                'antes',
                periodo_antes,
                janela_dias,
                valores_antes,
            ),
        )

    if len(valores_depois) != janela_dias:
        return _sem_dados(
            config,
            _motivo_cobertura(
                'depois',
                periodo_depois,
                janela_dias,
                valores_depois,
            ),
        )

    with localcontext() as contexto:
        contexto.prec = PRECISAO_CALCULO
        media_antes = sum(valores_antes.values()) / janela_dias
        media_depois = sum(valores_depois.values()) / janela_dias
        diferenca = media_depois - media_antes
        if media_antes == 0:
            variacao = None
        else:
            variacao = diferenca / media_antes * 100
        custo = diferenca * tarifa
        projecao = custo * projecao_dias

    if diferenca < 0:
        tendencia = TENDENCIA_QUEDA
    elif diferenca > 0:
        tendencia = TENDENCIA_AUMENTO
    else:
        tendencia = TENDENCIA_ESTAVEL

    if custo < 0:
        orientacao = ORIENTACAO_REDUCAO
    elif custo > 0:
        orientacao = ORIENTACAO_AUMENTO
    else:
        orientacao = ORIENTACAO_ESTAVEL

    resultado = {
        'id_acompanhamento': id_acompanhamento,
        'id_acao': config['id_acao'],
        'origem': 'simulada',
        'situacao': SITUACAO_COM_DADOS,
        'recurso': config['recurso'],
        'unidade': config['unidade'],
        'unidade_medias': f'{config["unidade"]}/dia',
        'local': config['local'],
        'data_implantacao': config['data_implantacao'],
        'periodo_antes': periodo_antes,
        'periodo_depois': periodo_depois,
        'media_antes': _formatar(media_antes),
        'media_depois': _formatar(media_depois),
        'diferenca_absoluta': _formatar(diferenca),
        'variacao_percentual': (
            None if variacao is None else _formatar(variacao)
        ),
        'tendencia': tendencia,
        'custo_diferenca': {
            'valor': _formatar(custo),
            'moeda': config['moeda'],
            'periodo': 'por_dia',
            'premissa_tarifa': config['tarifa'],
            'orientacao': orientacao,
            'natureza': 'estimativa_demonstrativa',
        },
        'projecao_mensal': {
            'dias': projecao_dias,
            'valor': _formatar(projecao),
            'premissa': (
                f'Projeção demonstrativa: diferença por dia x '
                f'{projecao_dias} dias. Não é medição nem garantia '
                'de resultado.'
            ),
        },
        'aviso_causal': AVISO_CAUSAL,
    }
    if variacao is None:
        resultado['motivo'] = MOTIVO_BASE_ZERO
    return resultado


def montar_acompanhamento(configs, acoes_por_id=None):
    """Monta a lista de acompanhamento; ação configurada nunca é omitida."""
    acoes = acoes_por_id or {}
    itens = []
    for config in configs:
        item = calcular_acompanhamento(config)
        acao = acoes.get(config['id_acao'])
        item['acao'] = (
            acao.get('acao') if isinstance(acao, dict) else None
        )
        itens.append(item)
    return itens


def anexar_ausencia_acompanhamento(sugestao, ids_configurados):
    """Copia a sugestão e registra ausência de acompanhamento, se couber."""
    resultado = copy.deepcopy(sugestao)
    if resultado.get('id_acao') in ids_configurados:
        return resultado
    resultado['acompanhamento'] = {
        'situacao': SITUACAO_SEM_DADOS,
        'motivo': MOTIVO_SEM_CONFIGURACAO,
    }
    return resultado
