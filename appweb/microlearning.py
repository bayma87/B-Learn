import json
from decimal import Decimal
from pathlib import Path

from django.conf import settings

from .validacao import (
    ler_decimal,
    ler_inteiro,
    ler_lista,
    ler_texto,
    registrar_identificador,
    validar_cabecalho,
)


PILARES_VALIDOS = {'Ambiental', 'Social', 'Governança'}
CONDICOES_VALIDAS = {'acima', 'abaixo'}
UNIDADES_IMPACTO = {
    'energia_kwh': 'kWh de energia',
    'agua_l': 'litros de água',
    'residuos_kg': 'kg de resíduos reciclados',
}
NIVEIS = [
    (0, 'Iniciante'),
    (30, 'Engajado'),
    (70, 'Guardião ESG'),
    (120, 'Líder ESG'),
]


def carregar_catalogo():
    caminho = (
        Path(settings.BASE_DIR)
        / 'appweb'
        / 'dados'
        / 'microlearning.json'
    )
    dados = json.loads(caminho.read_text(encoding='utf-8'))
    return validar_catalogo(dados)


def _validar_pilar(registro):
    pilar = registro.get('pilar')

    if pilar not in PILARES_VALIDOS:
        raise ValueError('Pilar desconhecido.')

    return pilar


def _validar_conceito(registro, ids):
    return {
        'id': registrar_identificador(registro, ids),
        'pilar': _validar_pilar(registro),
        'titulo': ler_texto(registro, 'titulo', maximo=100),
        'texto': ler_texto(registro, 'texto', maximo=300),
        'exemplo': ler_texto(registro, 'exemplo', maximo=300),
    }


def _validar_quiz(registro, ids):
    opcoes = registro.get('opcoes')

    if (
        not isinstance(opcoes, list)
        or not 2 <= len(opcoes) <= 6
        or not all(isinstance(o, str) and o.strip() for o in opcoes)
    ):
        raise ValueError('Quiz: informe de 2 a 6 opções de texto.')

    correta = ler_inteiro(registro, 'correta')

    if correta >= len(opcoes):
        raise ValueError('Quiz: alternativa correta fora das opções.')

    return {
        'id': registrar_identificador(registro, ids),
        'pilar': _validar_pilar(registro),
        'pergunta': ler_texto(registro, 'pergunta', maximo=200),
        'opcoes': [o.strip() for o in opcoes],
        'correta': correta,
        'explicacao': ler_texto(registro, 'explicacao', maximo=300),
        'pontos': ler_inteiro(registro, 'pontos', minimo=1),
    }


def _validar_desafio(registro, ids):
    desafio = {
        'id': registrar_identificador(registro, ids),
        'pilar': _validar_pilar(registro),
        'titulo': ler_texto(registro, 'titulo', maximo=100),
        'descricao': ler_texto(registro, 'descricao', maximo=300),
        'pontos': ler_inteiro(registro, 'pontos', minimo=1),
        'impacto': None,
    }
    impacto = registro.get('impacto')

    if impacto is not None:
        if (
            not isinstance(impacto, dict)
            or impacto.get('tipo') not in UNIDADES_IMPACTO
        ):
            raise ValueError('Desafio: impacto inválido.')

        desafio['impacto'] = {
            'tipo': impacto['tipo'],
            'valor': ler_decimal(impacto, 'valor'),
        }

    return desafio


def _validar_gatilho(registro, ids, ids_desafios):
    condicao = registro.get('condicao')
    desafio_id = ler_texto(registro, 'desafio_id', maximo=50)

    if condicao not in CONDICOES_VALIDAS:
        raise ValueError('Gatilho: condição deve ser acima ou abaixo.')

    if desafio_id not in ids_desafios:
        raise ValueError(f'Gatilho: desafio inexistente ({desafio_id}).')

    return {
        'id': registrar_identificador(registro, ids),
        'sensor': ler_texto(registro, 'sensor', maximo=100),
        'local': ler_texto(registro, 'local', maximo=100),
        'leitura': ler_decimal(registro, 'leitura'),
        'unidade': ler_texto(registro, 'unidade', maximo=100),
        'limite': ler_decimal(registro, 'limite'),
        'condicao': condicao,
        'mensagem': ler_texto(registro, 'mensagem', maximo=300),
        'desafio_id': desafio_id,
    }


def validar_catalogo(dados):
    validar_cabecalho(dados)

    ids = set()
    conceitos = [
        _validar_conceito(r, ids) for r in ler_lista(dados, 'conceitos')
    ]
    quizzes = [_validar_quiz(r, ids) for r in ler_lista(dados, 'quizzes')]
    desafios = [_validar_desafio(r, ids) for r in ler_lista(dados, 'desafios')]
    ids_desafios = {d['id'] for d in desafios}
    gatilhos = [
        _validar_gatilho(r, ids, ids_desafios)
        for r in ler_lista(dados, 'gatilhos_iot')
    ]

    return {
        'conceitos': conceitos,
        'quizzes': quizzes,
        'desafios': desafios,
        'gatilhos': gatilhos,
    }


def gatilho_ativo(gatilho):
    if gatilho['condicao'] == 'acima':
        return gatilho['leitura'] > gatilho['limite']

    return gatilho['leitura'] < gatilho['limite']


def _nivel(pontos):
    atual = NIVEIS[0][1]
    proximo = None

    for minimo, nome in NIVEIS:
        if pontos >= minimo:
            atual = nome
        elif proximo is None:
            proximo = {'nome': nome, 'faltam': minimo - pontos}

    return atual, proximo


def calcular_progresso(catalogo, concluidos):
    itens = {
        item['id']: item for item in catalogo['quizzes'] + catalogo['desafios']
    }
    feitos = {i for i in concluidos if i in itens}
    pontos = sum(itens[i]['pontos'] for i in feitos)
    nivel, proximo = _nivel(pontos)

    impacto = {tipo: Decimal('0') for tipo in UNIDADES_IMPACTO}
    for desafio in catalogo['desafios']:
        if desafio['id'] in feitos and desafio['impacto']:
            impacto[desafio['impacto']['tipo']] += desafio['impacto']['valor']

    return {
        'pontos': pontos,
        'nivel': nivel,
        'proximo_nivel': proximo,
        'concluidos': sorted(feitos),
        'total_itens': len(itens),
        'impacto': [
            {'tipo': tipo, 'valor': f'{impacto[tipo]:.2f}', 'rotulo': rotulo}
            for tipo, rotulo in UNIDADES_IMPACTO.items()
        ],
    }


def montar_painel(catalogo, concluidos):
    desafios = {d['id']: d for d in catalogo['desafios']}

    def impacto_publico(desafio):
        if not desafio['impacto']:
            return None

        return {
            'valor': f"{desafio['impacto']['valor']:.2f}",
            'rotulo': UNIDADES_IMPACTO[desafio['impacto']['tipo']],
        }

    return {
        'origem': 'simulada',
        'conceitos': catalogo['conceitos'],
        'quizzes': [
            {k: q[k] for k in ('id', 'pilar', 'pergunta', 'opcoes', 'pontos')}
            for q in catalogo['quizzes']
        ],
        'desafios': [
            {
                'id': d['id'],
                'pilar': d['pilar'],
                'titulo': d['titulo'],
                'descricao': d['descricao'],
                'pontos': d['pontos'],
                'impacto': impacto_publico(d),
            }
            for d in catalogo['desafios']
        ],
        'gatilhos': [
            {
                'id': g['id'],
                'sensor': g['sensor'],
                'local': g['local'],
                'leitura': f"{g['leitura']:.2f}",
                'unidade': g['unidade'],
                'limite': f"{g['limite']:.2f}",
                'condicao': g['condicao'],
                'mensagem': g['mensagem'],
                'ativo': gatilho_ativo(g),
                'desafio_id': g['desafio_id'],
                'desafio_titulo': desafios[g['desafio_id']]['titulo'],
            }
            for g in catalogo['gatilhos']
        ],
        'progresso': calcular_progresso(catalogo, concluidos),
    }


def registrar_resposta(catalogo, concluidos, item_id, resposta=None):
    """Valida uma resposta e devolve (resultado, novos_concluidos).

    Quiz errado não conclui o item (pode tentar de novo); cada item rende
    pontos uma única vez.
    """
    quizzes = {q['id']: q for q in catalogo['quizzes']}
    desafios = {d['id']: d for d in catalogo['desafios']}
    concluidos = set(concluidos)
    resultado = {'id': item_id, 'pontos_ganhos': 0, 'ja_concluido': False}

    if item_id in quizzes:
        item = quizzes[item_id]

        if type(resposta) is not int or not 0 <= resposta < len(item['opcoes']):
            raise ValueError('Resposta inválida.')

        resultado['tipo'] = 'quiz'
        resultado['correta'] = resposta == item['correta']
        resultado['explicacao'] = item['explicacao']
        concluir = resultado['correta']
    elif item_id in desafios:
        item = desafios[item_id]
        resultado['tipo'] = 'desafio'
        concluir = True
    else:
        raise ValueError('Item desconhecido.')

    if item_id in concluidos:
        resultado['ja_concluido'] = True
    elif concluir:
        concluidos.add(item_id)
        resultado['pontos_ganhos'] = item['pontos']

    return resultado, concluidos
